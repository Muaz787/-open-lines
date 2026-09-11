"""
W6A2-D2 — replacement creation, source cancellation, and durable recovery.

D1 froze an operation and touched nothing. D2 is the part that mutates the
provider twice, in an order chosen so that a failure never leaves the caller with
no appointment: create the replacement first, cancel the source second.

WHAT THESE TESTS ARE ACTUALLY DEFENDING
Every crash window between those two mutations is a state somebody has to be able
to recover from without the call that started it. call_slot_offers and
call_appointment_refs are deleted at end of call, so recovery has exactly two
inputs: the frozen operation row, and provider truth. The matrix below (A-U) is
one test per window.

The two properties that matter most, and are easiest to lose in a refactor:

  * A replay is the SAME request. The CreateBooking body is built only from
    frozen columns, so the frozen idempotency key still means something. Test
    18 destroys every live input and proves the second request is byte-identical
    to the first.

  * A merchant's edit is never overwritten. Once the source fingerprint stops
    matching, NO recovery pass may cancel it, in this process or any later one.
"""
import asyncio
import contextlib
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from db import mutation_claims as db_mc, reschedule_ops as db_ops
from services import reschedule_execute as rx, square_booking as sb

TID, CALL, PHONE = "t-dani", "call-1", "+353871234567"
SRC, OP = "appt-src", "op-1"
CORK_LOC, CORK_PID = "loc-cork", "L0Q8GTAZCHD42"
SRC_BOOKING, NEW_BOOKING = "BK-SRC", "BK-NEW"
VAR, TM, CUST = "VAR-CONSULT", "TM-AOIFE", "SQCUST-1"
KEY = "11111111-2222-3333-4444-555555555555"
TOKEN0 = "tok-claim-0"
AT0 = "2026-09-11T12:00:00+00:00"

SOURCE = {"id": SRC, "tenant_id": TID, "caller_phone": PHONE, "caller_name": "Aoife",
          "service": "Consultation", "appointment_datetime": "2026-11-01T13:00:00+00:00",
          "duration_minutes": 60, "status": "confirmed", "google_event_id": SRC_BOOKING,
          "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
          "vapi_call_id": "call-0", "rescheduled_from_appointment_id": None}

OPERATION = {
    "id": OP, "tenant_id": TID, "source_appointment_id": SRC,
    "replacement_appointment_id": None,
    "target_tenant_location_id": CORK_LOC, "target_provider_location_id": CORK_PID,
    "target_provider_customer_id": CUST, "target_service_variation_id": VAR,
    "target_service_variation_version": 1789040442821, "target_team_member_id": TM,
    "target_start_at_utc": "2026-11-08T13:00:00+00:00", "target_duration_minutes": 60,
    "target_service_name": "Consultation (example service) — Regular",
    "provider_idempotency_key": KEY,
    "source_provider_booking_id": SRC_BOOKING, "source_booking_version": 7,
    "source_start_at_utc": "2026-11-01T13:00:00+00:00",
    "cancel_failure_reason": None,
    "claim_token": TOKEN0, "claimed_at": AT0, "state": db_ops.STATE_IN_PROGRESS,
}

SQ_SOURCE = {"id": SRC_BOOKING, "status": "ACCEPTED", "location_id": CORK_PID,
             "version": 7, "start_at": "2026-11-01T13:00:00Z"}


# ---------------------------------------------------------------------------
# Fakes that carry the real constraints
# ---------------------------------------------------------------------------

