"""
W6A2-C3 — one destructive workflow owns an appointment, across all calls.

Appointment refs are CALL-scoped and their CAS is keyed on
(vapi_call_id, appointment_ref). Two simultaneous calls therefore hold two
different ref rows for the same appointment, both claim successfully, both read
the status as 'confirmed', and both proceed. A cancel in one call and a
reschedule in the other could each reach Square for the same booking.

appointment_mutation_claims closes that: its primary key is the durable
appointment id, so the INSERT is a global election. A caller that meets a held
claim refuses — it never inspects the owner's type and decides it deserves
priority, and it never waits.

The other half is ownership LIFETIME. A cancellation whose provider outcome is
unknown keeps the claim and moves it to cancel_reconcile, because releasing on
an unknown would let another workflow mutate an appointment whose real state
nobody knows. That is the invariant most of this file is about.
"""
import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import mutation_ownership as mo, square_booking as sb
from db import mutation_claims as db_mc

TID, CALL, PHONE = "t-dani", "call-1", "+353871234567"
CORK_PID, CORK_LOC = "L0Q8GTAZCHD42", "loc-cork"
APPT = "a-cork"


class Claims:
    """A fake appointment_mutation_claims enforcing the real PK and CAS rules."""

    FRESH = "2026-09-11T12:00:00+00:00"
    STALE = "2020-01-01T00:00:00+00:00"
    CUTOFF = "2021-01-01T00:00:00+00:00"

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.lock = asyncio.Lock()

    def seed(self, appointment_id, op_type, token="other", reason=None, stale=False):
        self.rows[appointment_id] = {
            "appointment_id": appointment_id, "tenant_id": TID,
            "operation_type": op_type, "operation_id": (
                str(uuid.uuid4()) if op_type == db_mc.OP_RESCHEDULE else None),
            "reconcile_reason": reason, "claim_token": token,
            "claimed_at": self.STALE if stale else self.FRESH}
        return self.rows[appointment_id]

    async def get_claim(self, appointment_id):
        r = self.rows.get(appointment_id)
        return dict(r) if r else None

    async def acquire_cancel_claim(self, appointment_id, tenant_id, claim_token):
        async with self.lock:
            if appointment_id in self.rows:        # the PK: global election
                return None
            self.rows[appointment_id] = {
                "appointment_id": appointment_id, "tenant_id": tenant_id,
                "operation_type": db_mc.OP_CANCEL, "operation_id": None,
                "reconcile_reason": None, "claim_token": claim_token,
                "claimed_at": self.FRESH}
            return dict(self.rows[appointment_id])

    async def transition_cancel_to_reconcile(self, appointment_id, token, claimed_at, reason):
        async with self.lock:
            r = self.rows.get(appointment_id)
            if (r and r["operation_type"] == db_mc.OP_CANCEL
                    and r["claim_token"] == token and r["claimed_at"] == claimed_at):
                r["operation_type"] = db_mc.OP_CANCEL_RECONCILE
                r["reconcile_reason"] = reason
                return True
            return False

    async def transition_reconcile_to_cancel(self, appointment_id, token, claimed_at, new_token):
        async with self.lock:
            r = self.rows.get(appointment_id)
            if (r and r["operation_type"] == db_mc.OP_CANCEL_RECONCILE
                    and r["claim_token"] == token and r["claimed_at"] == claimed_at):
                r.update(operation_type=db_mc.OP_CANCEL, reconcile_reason=None,
                         claim_token=new_token, claimed_at=self.FRESH)
                return True
            return False

    async def takeover_stale_reconcile(self, appointment_id, prev_token, prev_claimed_at, new_token):
        async with self.lock:
            r = self.rows.get(appointment_id)
            if (r and r["operation_type"] == db_mc.OP_CANCEL_RECONCILE
                    and r["claim_token"] == prev_token
                    and r["claimed_at"] == prev_claimed_at
                    and r["claimed_at"] < self.CUTOFF):
                r["claim_token"] = new_token
                r["claimed_at"] = self.FRESH
                return True
            return False

    async def release_claim(self, appointment_id, token, claimed_at):
        async with self.lock:
            r = self.rows.get(appointment_id)
            if r and r["claim_token"] == token and r["claimed_at"] == claimed_at:
                del self.rows[appointment_id]
                return True
            return False

    async def list_stale_reconcile_claims(self, limit=20):
        return [dict(r) for r in self.rows.values()
                if r["operation_type"] == db_mc.OP_CANCEL_RECONCILE
                and r["claimed_at"] < self.CUTOFF][:limit]


