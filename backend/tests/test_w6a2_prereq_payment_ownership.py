"""
W6A2-C4 — a refund's cancellation intent must outlive its inability to act.

THE HOLE, EXACTLY
A refund arrives while a reschedule owns the appointment, so it cannot mutate the
provider and skips. The reschedule then ends in create_failed — the one terminal
state that deliberately leaves the source ACTIVE — and releases its claim. The
customer has their money back, the appointment is still live, and nothing
anywhere records that anyone wanted it cancelled.

"The current owner will subsume it" holds for owners that cancel, and fails for
precisely the branch that doesn't. test_SYNTHETIC_reschedule_then_refund below is
that counterexample, end to end.

The other half is resurrection: a delayed payment webhook flipping a cancelled
appointment back to confirmed, leaving a phantom whose booking is already gone.
"""
import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import pytest

from db import mutation_claims as db_mc
from services import appointment_cancel_intent as intent
from services import appointment_cancellation as cancel_svc
from services import mutation_ownership as mo

TID, APPT, BOOKING = "t-dani", "appt-1", "BK-CORK"
APPT_ROW = {"id": APPT, "tenant_id": TID, "status": "confirmed",
            "google_event_id": BOOKING, "provider_location_id": "L0Q8GTAZCHD42",
            "caller_phone": "+353871234567"}
TENANT = {"id": TID, "square_appointments_enabled": True}
PAYMENT = {"id": "pay-1", "status": "succeeded", "appointment_id": APPT,
           "amount_cents": 2500, "currency": "usd"}


class Claims:
    """Fake appointment_mutation_claims with the real PK + CAS rules."""
    AT = "2026-09-11T12:00:00+00:00"

    def __init__(self):
        self.rows = {}
        self.lock = asyncio.Lock()

    def seed(self, appointment_id, op_type, token="other", reason=None):
        self.rows[appointment_id] = {
            "appointment_id": appointment_id, "tenant_id": TID,
            "operation_type": op_type,
            "operation_id": "op-1" if op_type == db_mc.OP_RESCHEDULE else None,
            "reconcile_reason": reason, "claim_token": token, "claimed_at": self.AT}

    async def get_claim(self, appointment_id):
        r = self.rows.get(appointment_id)
        return dict(r) if r else None

    async def acquire_cancel_claim(self, appointment_id, tenant_id, claim_token):
        async with self.lock:
            if appointment_id in self.rows:
                return None
            self.rows[appointment_id] = {
                "appointment_id": appointment_id, "tenant_id": tenant_id,
                "operation_type": db_mc.OP_CANCEL, "operation_id": None,
                "reconcile_reason": None, "claim_token": claim_token,
                "claimed_at": self.AT}
            return dict(self.rows[appointment_id])

    async def transition_cancel_to_reconcile(self, appointment_id, token, claimed_at, reason):
        r = self.rows.get(appointment_id)
        if r and r["operation_type"] == db_mc.OP_CANCEL and r["claim_token"] == token:
            r["operation_type"] = db_mc.OP_CANCEL_RECONCILE
            r["reconcile_reason"] = reason
            return True
        return False

    async def release_claim(self, appointment_id, token, claimed_at):
        r = self.rows.get(appointment_id)
        if r and r["claim_token"] == token and r["claimed_at"] == claimed_at:
            del self.rows[appointment_id]
            return True
        return False


class Queue:
    """Fake webhook_events honouring migration 023's one-pending-per-appointment."""

    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    async def enqueue(self, event_type, call_id, payload):
        if self.fail:
            raise RuntimeError("db down")
        if any(r["event_type"] == event_type and r["status"] == "pending"
               and r["payload"].get("appointment_id") == payload.get("appointment_id")
               for r in self.rows):
            return False                       # the partial unique index
        self.rows.append({"event_type": event_type, "call_id": call_id,
                          "payload": payload, "status": "pending"})
        return True

    def pending(self, event_type=intent.EVENT_TYPE):
        return [r for r in self.rows if r["event_type"] == event_type and r["status"] == "pending"]