class Store:
    """Claims, operations, appointments and slots, with the DB's own rules.

    The constraints are reproduced rather than assumed away: the claim table's
    primary key, the operation CAS predicates, and migration 018's unique index
    on rescheduled_from_appointment_id are what the code under test relies on, so
    a fake that let them slide would prove nothing.
    """

    def __init__(self, *, operation=None, source=None, claim_token=TOKEN0):
        op = dict(operation or OPERATION)
        self.ops = {op["id"]: op}
        self.appts = {SRC: dict(source or SOURCE)}
        self.claims = {SRC: {"appointment_id": SRC, "tenant_id": TID,
                             "operation_type": db_mc.OP_RESCHEDULE, "operation_id": op["id"],
                             "reconcile_reason": None, "claim_token": claim_token,
                             "claimed_at": AT0}}
        self.slots = {"slot_1": {"vapi_call_id": CALL, "slot_ref": "slot_1",
                                 "tenant_id": TID, "consumed_at": "claimed",
                                 "booking_id": None}}
        self.refs_consumed: list[str] = []
        self.insert_fails = False
        self.update_fails = False
        self.lock = asyncio.Lock()
        self._seq = 0

    # -- claims -------------------------------------------------------------
    async def get_claim(self, aid):
        r = self.claims.get(aid)
        return dict(r) if r else None

    async def release_claim(self, aid, token, claimed_at):
        r = self.claims.get(aid)
        if r and r["claim_token"] == token and r["claimed_at"] == claimed_at:
            del self.claims[aid]
            return True
        return False

    async def acquire_cancel_claim(self, aid, tid, token):
        async with self.lock:
            if aid in self.claims:
                return None                      # the primary key IS the election
            self.claims[aid] = {"appointment_id": aid, "tenant_id": tid,
                                "operation_type": db_mc.OP_CANCEL, "operation_id": None,
                                "reconcile_reason": None, "claim_token": token,
                                "claimed_at": self._now()}
            return dict(self.claims[aid])

    async def takeover(self, aid, op_id, prev_token, prev_at, new_token):
        async with self.lock:
            r = self.claims.get(aid)
            if not (r and r["operation_type"] == db_mc.OP_RESCHEDULE
                    and str(r["operation_id"]) == str(op_id)
                    and r["claim_token"] == prev_token and r["claimed_at"] == prev_at):
                return False
            r["claim_token"], r["claimed_at"] = new_token, self._now()
            return True

    async def list_stale(self, limit=20):
        return [dict(r) for r in self.claims.values()
                if r["operation_type"] == db_mc.OP_RESCHEDULE][:limit]

    # -- operations ---------------------------------------------------------
    def _now(self):
        self._seq += 1
        return f"2026-09-11T12:{self._seq:02d}:00+00:00"

    async def get_operation(self, op_id):
        r = self.ops.get(op_id)
        return dict(r) if r else None

    async def _transition(self, op_id, token, from_states, patch_):
        async with self.lock:
            r = self.ops.get(op_id)
            if not (r and r["claim_token"] == token and r["state"] in from_states):
                return False
            r.update(patch_)
            r["claimed_at"] = self._now()
            return True

    async def mark_create_failed(self, op_id, token):
        return await self._transition(op_id, token, (db_ops.STATE_IN_PROGRESS,),
                                      {"state": db_ops.STATE_CREATE_FAILED})

    async def mark_replacement_created(self, op_id, token, rid):
        return await self._transition(op_id, token, (db_ops.STATE_IN_PROGRESS,),
                                      {"state": db_ops.STATE_REPLACEMENT_CREATED,
                                       "replacement_appointment_id": rid})

    async def mark_cancel_failed(self, op_id, token, reason):
        return await self._transition(
            op_id, token, (db_ops.STATE_REPLACEMENT_CREATED, db_ops.STATE_CANCEL_FAILED),
            {"state": db_ops.STATE_CANCEL_FAILED, "cancel_failure_reason": reason})

    async def mark_completed(self, op_id, token):
        return await self._transition(
            op_id, token, (db_ops.STATE_REPLACEMENT_CREATED, db_ops.STATE_CANCEL_FAILED),
            {"state": db_ops.STATE_COMPLETED})

    async def set_replacement_booking_id(self, op_id, token, booking_id):
        """Set-once and claim-fenced, exactly like the real UPDATE predicate."""
        async with self.lock:
            r = self.ops.get(op_id)
            if not (r and r["claim_token"] == token):
                return False
            if r.get("replacement_provider_booking_id"):
                return False              # already set -> caller re-reads
            r["replacement_provider_booking_id"] = booking_id
            return True

    async def adopt_claim_token(self, op_id, prev, new):
        async with self.lock:
            r = self.ops.get(op_id)
            if not (r and r["claim_token"] == prev):
                return False
            r["claim_token"], r["claimed_at"] = new, self._now()
            return True

    # -- appointments (migration 018's unique lineage) ----------------------
    async def get_appointment(self, aid):
        r = self.appts.get(aid)
        return dict(r) if r else None

    async def by_lineage(self, src):
        for r in self.appts.values():
            if r.get("rescheduled_from_appointment_id") == src:
                return dict(r)
        return None

    async def insert_appointment(self, row):
        async with self.lock:
            if self.insert_fails:
                raise RuntimeError("insert exploded")
            src = row.get("rescheduled_from_appointment_id")
            if src and any(r.get("rescheduled_from_appointment_id") == src
                           for r in self.appts.values()):
                raise RuntimeError('duplicate key value violates unique constraint '
                                   '"appointments_rescheduled_from_unique" (23505)')
            new = {**row, "id": f"appt-new-{len(self.appts)}"}
            self.appts[new["id"]] = new
            return dict(new)

    async def update_appointment(self, aid, patch_):
        if self.update_fails:
            raise RuntimeError("update exploded")
        if aid in self.appts:
            self.appts[aid].update(patch_)
        return dict(self.appts.get(aid) or {})

    # -- slots / refs -------------------------------------------------------
    async def consume_slot(self, call_id, slot_ref, booking_id):
        r = self.slots.get(slot_ref)
        if r and r["booking_id"] is None:
            r["consumed_at"], r["booking_id"] = "consumed", booking_id
        return dict(r or {})

    async def release_slot(self, call_id, slot_ref):
        r = self.slots.get(slot_ref)
        if r and r["booking_id"] is None:
            r["consumed_at"] = None

    async def consume_ref(self, call_id, ref):
        self.refs_consumed.append(ref)
        return True


class Wire:
    """Captures the CreateBooking JSON as it goes out, so §18 is a claim about
    the request on the wire rather than about Python keyword arguments."""

    def __init__(self, statuses=(200,), booking=None):
        self.bodies: list[dict] = []
        self.raw: list[str] = []
        self.statuses = list(statuses)
        self.booking = booking or {"id": NEW_BOOKING, "status": "ACCEPTED",
                                   "version": 0, "location_id": CORK_PID}

    def _next_status(self):
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def patch(self):
        outer = self

        class _Resp:
            def __init__(self, status, payload):
                self.status_code = status
                self.is_success = 200 <= status < 300
                self._p, self.text = payload, "square error body"

            def json(self):
                return self._p

            def raise_for_status(self):
                raise RuntimeError(f"HTTP {self.status_code}")

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kw):
                body = kw["json"]
                outer.bodies.append(body)
                outer.raw.append(json.dumps(body))
                status = outer._next_status()
                if status == 0:
                    raise ConnectionError("connection dropped")
                return _Resp(status, {"booking": outer.booking})

        return patch("services.square_booking.httpx.AsyncClient", _C)