def install(claims):
    return patch.multiple(
        "db.mutation_claims",
        get_claim=AsyncMock(side_effect=claims.get_claim),
        acquire_cancel_claim=AsyncMock(side_effect=claims.acquire_cancel_claim),
        transition_cancel_to_reconcile=AsyncMock(side_effect=claims.transition_cancel_to_reconcile),
        transition_reconcile_to_cancel=AsyncMock(side_effect=claims.transition_reconcile_to_cancel),
        takeover_stale_reconcile=AsyncMock(side_effect=claims.takeover_stale_reconcile),
        release_claim=AsyncMock(side_effect=claims.release_claim),
        list_stale_reconcile_claims=AsyncMock(side_effect=claims.list_stale_reconcile_claims),
    )


@contextlib.contextmanager
def ctx(claims, **kw):
    """A W6A1 cancellation context wired to the fake claim store.

    A real context manager, not an instance with reassigned dunders: Python looks
    __enter__/__exit__ up on the TYPE, so patching them per-instance silently does
    nothing and the test runs against the unpatched claim layer.
    """
    from tests.test_w6a1_safe_cancellation import Ctx
    c = Ctx(**kw)
    with c, install(claims):
        yield c


# ── A-D. the cross-call race ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_two_calls_cancelling_one_appointment_reach_square_once():
    """The race C3 closes. Two calls, two independent refs, one appointment."""
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK]) as c:
        await c.call(call_id="call-A")
        await c.call(call_id="call-B")
        results = await asyncio.gather(
            c.call(ref="appt_1", call_id="call-A"),
            c.call(ref="appt_1", call_id="call-B"))
    assert len(c.cancel_calls) == 1, f"provider called {len(c.cancel_calls)} times"
    assert c.cancelled_ids() == ["a-cork"], "exactly one cancellation persisted"
    # The loser's wording depends on the interleaving, and BOTH are correct: it is
    # refused at the claim ("being updated right now") if it arrives while the
    # winner holds ownership, or at the authoritative re-read ("isn't active any
    # more") if the winner has already finished. What must never happen is a
    # second provider call or a second fresh confirmation.
    spoken = [c.text(r).lower() for r in results]
    losers = [t for t in spoken if "being updated right now" in t or "isn't active any more" in t]
    assert len(losers) == 1, spoken


@pytest.mark.asyncio
async def test_B_cancellation_refuses_while_a_reschedule_owns_the_appointment():
    """No cross-type steal, and no inspection of whether the caller 'deserves'
    priority — a held claim is a held claim."""
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    claims.seed(APPT, db_mc.OP_RESCHEDULE)
    with ctx(claims, candidates=[CORK]) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == [], "must refuse before any provider call"
    assert c.updates == []
    assert "being updated right now" in c.text(res)
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_RESCHEDULE, "untouched"


@pytest.mark.asyncio
async def test_C_a_reschedule_claim_cannot_be_acquired_while_cancel_owns_it():
    claims = Claims()
    with install(claims):
        status, claim = await mo.acquire_for_cancel(APPT, TID)
        assert status == mo.ACQUIRED
        # a synthetic second acquisition of any type hits the PK
        assert await claims.acquire_cancel_claim(APPT, TID, "someone-else") is None