@contextlib.contextmanager
def env(claims, queue, appt=None, provider_outcome="ok", appt_store=None):
    """Wire the fakes in. appt_store lets a test observe status writes."""
    store = appt_store if appt_store is not None else {APPT: dict(appt or APPT_ROW)}
    updates = []

    async def _update(aid, patch):
        updates.append((aid, patch))
        if aid in store:
            store[aid] = {**store[aid], **patch}

    async def _get(aid):
        r = store.get(aid)
        return dict(r) if r else None

    with patch.multiple("db.mutation_claims",
                        get_claim=AsyncMock(side_effect=claims.get_claim),
                        acquire_cancel_claim=AsyncMock(side_effect=claims.acquire_cancel_claim),
                        transition_cancel_to_reconcile=AsyncMock(
                            side_effect=claims.transition_cancel_to_reconcile),
                        release_claim=AsyncMock(side_effect=claims.release_claim)), \
         patch("db.supabase.enqueue_webhook_event", new=AsyncMock(side_effect=queue.enqueue)), \
         patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=_get)), \
         patch("db.supabase.update_appointment", new=AsyncMock(side_effect=_update)), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=dict(TENANT))), \
         patch("services.appointment_cancellation.cancel_at_provider",
               new=AsyncMock(return_value=provider_outcome)) as prov:
        yield {"updates": updates, "store": store, "provider": prov}


async def run_refund(claims, queue, **kw):
    from routers import payments
    with env(claims, queue, **kw) as e, \
         patch("routers.payments.db.update_payment", new=AsyncMock()), \
         patch("routers.payments.db.get_appointment_by_id",
               new=AsyncMock(return_value=dict(APPT_ROW))), \
         patch("routers.payments.db.update_appointment",
               new=AsyncMock(side_effect=lambda a, p: e["updates"].append((a, p)))), \
         patch("routers.payments._notify_refund", new=AsyncMock()), \
         patch("routers.payments._sms_caller_refund", new=AsyncMock()), \
         patch("routers.payments._emit_zapier_deposit", new=AsyncMock()):
        await payments._process_refund(dict(PAYMENT), dict(TENANT))
        return e


# ── 11. THE COUNTEREXAMPLE, END TO END ───────────────────────────────────────

@pytest.mark.asyncio
async def test_SYNTHETIC_reschedule_then_refund_intent_survives_create_failed():
    """The exact sequence that caused migration 023.

    A reschedule owns X; a refund arrives and cannot act; the reschedule ends in
    create_failed and releases, leaving X ACTIVE; the queued intent later acquires
    ownership and cancels it exactly once.
    """
    claims, queue = Claims(), Queue()
    claims.seed(APPT, db_mc.OP_RESCHEDULE)                       # 1

    e = await run_refund(claims, queue)                          # 2, 3
    assert e["provider"].await_count == 0, "4. no provider cancellation while owned"  # 4
    assert len(queue.pending()) == 1, "5. exactly one intent queued"                  # 5
    assert e["updates"] == [], "the appointment must not be touched"

    del claims.rows[APPT]                                        # 6. reschedule create_failed -> released

    with env(claims, queue) as e2:                               # 7
        await intent.handle(queue.pending()[0]["payload"])
    assert e2["provider"].await_count == 1, "9. cancelled exactly once"               # 8, 9
    assert e2["updates"] == [(APPT, {"status": "cancelled"})], "10. locally cancelled"  # 10
    assert APPT not in claims.rows, "ownership released"
    queue.rows[0]["status"] = "done"                                                  # 11
    assert queue.pending() == []


# ── 12A, 12B. resurrection ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("start,expect_confirm", [
    ("confirmed", True), ("pending_payment", True), ("cancelled", False)])
async def test_a_payment_webhook_cannot_resurrect_a_cancelled_appointment(start, expect_confirm):
    """The write is conditional on status != 'cancelled'. A delayed deposit
    webhook must not revive an appointment whose booking is already gone."""
    import db.supabase as dbs
    captured = {}

    class _Q:
        def __init__(self): self.f = {}
        def update(self, patch): captured["patch"] = patch; return self
        def eq(self, k, v): self.f[k] = v; return self
        def neq(self, k, v): captured["neq"] = (k, v); self.f["_neq"] = (k, v); return self
        def execute(self):
            blocked = self.f.get("_neq") == ("status", "cancelled") and start == "cancelled"
            return type("R", (), {"data": [] if blocked else [{"id": APPT}]})()

    with patch("db.supabase.get_client", return_value=type("C", (), {"table": lambda s, t: _Q()})()):
        ok = await dbs.confirm_appointment_unless_cancelled(APPT)
    assert ok is expect_confirm
    assert captured["neq"] == ("status", "cancelled"), "the guard must be in the predicate"
    assert captured["patch"] == {"status": "confirmed"}


def test_both_confirmation_sites_use_the_guarded_helper():
    import ast
    import inspect
    from routers import payments
    for fn in (payments._handle_checkout_completed, payments._handle_square_payment_completed):
        code = ast.unparse(ast.parse(inspect.getsource(fn).lstrip()))
        assert "confirm_appointment_unless_cancelled" in code, fn.__name__
        assert "update_appointment" not in code, f"{fn.__name__} must not write status directly"