@contextlib.contextmanager
def env(store, *, wire=None, fetch=sb.FETCH_FOUND, sq_source=SQ_SOURCE,
        cancel=(sb.CANCEL_OK, {}, "")):
    """Wires the fakes in. CreateBooking runs for real against `wire`; the C1
    read/cancel helpers are patched, since their taxonomy is C1's to prove."""
    wire = wire or Wire()
    cancel_mock = AsyncMock(return_value=cancel) if not isinstance(cancel, AsyncMock) else cancel
    fetch_mock = AsyncMock(return_value=(fetch, dict(sq_source) if sq_source else {})) \
        if not isinstance(fetch, AsyncMock) else fetch

    with wire.patch(), \
         patch.multiple("db.mutation_claims",
                        get_claim=AsyncMock(side_effect=store.get_claim),
                        release_claim=AsyncMock(side_effect=store.release_claim),
                        acquire_cancel_claim=AsyncMock(side_effect=store.acquire_cancel_claim),
                        takeover_stale_reschedule=AsyncMock(side_effect=store.takeover),
                        list_stale_reschedule_claims=AsyncMock(side_effect=store.list_stale)), \
         patch.multiple("db.reschedule_ops",
                        get_operation=AsyncMock(side_effect=store.get_operation),
                        mark_create_failed=AsyncMock(side_effect=store.mark_create_failed),
                        mark_replacement_created=AsyncMock(side_effect=store.mark_replacement_created),
                        mark_cancel_failed=AsyncMock(side_effect=store.mark_cancel_failed),
                        mark_completed=AsyncMock(side_effect=store.mark_completed),
                        adopt_claim_token=AsyncMock(side_effect=store.adopt_claim_token),
                        set_replacement_booking_id=AsyncMock(
                            side_effect=store.set_replacement_booking_id)), \
         patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=store.get_appointment)), \
         patch("db.supabase.get_appointment_by_rescheduled_from", new=AsyncMock(side_effect=store.by_lineage)), \
         patch("db.supabase.insert_appointment", new=AsyncMock(side_effect=store.insert_appointment)), \
         patch("db.supabase.update_appointment", new=AsyncMock(side_effect=store.update_appointment)), \
         patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value={"id": TID})), \
         patch("db.locations.consume_slot_offer", new=AsyncMock(side_effect=store.consume_slot)), \
         patch("db.locations.release_slot_offer", new=AsyncMock(side_effect=store.release_slot)), \
         patch("db.appointment_refs.consume_ref", new=AsyncMock(side_effect=store.consume_ref)), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.get_booking_detailed", new=fetch_mock), \
         patch("services.square_booking.cancel_booking_detailed", new=cancel_mock):
        yield {"wire": wire, "cancel": cancel_mock, "fetch": fetch_mock}


async def run(store, token=TOKEN0, **kw):
    return await rx.run_operation(OP, token, vapi_call_id=kw.pop("call", CALL),
                                  slot_ref=kw.pop("slot", "slot_1"),
                                  appointment_ref=kw.pop("ref", "appt_1"))


# ═══════════════════════════════════════════════════════════════════════════
# §3 — the frozen body, and the functions that must never be touched
# ═══════════════════════════════════════════════════════════════════════════

def test_3a_every_createbooking_argument_comes_from_a_frozen_column():
    kwargs = rx.create_booking_kwargs(OPERATION)
    assert kwargs["location_id"] == OPERATION["target_provider_location_id"]
    assert kwargs["customer_id"] == OPERATION["target_provider_customer_id"]
    assert kwargs["team_member_id"] == OPERATION["target_team_member_id"]
    assert kwargs["service_variation_id"] == OPERATION["target_service_variation_id"]
    assert kwargs["service_variation_version"] == OPERATION["target_service_variation_version"]
    assert kwargs["start_at_iso"] == str(OPERATION["target_start_at_utc"])
    assert kwargs["duration_minutes"] == OPERATION["target_duration_minutes"]
    assert kwargs["idempotency_key"] == OPERATION["provider_idempotency_key"]
    # the note is a pure function of one frozen column
    assert OPERATION["target_service_name"] in kwargs["note"]


def test_3b_the_note_is_derived_only_from_the_frozen_service_name():
    assert rx.booking_note({"target_service_name": "  Fitting  "}).endswith("— Fitting")
    bare = rx.booking_note({})
    assert "—" not in bare and bare == rx.booking_note({"target_service_name": ""})


@pytest.mark.asyncio
async def test_3c_live_resolution_helpers_raise_if_the_create_path_touches_them():
    store = Store()
    boom = AsyncMock(side_effect=AssertionError("D2 must not re-resolve live state"))
    with env(store) as e, \
         patch("services.square_booking.resolve_slot", new=boom), \
         patch("services.square_booking.resolve_customer", new=boom), \
         patch("services.square_booking.search_availability", new=boom), \
         patch("services.square_booking.available_slots", new=boom), \
         patch("services.square_booking.list_services", new=boom):
        assert await run(store) == rx.COMPLETED
    assert len(e["wire"].bodies) == 1