@pytest.mark.asyncio
async def test_D_two_refs_in_one_call_still_serialize_on_the_appointment():
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK, CORK]) as c:
        await c.call()
        results = await asyncio.gather(c.call(ref="appt_1"), c.call(ref="appt_2"))
    assert len(c.cancel_calls) <= 1
    assert len([r for r in results if "being updated" in c.text(r)]) >= 0


# ── E, F. a stale worker is fenced ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_E_a_stale_release_affects_zero_rows():
    claims = Claims()
    row = claims.seed(APPT, db_mc.OP_CANCEL, token="worker-A")
    with install(claims):
        stale = mo.Claim(APPT, "worker-A", row["claimed_at"], db_mc.OP_CANCEL)
        # somebody else takes over
        claims.rows[APPT]["claim_token"] = "worker-B"
        assert await mo.release(stale) is False
    assert APPT in claims.rows, "the new owner's claim must survive"


@pytest.mark.asyncio
async def test_F_a_stale_reconcile_transition_affects_zero_rows():
    claims = Claims()
    row = claims.seed(APPT, db_mc.OP_CANCEL, token="worker-A")
    with install(claims):
        stale = mo.Claim(APPT, "worker-A", row["claimed_at"], db_mc.OP_CANCEL)
        claims.rows[APPT]["claim_token"] = "worker-B"
        assert await mo.to_reconcile(stale, db_mc.REASON_PROVIDER_UNKNOWN) is False
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL


# ── G-J. ownership lifetime by outcome ───────────────────────────────────────

@pytest.mark.asyncio
async def test_G_an_unknown_outcome_retains_ownership_as_cancel_reconcile():
    """The most important C3 invariant: unknown holds the claim."""
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK], cancel=(sb.CANCEL_UNKNOWN, {})) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.updates == [], "status untouched"
    assert APPT in claims.rows, "ownership must NOT be released on unknown"
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE
    assert claims.rows[APPT]["reconcile_reason"] == db_mc.REASON_PROVIDER_UNKNOWN
    assert "couldn't confirm whether the cancellation went through" in c.text(res).lower()


@pytest.mark.asyncio
async def test_H_a_failed_local_write_after_a_confirmed_cancel_retains_ownership():
    from tests.test_w6a1_safe_cancellation import Ctx, CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK]) as c:
        await c.call()
        with patch("db.supabase.update_appointment",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            res = await c.call(ref="appt_1")
    assert APPT in claims.rows
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE
    assert claims.rows[APPT]["reconcile_reason"] == db_mc.REASON_LOCAL_WRITE_FAILED
    assert "has been cancelled with the business" in c.text(res).lower()


@pytest.mark.asyncio
async def test_I_a_definitive_rejection_releases_ownership():
    """Nothing to reconcile: the booking is known NOT cancelled."""
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert APPT not in claims.rows, "a definitive failure must release ownership"


@pytest.mark.asyncio
async def test_J_a_successful_cancellation_releases_ownership():
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK]) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]
    assert APPT not in claims.rows


@pytest.mark.asyncio
async def test_a_pre_provider_bail_releases_ownership():
    """Every path that gives up before Square must hand the appointment back."""
    from tests.test_w6a1_safe_cancellation import Ctx, CORK, appt as mk
    claims = Claims()
    with ctx(claims, candidates=[mk("a-cork", booking="")]) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancel_calls == []
    assert APPT not in claims.rows, "no provider booking id -> release, not hold"