# ── 8. BUSY behaviour BY OWNER TYPE ──────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("owner,should_enqueue", [
    (db_mc.OP_RESCHEDULE, True),         # may end create_failed -> source stays live
    (db_mc.OP_CANCEL, False),            # already durably heading for cancellation
    (db_mc.OP_CANCEL_RECONCILE, False),  # ditto, owned by reconciliation
])
async def test_busy_behaviour_depends_on_who_owns_the_appointment(owner, should_enqueue):
    """Not all BUSY claims are equal, and generalising them would either lose the
    refund's intent or queue redundant work."""
    claims, queue = Claims(), Queue()
    claims.seed(APPT, owner, reason=(db_mc.REASON_PROVIDER_UNKNOWN
                                     if owner == db_mc.OP_CANCEL_RECONCILE else None))
    e = await run_refund(claims, queue)
    assert e["provider"].await_count == 0, "never mutate under another owner"
    assert (len(queue.pending()) == 1) is should_enqueue


# ── 6. direct refund outcomes ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refund_with_ownership_cancels_and_releases():
    claims, queue = Claims(), Queue()
    e = await run_refund(claims, queue, provider_outcome=cancel_svc.OK)
    assert e["provider"].await_count == 1
    assert (APPT, {"status": "cancelled"}) in e["updates"]
    assert APPT not in claims.rows
    assert queue.pending() == [], "nothing to queue — the work is done"


@pytest.mark.asyncio
async def test_a_definitive_refusal_releases_ownership_and_queues_a_retry():
    """Unlike an interactive caller, a refund is a standing business requirement:
    the durable queue keeps trying rather than the intent being dropped."""
    claims, queue = Claims(), Queue()
    e = await run_refund(claims, queue, provider_outcome=cancel_svc.FAILED)
    assert APPT not in claims.rows, "released — nothing to reconcile"
    assert e["updates"] == [], "status untouched; the booking is still live"
    assert len(queue.pending()) == 1


@pytest.mark.asyncio
async def test_an_unknown_outcome_keeps_ownership_and_queues_nothing():
    """C3 reconciliation now owns convergence. A queued event would fight it."""
    claims, queue = Claims(), Queue()
    e = await run_refund(claims, queue, provider_outcome=cancel_svc.UNKNOWN)
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE
    assert claims.rows[APPT]["reconcile_reason"] == db_mc.REASON_PROVIDER_UNKNOWN
    assert e["updates"] == []
    assert queue.pending() == [], "exactly one durable mechanism owns the unresolved state"


@pytest.mark.asyncio
async def test_a_local_write_failure_after_a_confirmed_cancel_keeps_ownership():
    claims, queue = Claims(), Queue()
    from routers import payments
    with env(claims, queue) as e, \
         patch("routers.payments.db.update_payment", new=AsyncMock()), \
         patch("routers.payments.db.get_appointment_by_id",
               new=AsyncMock(return_value=dict(APPT_ROW))), \
         patch("routers.payments.db.update_appointment",
               new=AsyncMock(side_effect=RuntimeError("db down"))), \
         patch("routers.payments._notify_refund", new=AsyncMock()), \
         patch("routers.payments._sms_caller_refund", new=AsyncMock()), \
         patch("routers.payments._emit_zapier_deposit", new=AsyncMock()):
        await payments._process_refund(dict(PAYMENT), dict(TENANT))
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE
    assert claims.rows[APPT]["reconcile_reason"] == db_mc.REASON_LOCAL_WRITE_FAILED
    assert queue.pending() == []


# ── 7. enqueue failure is not a deferral ─────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failed_enqueue_is_reported_distinctly_from_already_queued():
    assert await intent.enqueue(tenant_id=TID, appointment_id=APPT,
                                provider_booking_id=BOOKING) is not None
    q = Queue()
    with patch("db.supabase.enqueue_webhook_event", new=AsyncMock(side_effect=q.enqueue)):
        assert await intent.enqueue(tenant_id=TID, appointment_id=APPT,
                                    provider_booking_id=BOOKING) == intent.ENQUEUED
        assert await intent.enqueue(tenant_id=TID, appointment_id=APPT,
                                    provider_booking_id=BOOKING) == intent.ALREADY_PENDING
    bad = Queue(fail=True)
    with patch("db.supabase.enqueue_webhook_event", new=AsyncMock(side_effect=bad.enqueue)):
        assert await intent.enqueue(tenant_id=TID, appointment_id=APPT,
                                    provider_booking_id=BOOKING) == intent.ENQUEUE_FAILED