# ═══════════════════════════════════════════════════════════════════════════
# §17 — the crash-window matrix
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A_no_provider_call_without_a_persisted_operation():
    """A: the operation must exist before CreateBooking can happen at all."""
    store = Store()
    store.ops.clear()
    with env(store) as e:
        assert await run(store) == rx.FENCED
    assert e["wire"].bodies == []


@pytest.mark.asyncio
async def test_A2_a_claim_naming_another_operation_blocks_the_create():
    store = Store()
    store.claims[SRC]["operation_id"] = "some-other-op"
    with env(store) as e:
        assert await run(store) == rx.FENCED
    assert e["wire"].bodies == []


@pytest.mark.asyncio
async def test_A3_a_cancel_claim_may_never_drive_a_reschedule_create():
    store = Store()
    store.claims[SRC]["operation_type"] = db_mc.OP_CANCEL
    with env(store) as e:
        assert await run(store) == rx.FENCED
    assert e["wire"].bodies == []


@pytest.mark.asyncio
async def test_B_definitive_create_failure_leaves_the_source_alone():
    """B: Square refused, so nothing exists and the caller keeps what they had."""
    store = Store()
    with env(store, wire=Wire(statuses=(400,))) as e:
        assert await run(store) == rx.CREATE_FAILED
    assert store.ops[OP]["state"] == db_ops.STATE_CREATE_FAILED
    assert store.appts[SRC]["status"] == "confirmed"          # untouched
    assert await store.by_lineage(SRC) is None                # no replacement
    assert SRC not in store.claims                            # ownership released
    assert store.slots["slot_1"]["consumed_at"] is None       # slot given back
    assert e["cancel"].await_count == 0


@pytest.mark.asyncio
async def test_C_unknown_create_outcome_stays_in_progress_and_holds_everything():
    """C: may or may not exist. Nothing is released, nothing is re-keyed."""
    store = Store()
    with env(store, wire=Wire(statuses=(500,))) as e:
        assert await run(store) == rx.CREATE_UNKNOWN
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS
    assert store.claims[SRC]["claim_token"] == TOKEN0         # ownership held
    assert store.slots["slot_1"]["consumed_at"] == "claimed"  # slot NOT released
    assert store.appts[SRC]["status"] == "confirmed"
    assert e["cancel"].await_count == 0


@pytest.mark.asyncio
async def test_C2_a_dropped_connection_is_unknown_not_failure():
    store = Store()
    with env(store, wire=Wire(statuses=(0,))):
        assert await run(store) == rx.CREATE_UNKNOWN
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS


@pytest.mark.asyncio
async def test_C3_a_429_is_unknown_not_a_definitive_rejection():
    """Square rate-limits at the edge, but never promises nothing was created."""
    store = Store()
    with env(store, wire=Wire(statuses=(429,))):
        assert await run(store) == rx.CREATE_UNKNOWN
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS
    assert store.slots["slot_1"]["consumed_at"] == "claimed"


@pytest.mark.asyncio
async def test_D_response_lost_then_replay_uses_the_same_key_and_converges():
    """D: the request reached Square; the answer did not. Replay is the SAME request."""
    store = Store()
    wire = Wire(statuses=(500, 200))
    with env(store, wire=wire):
        assert await run(store) == rx.CREATE_UNKNOWN
        assert await run(store) == rx.COMPLETED
    assert len(wire.bodies) == 2
    assert wire.bodies[0]["idempotency_key"] == wire.bodies[1]["idempotency_key"] == KEY
    assert wire.raw[0] == wire.raw[1]
    assert len([a for a in store.appts.values()
                if a.get("rescheduled_from_appointment_id") == SRC]) == 1


@pytest.mark.asyncio
async def test_E_square_succeeded_but_we_crashed_before_the_insert():
    """E: recovery replays, Square returns the same booking, one row is written."""
    store = Store()
    store.insert_fails = True
    with env(store), pytest.raises(RuntimeError):
        await run(store)
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS

    store.insert_fails = False
    wire = Wire()
    with env(store, wire=wire):
        assert await run(store) == rx.COMPLETED
    replacement = await store.by_lineage(SRC)
    assert replacement and replacement["google_event_id"] == NEW_BOOKING
    assert len(wire.bodies) == 1


@pytest.mark.asyncio
async def test_F_insert_succeeded_but_we_crashed_before_the_operation_update():
    """F: the lineage row is the evidence; adopt it, never book a second time."""
    store = Store()
    store.appts["appt-orphan"] = {"id": "appt-orphan", "tenant_id": TID,
                                  "caller_phone": PHONE, "status": "confirmed",
                                  "google_event_id": NEW_BOOKING,
                                  "rescheduled_from_appointment_id": SRC}
    wire = Wire()
    with env(store, wire=wire):
        assert await run(store) == rx.COMPLETED
    assert wire.bodies == []                                  # no provider create at all
    assert store.ops[OP]["replacement_appointment_id"] == "appt-orphan"
    assert store.ops[OP]["state"] == db_ops.STATE_COMPLETED


@pytest.mark.asyncio
async def test_G_duplicate_recovery_produces_exactly_one_replacement():
    store = Store()
    wire = Wire()
    with env(store, wire=wire):
        first = await run(store)
        second = await run(store)
    assert first == rx.COMPLETED
    lineage = [a for a in store.appts.values()
               if a.get("rescheduled_from_appointment_id") == SRC]
    assert len(lineage) == 1
    assert second in (rx.COMPLETED, rx.FENCED)