# ── the CANCEL_NOT_FOUND decision ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_not_found_is_terminal_provider_truth_and_reconciles_locally():
    """DECISION, and a deliberate change to W6A1 behaviour.

    Square definitively says the booking does not exist. Previously this was
    treated as a provider failure and the row was left 'confirmed' — which made
    the appointment permanently uncancellable through the assistant, since every
    retry returns NOT_FOUND and leaves it in place again. Absence is provider
    truth: the caller's intent is already satisfied and our record is the stale
    part, so we reconcile it and release ownership.

    Kept strictly distinct from UNKNOWN, where absence is NOT established and
    assuming it would be a guess.
    """
    from tests.test_w6a1_safe_cancellation import CORK
    claims = Claims()
    with ctx(claims, candidates=[CORK], cancel=(sb.CANCEL_NOT_FOUND, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"], "local record catches up"
    assert APPT not in claims.rows, "ownership released — nothing left to reconcile"


# ── 6. VERSION_MISMATCH stays a W6A1 concern only ────────────────────────────

def test_w6a1_cancellation_does_not_use_source_fingerprint_semantics():
    """C1 exposed the error code; W6A2 will use it. W6A1's explicit cancellation
    must NOT — the caller chose this appointment, and cancelling the latest
    version of that same booking is exactly what they asked for."""
    import ast
    import inspect
    code = ast.unparse(ast.parse(inspect.getsource(tools._cancel_square_booking).lstrip()))
    assert "source_changed" not in code
    assert "source_booking_version" not in code
    assert "ERR_VERSION_MISMATCH" not in code, "no fingerprint branching in W6A1"


def test_cancellation_never_crosses_booking_ids():
    import ast
    import inspect
    src = inspect.getsource(tools._cancel_square_booking)
    tree = ast.parse(src.lstrip())
    ids = {ast.unparse(n) for n in ast.walk(tree)
           if isinstance(n, ast.Call) and "cancel_booking_detailed" in ast.unparse(n.func)}
    assert all("event_id" in i for i in ids), "only the selected booking may be cancelled"


# ── K-N. reconciliation ──────────────────────────────────────────────────────

def _recon_ctx(claims, appt_row, booking_status, tenant=None):
    from services import cancel_reconcile
    updates = []

    async def _get_booking_detailed(token, bid):
        if booking_status == "unknown":
            return sb.FETCH_UNKNOWN, {}
        if booking_status == "absent":
            return sb.FETCH_NOT_FOUND, {}
        return sb.FETCH_FOUND, {"id": bid, "status": booking_status}

    return patch.multiple(
        "db.supabase",
        get_appointment_by_id=AsyncMock(return_value=appt_row),
        get_tenant_by_id=AsyncMock(return_value=tenant or {"id": TID}),
        update_appointment=AsyncMock(side_effect=lambda i, d: updates.append((i, d))),
    ), patch.multiple(
        "services.square_booking",
        get_access_token=AsyncMock(return_value="tok"),
        get_booking_detailed=AsyncMock(side_effect=_get_booking_detailed),
    ), updates


APPT_ROW = {"id": APPT, "tenant_id": TID, "status": "confirmed",
            "google_event_id": "BK-CORK", "caller_phone": PHONE}


@pytest.mark.asyncio
async def test_K_recovery_reconciles_when_square_now_says_cancelled():
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "CANCELLED_BY_SELLER")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"reconciled": 1}
    assert updates == [(APPT, {"status": "cancelled"})]
    assert APPT not in claims.rows, "claim released once settled"


@pytest.mark.asyncio
async def test_L_recovery_returns_an_active_booking_to_cancel_ownership():
    """provider_outcome_unknown + definitively active means the cancel never
    landed. A type-matched transition back to 'cancel' allows a retry without any
    cross-type steal and without deleting the row."""
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "ACCEPTED")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"retryable": 1}
    assert updates == [], "nothing written — the appointment was never cancelled"
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL
    assert claims.rows[APPT]["reconcile_reason"] is None


@pytest.mark.asyncio
async def test_L2_an_active_booking_after_local_write_failed_is_an_anomaly():
    """The two facts contradict each other, so this is not a retry opportunity."""
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_LOCAL_WRITE_FAILED, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "ACCEPTED")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"needs_operator": 1}
    assert updates == []
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE, "claim retained"