@pytest.mark.asyncio
async def test_a_failed_enqueue_never_triggers_an_unsafe_provider_mutation():
    claims, queue = Claims(), Queue(fail=True)
    claims.seed(APPT, db_mc.OP_RESCHEDULE)
    e = await run_refund(claims, queue)
    assert e["provider"].await_count == 0
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_RESCHEDULE, "owner untouched"


# ── 8/13. the handler ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_missing_appointment_converges_before_taking_ownership():
    claims, queue = Claims(), Queue()
    with env(claims, queue, appt_store={}) as e:
        await intent.handle({"appointment_id": APPT})
    assert claims.rows == {}, "ownership never acquired"
    assert e["provider"].await_count == 0


@pytest.mark.asyncio
async def test_an_already_cancelled_appointment_converges_before_ownership():
    claims, queue = Claims(), Queue()
    with env(claims, queue, appt={**APPT_ROW, "status": "cancelled"}) as e:
        await intent.handle({"appointment_id": APPT})
    assert claims.rows == {}
    assert e["provider"].await_count == 0


@pytest.mark.asyncio
async def test_a_busy_claim_makes_the_event_RETRY_rather_than_complete():
    """Marking it done here is exactly how the intent would be lost a second time."""
    claims, queue = Claims(), Queue()
    claims.seed(APPT, db_mc.OP_RESCHEDULE)
    with env(claims, queue) as e:
        with pytest.raises(RuntimeError):
            await intent.handle({"appointment_id": APPT})
    assert e["provider"].await_count == 0


@pytest.mark.asyncio
async def test_a_definitive_refusal_in_the_handler_releases_and_retries():
    claims, queue = Claims(), Queue()
    with env(claims, queue, provider_outcome=cancel_svc.FAILED) as e:
        with pytest.raises(RuntimeError):
            await intent.handle({"appointment_id": APPT})
    assert APPT not in claims.rows, "released so a later retry can own it"


@pytest.mark.asyncio
async def test_an_unknown_outcome_in_the_handler_completes_and_hands_to_reconciliation():
    claims, queue = Claims(), Queue()
    with env(claims, queue, provider_outcome=cancel_svc.UNKNOWN) as e:
        await intent.handle({"appointment_id": APPT})          # no raise -> event done
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE


@pytest.mark.asyncio
async def test_a_malformed_payload_raises_into_the_queue_policy():
    with pytest.raises(ValueError):
        await intent.handle({})


# ── 9. duplicates converge without the index ─────────────────────────────────

@pytest.mark.asyncio
async def test_two_duplicate_intents_cancel_at_most_once():
    """Correctness comes from ownership plus terminal convergence, not from the
    unique index — so this test bypasses the index entirely."""
    claims, queue = Claims(), Queue()
    store = {APPT: dict(APPT_ROW)}
    with env(claims, queue, appt_store=store) as e1:
        await intent.handle({"appointment_id": APPT})
    with env(claims, queue, appt_store=store) as e2:
        await intent.handle({"appointment_id": APPT})
    assert e1["provider"].await_count == 1
    assert e2["provider"].await_count == 0, "the second converges on the cancelled state"
    assert store[APPT]["status"] == "cancelled"


# ── 14. the Vapi path is untouched ───────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["end-of-call-report", ""])
async def test_end_of_call_events_still_reach_process_end_of_call(event_type):
    from services import webhook_processor as wp
    with patch("services.webhook_processor.process_end_of_call", new=AsyncMock()) as eoc:
        await wp._dispatch({"event_type": event_type, "payload": {"x": 1}})
    eoc.assert_awaited_once_with({"x": 1})


@pytest.mark.asyncio
async def test_a_cancellation_intent_never_enters_the_vapi_handler():
    from services import webhook_processor as wp
    with patch("services.webhook_processor.process_end_of_call", new=AsyncMock()) as eoc, \
         patch("services.appointment_cancel_intent.handle", new=AsyncMock()) as h:
        await wp._dispatch({"event_type": intent.EVENT_TYPE, "payload": {"appointment_id": APPT}})
    eoc.assert_not_awaited()
    h.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unknown_event_type_fails_visibly_rather_than_silently():
    from services import webhook_processor as wp
    with patch("services.webhook_processor.process_end_of_call", new=AsyncMock()) as eoc:
        with pytest.raises(ValueError):
            await wp._dispatch({"event_type": "something.new", "payload": {}})
    eoc.assert_not_awaited()


def test_retry_and_dedupe_behaviour_is_unchanged():
    import inspect
    from services import webhook_processor as wp
    src = inspect.getsource(wp._process_one)
    assert "mark_webhook_retry" in src and "mark_webhook_failed" in src
    assert "MAX_ATTEMPTS" in src
    assert wp._RETRY_DELAYS == [30, 60, 120]