@pytest.mark.asyncio
async def test_G2_concurrent_workers_produce_exactly_one_replacement():
    store = Store()
    wire = Wire()
    with env(store, wire=wire):
        await asyncio.gather(run(store), run(store), return_exceptions=True)
    lineage = [a for a in store.appts.values()
               if a.get("rescheduled_from_appointment_id") == SRC]
    assert len(lineage) == 1


@pytest.mark.asyncio
async def test_H_once_replacement_created_createbooking_never_runs_again():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED,
                             "replacement_appointment_id": "appt-new-1"})
    wire = Wire()
    with env(store, wire=wire):
        assert await run(store) == rx.COMPLETED
    assert wire.bodies == []


@pytest.mark.asyncio
async def test_I_the_slot_is_permanently_consumed_once_a_replacement_exists():
    """I: even when the source cancellation then fails, the slot is never released."""
    store = Store()
    with env(store, cancel=(sb.CANCEL_FAILED, {}, "SOME_OTHER_CODE")):
        assert await run(store) == rx.CANCEL_RETRYABLE
    assert store.slots["slot_1"]["consumed_at"] == "consumed"
    assert store.slots["slot_1"]["booking_id"] == NEW_BOOKING
    assert store.ops[OP]["state"] == db_ops.STATE_CANCEL_FAILED
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_RETRYABLE
    assert SRC in store.claims                                # ownership HELD


@pytest.mark.asyncio
async def test_J_a_changed_source_fingerprint_stops_the_cancellation_dead():
    """J: the merchant moved the booking. We never cancel their edit."""
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    moved = {**SQ_SOURCE, "version": 9, "start_at": "2026-11-02T09:00:00Z"}
    with env(store, sq_source=moved) as e:
        assert await run(store) == rx.SOURCE_CHANGED
    assert e["cancel"].await_count == 0                       # zero destructive calls
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_SOURCE_CHANGED
    assert store.appts[SRC]["status"] == "confirmed"          # source remains active
    assert SRC in store.claims                                # ownership HELD


@pytest.mark.asyncio
async def test_J2_a_start_time_change_alone_is_enough_to_refuse():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, sq_source={**SQ_SOURCE, "start_at": "2026-11-01T15:00:00Z"}) as e:
        assert await run(store) == rx.SOURCE_CHANGED
    assert e["cancel"].await_count == 0


def test_J3_an_equal_instant_written_differently_is_not_a_change():
    """'Z' and '+00:00' are the same moment; a string compare would refuse forever."""
    ok, why = rx.fingerprint_matches(OPERATION, SQ_SOURCE, SOURCE)
    assert ok, why
    assert SQ_SOURCE["start_at"].endswith("Z")
    assert OPERATION["source_start_at_utc"].endswith("+00:00")


@pytest.mark.asyncio
async def test_K_version_mismatch_at_cancel_is_a_merchant_edit():
    """K: lost the race between the fingerprint read and the cancel. Do not retry."""
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, cancel=(sb.CANCEL_FAILED, {}, sb.ERR_VERSION_MISMATCH)):
        assert await run(store) == rx.SOURCE_CHANGED
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_SOURCE_CHANGED
    assert store.appts[SRC]["status"] == "confirmed"
    assert SRC in store.claims


@pytest.mark.asyncio
async def test_L_other_definitive_cancel_failures_are_retryable():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, cancel=(sb.CANCEL_FAILED, {}, "INTERNAL_SERVER_ERROR")):
        assert await run(store) == rx.CANCEL_RETRYABLE
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_RETRYABLE
    assert SRC in store.claims


@pytest.mark.asyncio
async def test_M_an_unknown_cancel_outcome_holds_ownership():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, cancel=(sb.CANCEL_UNKNOWN, {}, "")):
        assert await run(store) == rx.CANCEL_UNKNOWN
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_UNKNOWN
    assert store.appts[SRC]["status"] == "confirmed"
    assert SRC in store.claims


@pytest.mark.asyncio
async def test_N_provider_cancelled_but_the_local_write_failed():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    store.update_fails = True
    with env(store, cancel=(sb.CANCEL_OK, {}, "")):
        assert await run(store) == rx.CANCEL_UNKNOWN
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_UNKNOWN
    assert SRC in store.claims                                # held for reconciliation


@pytest.mark.asyncio
async def test_O_a_source_already_cancelled_at_the_provider_reconciles_and_completes():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, sq_source={**SQ_SOURCE, "status": "CANCELLED_BY_SELLER"}) as e:
        assert await run(store) == rx.COMPLETED
    assert e["cancel"].await_count == 0                       # nothing left to cancel
    assert store.appts[SRC]["status"] == "cancelled"
    assert store.ops[OP]["state"] == db_ops.STATE_COMPLETED
    assert SRC not in store.claims


@pytest.mark.asyncio
async def test_O2_a_source_the_provider_cannot_find_also_completes():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, fetch=sb.FETCH_NOT_FOUND, sq_source=None) as e:
        assert await run(store) == rx.COMPLETED
    assert e["cancel"].await_count == 0
    assert store.appts[SRC]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_O3_an_unreadable_source_is_retryable_and_mutates_nothing():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store, fetch=sb.FETCH_UNKNOWN, sq_source=None) as e:
        assert await run(store) == rx.CANCEL_RETRYABLE
    assert e["cancel"].await_count == 0
    assert store.appts[SRC]["status"] == "confirmed"
    assert SRC in store.claims