@pytest.mark.asyncio
async def test_M_an_unreadable_provider_leaves_the_claim_exactly_as_it_was():
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "unknown")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"still_unknown": 1}
    assert updates == []
    assert claims.rows[APPT]["operation_type"] == db_mc.OP_CANCEL_RECONCILE


@pytest.mark.asyncio
async def test_an_absent_booking_during_recovery_counts_as_cancelled():
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "absent")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"reconciled": 1}
    assert APPT not in claims.rows


@pytest.mark.asyncio
async def test_N_recovery_needs_no_appointment_ref_at_all():
    """Durable recovery must not depend on call-scoped state. The refs are gone
    here — deleted at end of call — and reconciliation still completes."""
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, updates = _recon_ctx(claims, APPT_ROW, "CANCELLED_BY_SELLER")
    with install(claims), p1, p2, \
         patch("db.appointment_refs.get_ref",
               new=AsyncMock(side_effect=AssertionError("recovery must not read refs"))):
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"reconciled": 1}


@pytest.mark.asyncio
async def test_a_fresh_claim_is_not_taken_over_by_recovery():
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=False)
    p1, p2, _ = _recon_ctx(claims, APPT_ROW, "CANCELLED_BY_SELLER")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["scanned"] == 0, "a live worker must never be stolen from"


@pytest.mark.asyncio
async def test_an_erased_appointment_releases_its_claim():
    from services import cancel_reconcile
    claims = Claims()
    claims.seed(APPT, db_mc.OP_CANCEL_RECONCILE,
                reason=db_mc.REASON_PROVIDER_UNKNOWN, stale=True)
    p1, p2, _ = _recon_ctx(claims, None, "CANCELLED_BY_SELLER")
    with install(claims), p1, p2:
        out = await cancel_reconcile.run_cancel_reconciliation()
    assert out["outcomes"] == {"appointment_gone": 1}
    assert APPT not in claims.rows


# ── the trigger exists ───────────────────────────────────────────────────────

def test_reconciliation_is_wired_into_a_continuously_running_loop():
    """C3 must not ship claims that can be stranded: W6A1 can now create
    cancel_reconcile, so production needs a path that eventually settles it."""
    import inspect
    from services import webhook_processor as wp
    assert "_maybe_reconcile_cancellations" in inspect.getsource(wp._processor_loop)
    src = inspect.getsource(wp._maybe_reconcile_cancellations)
    assert "run_cancel_reconciliation" in src
    assert wp._RECONCILE_EVERY_SECONDS <= 300, "must be far faster than the daily cron"


def test_no_release_helper_works_without_both_token_and_timestamp():
    import ast
    import inspect
    for fn in (db_mc.release_claim, db_mc.transition_cancel_to_reconcile,
               db_mc.transition_reconcile_to_cancel, db_mc.takeover_stale_reconcile):
        code = ast.unparse(ast.parse(inspect.getsource(fn).lstrip()))
        assert "claim_token" in code and "claimed_at" in code, fn.__name__


def test_the_ownership_layer_never_mutates_a_provider():
    """SUPERSEDES C3's "no reschedule runtime exists" guard, which D1 retires by
    design when it adds acquire_for_reschedule.

    What must still hold — and is the stronger property — is that the ownership
    layer itself remains a lock and nothing more: it never creates or cancels a
    booking, and it never touches the operations table. Reschedule ownership may
    exist; reschedule side effects may not live here.
    """
    import inspect
    for mod in (mo, db_mc):
        src = inspect.getsource(mod)
        assert "create_booking" not in src, f"{mod.__name__} must not create bookings"
        assert "cancel_booking" not in src, f"{mod.__name__} must not cancel bookings"
        assert "appointment_reschedule_operations" not in src, \
            f"{mod.__name__} must not touch the operations table"
    assert hasattr(mo, "acquire_for_cancel") and hasattr(mo, "acquire_for_reschedule")