@pytest.mark.asyncio
async def test_P_a_completed_operation_with_a_dangling_claim_is_released():
    """P: §12 crash C — the work finished, only the global lock outlived it."""
    store = Store(operation={**OPERATION, "state": db_ops.STATE_COMPLETED})
    with env(store) as e:
        result = await rx.run_reschedule_recovery()
    assert SRC not in store.claims
    assert result["outcomes"].get("terminal_claim_released") == 1
    assert e["wire"].bodies == []


@pytest.mark.asyncio
async def test_P2_a_create_failed_operation_also_releases_its_claim():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_CREATE_FAILED})
    with env(store):
        await rx.run_reschedule_recovery()
    assert SRC not in store.claims


@pytest.mark.asyncio
async def test_Q_source_changed_recovery_makes_zero_destructive_provider_calls():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_CANCEL_FAILED,
                             "cancel_failure_reason": rx.REASON_SOURCE_CHANGED})
    with env(store) as e:
        result = await rx.run_reschedule_recovery()
    assert result["outcomes"].get("awaiting_operator") == 1
    assert e["cancel"].await_count == 0
    assert e["wire"].bodies == []
    assert SRC in store.claims                                # held for a human
    assert store.claims[SRC]["claim_token"] == TOKEN0         # not even touched


@pytest.mark.asyncio
async def test_Q2_source_changed_is_refused_even_when_invoked_directly():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_CANCEL_FAILED,
                             "cancel_failure_reason": rx.REASON_SOURCE_CHANGED})
    with env(store) as e:
        assert await run(store) == rx.SOURCE_CHANGED
    assert e["cancel"].await_count == 0
    assert e["fetch"].await_count == 0


@pytest.mark.asyncio
async def test_R_a_stale_worker_is_fenced_after_a_takeover():
    store = Store()
    store.claims[SRC]["claim_token"] = "tok-new-owner"
    store.ops[OP]["claim_token"] = "tok-new-owner"
    with env(store) as e:
        assert await run(store, token=TOKEN0) == rx.FENCED    # the old worker
    assert e["wire"].bodies == []
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS


@pytest.mark.asyncio
async def test_R2_a_half_finished_takeover_fences_both_halves():
    """The claim moved but the operation did not: neither worker may act."""
    store = Store()
    store.claims[SRC]["claim_token"] = "tok-new-owner"        # operation still TOKEN0
    with env(store) as e:
        assert await run(store, token=TOKEN0) == rx.FENCED
        assert await run(store, token="tok-new-owner") == rx.FENCED
    assert e["wire"].bodies == []


@pytest.mark.asyncio
async def test_R3_recovery_rotates_the_token_and_advances_the_operation():
    store = Store()
    with env(store) as e:
        result = await rx.run_reschedule_recovery()
    assert result["outcomes"].get(rx.COMPLETED) == 1
    assert len(e["wire"].bodies) == 1
    assert SRC not in store.claims                            # completed, released
    assert store.ops[OP]["state"] == db_ops.STATE_COMPLETED
    assert store.ops[OP]["claim_token"] != TOKEN0             # rotated on takeover


@pytest.mark.asyncio
async def test_R4_recovery_leaves_a_claim_with_no_operation_row_to_d1():
    store = Store()
    store.ops.clear()
    with env(store) as e:
        result = await rx.run_reschedule_recovery()
    assert result["outcomes"].get("orphan_left_to_d1") == 1
    assert SRC in store.claims                                # D1's sweeper owns it
    assert e["wire"].bodies == []


# ═══════════════════════════════════════════════════════════════════════════
# §6 — contradictory lineage is an incident, never an overwrite
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_6_a_conflicting_provider_identity_fails_closed():
    """The lineage was taken by a DIFFERENT booking while we were at Square.

    Injected the only way it can really happen: between our pre-check (no
    lineage) and our insert. Overwriting either identity would hide a genuine
    double booking from the merchant, so neither is touched.
    """
    store = Store()
    wire = Wire()

    async def _steal(*a, **kw):
        store.appts["appt-other"] = {
            "id": "appt-other", "tenant_id": TID, "caller_phone": PHONE,
            "status": "confirmed", "google_event_id": "BK-SOMETHING-ELSE",
            "rescheduled_from_appointment_id": SRC}
        return {"id": NEW_BOOKING, "status": "ACCEPTED"}

    with env(store, wire=wire), \
         patch("services.square_booking.create_booking", new=AsyncMock(side_effect=_steal)):
        assert await run(store) == rx.INCIDENT

    assert store.appts["appt-other"]["google_event_id"] == "BK-SOMETHING-ELSE"
    assert store.ops[OP]["state"] == db_ops.STATE_IN_PROGRESS   # not advanced
    assert store.ops[OP]["replacement_appointment_id"] is None
    assert SRC in store.claims                                 # ownership held
    assert store.appts[SRC]["status"] == "confirmed"            # source untouched


@pytest.mark.asyncio
async def test_6b_an_existing_lineage_row_is_adopted_without_asking_square():
    """Only this operation can own this source, so a lineage row that exists IS
    our replacement. Asking Square again is how a caller gets two bookings."""
    store = Store()
    store.appts["appt-ours"] = {"id": "appt-ours", "tenant_id": TID,
                                "caller_phone": PHONE, "status": "confirmed",
                                "google_event_id": NEW_BOOKING,
                                "rescheduled_from_appointment_id": SRC}
    wire = Wire()
    with env(store, wire=wire):
        assert await run(store) == rx.COMPLETED
    assert wire.bodies == []
    assert store.ops[OP]["replacement_appointment_id"] == "appt-ours"


# ═══════════════════════════════════════════════════════════════════════════
# §5 — what the replacement inherits
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_5_the_replacement_inherits_identity_and_carries_the_frozen_target():
    store = Store()
    with env(store):
        assert await run(store) == rx.COMPLETED
    r = await store.by_lineage(SRC)
    # identity/lineage from the source
    assert r["tenant_id"] == TID
    assert r["caller_phone"] == SOURCE["caller_phone"]         # EXACTLY
    assert r["caller_name"] == SOURCE["caller_name"]
    assert r["rescheduled_from_appointment_id"] == SRC
    # target from the frozen operation
    assert r["appointment_datetime"] == OPERATION["target_start_at_utc"]
    assert r["tenant_location_id"] == OPERATION["target_tenant_location_id"]
    assert r["provider_location_id"] == OPERATION["target_provider_location_id"]
    assert r["duration_minutes"] == OPERATION["target_duration_minutes"]
    assert r["google_event_id"] == NEW_BOOKING
    # and the source is NOT mutated into the replacement
    assert store.appts[SRC]["appointment_datetime"] == SOURCE["appointment_datetime"]


@pytest.mark.asyncio
async def test_5b_the_caller_phone_is_identical_so_pipeda_erasure_still_works():
    """delete_caller_data issues ONE set-based DELETE keyed on caller_phone. A
    replacement with a different one would make the source undeletable (23503)."""
    store = Store()
    with env(store):
        await run(store)
    r = await store.by_lineage(SRC)
    assert r["caller_phone"] == store.appts[SRC]["caller_phone"]


@pytest.mark.asyncio
async def test_5c_a_deposit_pending_source_produces_a_deposit_pending_replacement():
    store = Store(source={**SOURCE, "status": "pending_payment"})
    with env(store):
        await run(store)
    assert (await store.by_lineage(SRC))["status"] == "pending_payment"


@pytest.mark.asyncio
async def test_5d_both_appointments_coexist_until_cancellation_is_proven():
    store = Store()
    with env(store, cancel=(sb.CANCEL_UNKNOWN, {}, "")):
        assert await run(store) == rx.CANCEL_UNKNOWN
    assert store.appts[SRC]["status"] == "confirmed"
    assert (await store.by_lineage(SRC)) is not None


# ═══════════════════════════════════════════════════════════════════════════
# §11 — the happy path, end to end
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_11_success_cancels_the_source_completes_and_releases_everything():
    store = Store()
    with env(store) as e:
        assert await run(store) == rx.COMPLETED
    assert store.appts[SRC]["status"] == "cancelled"
    assert store.ops[OP]["state"] == db_ops.STATE_COMPLETED
    assert store.ops[OP]["replacement_appointment_id"]
    assert SRC not in store.claims                            # ownership released
    assert store.refs_consumed == ["appt_1"]                  # ref spent
    assert store.slots["slot_1"]["booking_id"] == NEW_BOOKING  # slot stays consumed
    assert e["cancel"].await_count == 1


@pytest.mark.asyncio
async def test_11b_a_retryable_failure_can_be_retried_from_cancel_failed():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_CANCEL_FAILED,
                             "cancel_failure_reason": rx.REASON_RETRYABLE,
                             "replacement_appointment_id": "appt-new-1"})
    with env(store):
        assert await run(store) == rx.COMPLETED
    assert store.ops[OP]["state"] == db_ops.STATE_COMPLETED
    assert SRC not in store.claims


@pytest.mark.asyncio
async def test_11c_a_retry_that_finds_an_edit_switches_the_reason_to_source_changed():
    store = Store(operation={**OPERATION, "state": db_ops.STATE_CANCEL_FAILED,
                             "cancel_failure_reason": rx.REASON_RETRYABLE,
                             "replacement_appointment_id": "appt-new-1"})
    with env(store, sq_source={**SQ_SOURCE, "version": 11}) as e:
        assert await run(store) == rx.SOURCE_CHANGED
    assert store.ops[OP]["cancel_failure_reason"] == rx.REASON_SOURCE_CHANGED
    assert e["cancel"].await_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# §18 — deterministic replay, proven at the wire
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_18_replay_is_byte_identical_with_every_live_input_destroyed():
    store = Store()
    wire = Wire(statuses=(500, 200))
    with env(store, wire=wire):
        assert await run(store) == rx.CREATE_UNKNOWN

    # Destroy everything live the first attempt could conceivably have used.
    store.slots.clear()
    boom = AsyncMock(side_effect=AssertionError("replay must not touch live state"))
    with env(store, wire=wire), \
         patch("services.square_booking.resolve_slot", new=boom), \
         patch("services.square_booking.resolve_customer", new=boom), \
         patch("services.square_booking.search_availability", new=boom), \
         patch("services.square_booking.list_services", new=boom), \
         patch("services.square_booking.list_team_members", new=boom), \
         patch("services.square_booking.find_or_create_customer", new=boom), \
         patch("services.square_booking.available_slots", new=boom), \
         patch("db.provider_customers.get_mapping", new=boom):
        assert await run(store, call="", slot="") == rx.COMPLETED

    assert len(wire.raw) == 2
    assert wire.raw[0] == wire.raw[1], "the replay body is not byte-identical"
    first, second = wire.bodies
    assert first == second
    for field in ("idempotency_key",):
        assert first[field] == second[field] == KEY
    for field in ("location_id", "start_at", "customer_id", "customer_note"):
        assert first["booking"][field] == second["booking"][field]
    seg_a, seg_b = first["booking"]["appointment_segments"][0], \
        second["booking"]["appointment_segments"][0]
    assert seg_a == seg_b
    assert set(seg_a) == {"team_member_id", "service_variation_id",
                          "service_variation_version", "duration_minutes"}


@pytest.mark.asyncio
async def test_18b_optional_field_omission_is_stable_across_a_replay():
    """A frozen NULL must be omitted both times, not sent as null on one attempt."""
    lean = {**OPERATION, "target_service_variation_version": None,
            "target_duration_minutes": None, "target_service_name": None}
    store = Store(operation=lean)
    wire = Wire(statuses=(500, 200))
    with env(store, wire=wire):
        await run(store)
    with env(store, wire=wire):
        await run(store)
    assert wire.raw[0] == wire.raw[1]
    seg = wire.bodies[0]["booking"]["appointment_segments"][0]
    assert set(seg) == {"team_member_id", "service_variation_id"}
    assert "customer_note" in wire.bodies[0]["booking"]       # the base note survives


# ═══════════════════════════════════════════════════════════════════════════
# §15 — refund interaction (C4 must remain valid)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_S_refund_after_create_failed_eventually_cancels_the_source():
    """S: create_failed releases ownership, so the queued intent can finally act."""
    from services import appointment_cancel_intent as intent

    store = Store()
    with env(store, wire=Wire(statuses=(400,))):
        assert await run(store) == rx.CREATE_FAILED

        # the refund's queued intent now runs, and is no longer blocked
        with patch("services.appointment_cancellation.cancel_at_provider",
                   new=AsyncMock(return_value="ok")):
            await intent.handle({"appointment_id": SRC})

    assert store.appts[SRC]["status"] == "cancelled"
    assert SRC not in store.claims


@pytest.mark.asyncio
async def test_T_refund_after_completion_converges_harmlessly():
    from services import appointment_cancel_intent as intent

    store = Store()
    with env(store):
        assert await run(store) == rx.COMPLETED
        cancel_at = AsyncMock(return_value="ok")
        with patch("services.appointment_cancellation.cancel_at_provider", new=cancel_at):
            await intent.handle({"appointment_id": SRC})
    assert cancel_at.await_count == 0                         # already cancelled; no-op


@pytest.mark.asyncio
async def test_U_refund_cannot_steal_a_held_reschedule_claim():
    from services import appointment_cancel_intent as intent

    store = Store(operation={**OPERATION, "state": db_ops.STATE_CANCEL_FAILED,
                             "cancel_failure_reason": rx.REASON_RETRYABLE})
    with env(store):
        cancel_at = AsyncMock(return_value="ok")
        with patch("services.appointment_cancellation.cancel_at_provider", new=cancel_at):
            with pytest.raises(RuntimeError):                 # raises => queue retries
                await intent.handle({"appointment_id": SRC})
    assert cancel_at.await_count == 0
    assert store.claims[SRC]["operation_type"] == db_mc.OP_RESCHEDULE
    assert store.claims[SRC]["claim_token"] == TOKEN0
    assert store.appts[SRC]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_U2_a_refund_cannot_steal_a_replacement_created_claim_either():
    from services import appointment_cancel_intent as intent

    store = Store(operation={**OPERATION, "state": db_ops.STATE_REPLACEMENT_CREATED})
    with env(store):
        with patch("services.appointment_cancellation.cancel_at_provider",
                   new=AsyncMock(return_value="ok")):
            with pytest.raises(RuntimeError):
                await intent.handle({"appointment_id": SRC})
    assert store.claims[SRC]["operation_id"] == OP


# ═══════════════════════════════════════════════════════════════════════════
# §16 — still internal
# ═══════════════════════════════════════════════════════════════════════════

def test_16_the_tool_surface_is_exactly_the_five_known_tools():
    """D3 added reschedule_appointment. Nothing else may appear alongside it."""
    from services import vapi

    names = {t["function"]["name"]
             for t in vapi.build_calendar_tools("t1", supports_reschedule=True)}
    assert names == {"book_appointment", "caller_lookup", "cancel_appointment",
                     "check_availability", "reschedule_appointment"}


def test_16a_the_request_path_reaches_the_executor_only_through_the_intent_layer():
    """D2's executor is not a tool handler, and must not become one.

    routers/tools.py may reach the lifecycle only via services.reschedule_intent,
    which owns the outcome vocabulary the assistant is allowed to speak. A direct
    call to reschedule_execute from the router would be a second opinion about
    what a caller may be told, and two opinions drift.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("routers/tools.py").read_text())
    modules = {n.module for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) and n.module}
    names = {a.name for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) for a in n.names}
    names |= {a.name for n in ast.walk(tree)
              if isinstance(n, ast.Import) for a in n.names}
    assert "services.reschedule_execute" not in modules
    assert "reschedule_execute" not in names
    assert "reschedule_intent" in names

    called = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not any("reschedule_execute" in c or "run_operation" in c
                   or "begin_reschedule" in c for c in called)


def test_16b_the_recovery_worker_is_actually_scheduled():
    from pathlib import Path
    src = Path("services/webhook_processor.py").read_text()
    assert "run_reschedule_recovery" in src
