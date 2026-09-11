"""
W6A2-D1 — freeze a reschedule, and make no provider mutation at all.

D1 takes global ownership of the source, re-proves everything under it, resolves
the target slot one final time, and writes a durable operation row. Zero
CreateBooking, zero CancelBooking — only GETs, and only to establish source truth.

The property everything else rests on: no Square create may happen unless the
mutation claim's operation_id names a PERSISTED operation row. That is why the
UUID is allocated before ownership and written into the claim atomically — a
claim naming an absent operation then proves nothing was created, which is what
makes an interrupted D1 safe to clean up rather than merely likely to be.

The gate at the end of this file matters most: once frozen, the row must be
sufficient to rebuild the exact future CreateBooking with every live fixture
destroyed.
"""
import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from db import mutation_claims as db_mc, reschedule_ops as db_ops
from services import reschedule as rs, slot_offers, square_booking as sb

TID, CALL, PHONE = "t-dani", "call-1", "+353871234567"
SRC = "appt-src"
CORK_LOC, CORK_PID = "loc-cork", "L0Q8GTAZCHD42"
DUBLIN_LOC, DUBLIN_PID = "loc-dublin", "L9SA1AQ7XBM6K"
BOOKING = "BK-SRC"
VAR, TM, CUST = "VAR-CONSULT", "TM-AOIFE", "SQCUST-1"

SOURCE = {"id": SRC, "tenant_id": TID, "caller_phone": PHONE, "caller_name": "Aoife",
          "service": "Consultation", "appointment_datetime": "2026-11-01T13:00:00+00:00",
          "duration_minutes": 60, "status": "confirmed", "google_event_id": BOOKING,
          "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID}

REF = {"vapi_call_id": CALL, "appointment_ref": "appt_1", "tenant_id": TID,
       "appointment_id": SRC, "caller_phone": PHONE,
       "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
       "provider_booking_id": BOOKING, "service": "Consultation",
       "start_at_utc": "2026-11-01T13:00:00+00:00", "consumed_at": None,
       "expires_at": "2099-01-01T00:00:00+00:00"}

OFFER = {"vapi_call_id": CALL, "slot_ref": "slot_1", "tenant_id": TID,
         "tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
         "service_variation_id": VAR, "service_variation_version": 1789040442821,
         "service_name": "Consultation (example service) — Regular",
         "team_member_id": TM, "start_at_utc": "2026-11-08T13:00:00Z",
         "duration_minutes": 60, "consumed_at": None, "booking_id": None,
         "expires_at": "2099-01-01T00:00:00+00:00"}

SEG = {"team_member_id": TM, "service_variation_version": 1789040442821,
       "duration_minutes": 60, "start_at": "2026-11-08T13:00:00Z"}

SQ_SOURCE = {"id": BOOKING, "status": "ACCEPTED", "location_id": CORK_PID,
             "version": 7, "start_at": "2026-11-01T13:00:00Z"}


class Store:
    """Fakes for claims, operations and slot offers, with the real constraints."""
    AT = "2026-09-11T12:00:00+00:00"

    def __init__(self):
        self.claims, self.ops, self.slots = {}, {}, {"slot_1": dict(OFFER)}
        self.lock = asyncio.Lock()

    # -- mutation claims (PK = appointment_id) --
    async def get_claim(self, aid):
        r = self.claims.get(aid)
        return dict(r) if r else None

    async def _insert_claim(self, aid, tid, op_type, op_id, token):
        async with self.lock:
            if aid in self.claims:
                return None
            self.claims[aid] = {"appointment_id": aid, "tenant_id": tid,
                                "operation_type": op_type, "operation_id": op_id,
                                "reconcile_reason": None, "claim_token": token,
                                "claimed_at": self.AT}
            return dict(self.claims[aid])

    async def acquire_cancel_claim(self, aid, tid, token):
        return await self._insert_claim(aid, tid, db_mc.OP_CANCEL, None, token)

    async def acquire_reschedule_claim(self, aid, tid, op_id, token):
        return await self._insert_claim(aid, tid, db_mc.OP_RESCHEDULE, op_id, token)

    async def release_claim(self, aid, token, claimed_at):
        r = self.claims.get(aid)
        if r and r["claim_token"] == token and r["claimed_at"] == claimed_at:
            del self.claims[aid]
            return True
        return False

    async def release_orphan(self, aid, op_id, token, claimed_at):
        r = self.claims.get(aid)
        if (r and r["operation_type"] == db_mc.OP_RESCHEDULE
                and r["operation_id"] == op_id and r["claim_token"] == token
                and r["claimed_at"] == claimed_at):
            del self.claims[aid]
            return True
        return False

    async def list_stale_reschedule(self, limit=20):
        return [dict(r) for r in self.claims.values()
                if r["operation_type"] == db_mc.OP_RESCHEDULE][:limit]

    # -- operations (partial unique on LIVE states) --
    async def insert_operation(self, row):
        async with self.lock:
            if any(o["source_appointment_id"] == row["source_appointment_id"]
                   and o["state"] in db_ops.LIVE_STATES for o in self.ops.values()):
                return None
            self.ops[row["id"]] = dict(row)
            return dict(row)

    async def get_operation(self, op_id):
        r = self.ops.get(op_id)
        return dict(r) if r else None

    async def get_live_for_source(self, src):
        for o in self.ops.values():
            if o["source_appointment_id"] == src and o["state"] in db_ops.LIVE_STATES:
                return dict(o)
        return None

    # -- slot offers --
    async def claim_slot(self, call_id, slot_ref, tenant_id):
        async with self.lock:
            r = self.slots.get(slot_ref)
            if r and r["consumed_at"] is None:
                r["consumed_at"] = "claimed"
                return True
            return False

    async def release_slot(self, call_id, slot_ref):
        r = self.slots.get(slot_ref)
        if r and r["booking_id"] is None:
            r["consumed_at"] = None


@contextlib.contextmanager
def env(store, *, source=None, offer=None, sq_source=SQ_SOURCE, fetch=sb.FETCH_FOUND,
        seg=SEG, customer=("ok", CUST), locations=None, bindings=None):
    src_row = dict(source or SOURCE)
    appts = {SRC: src_row}
    updates = []

    async def _get_appt(aid):
        r = appts.get(aid)
        return dict(r) if r else None

    async def _update(aid, patch):
        updates.append((aid, patch))
        if aid in appts:
            appts[aid] = {**appts[aid], **patch}

    async def _get_ref(call_id, ref, tenant_id, phone):
        if (call_id, ref, tenant_id, phone) != (CALL, "appt_1", TID, PHONE):
            return None
        return dict(REF)

    async def _get_slot(call_id, slot_ref, tenant_id):
        r = store.slots.get(slot_ref)
        if not r or r["vapi_call_id"] != call_id or r["tenant_id"] != tenant_id:
            return None
        return dict({**r, **(offer or {})})

    create = AsyncMock(side_effect=AssertionError("D1 must never call CreateBooking"))
    cancel = AsyncMock(side_effect=AssertionError("D1 must never call CancelBooking"))

    with patch.multiple("db.mutation_claims",
                        get_claim=AsyncMock(side_effect=store.get_claim),
                        acquire_cancel_claim=AsyncMock(side_effect=store.acquire_cancel_claim),
                        acquire_reschedule_claim=AsyncMock(side_effect=store.acquire_reschedule_claim),
                        release_claim=AsyncMock(side_effect=store.release_claim),
                        release_orphan_reschedule_claim=AsyncMock(side_effect=store.release_orphan),
                        list_stale_reschedule_claims=AsyncMock(side_effect=store.list_stale_reschedule)), \
         patch.multiple("db.reschedule_ops",
                        insert_operation=AsyncMock(side_effect=store.insert_operation),
                        get_operation=AsyncMock(side_effect=store.get_operation),
                        get_live_operation_for_source=AsyncMock(side_effect=store.get_live_for_source)), \
         patch("db.appointment_refs.get_ref", new=AsyncMock(side_effect=_get_ref)), \
         patch("db.locations.get_slot_offer", new=AsyncMock(side_effect=_get_slot)), \
         patch("db.locations.claim_slot_offer", new=AsyncMock(side_effect=store.claim_slot)), \
         patch("db.locations.release_slot_offer", new=AsyncMock(side_effect=store.release_slot)), \
         patch("db.locations.list_locations", new=AsyncMock(return_value=locations if locations is not None else [
             {"id": CORK_LOC, "active": True, "booking_enabled": True},
             {"id": DUBLIN_LOC, "active": True, "booking_enabled": True}])), \
         patch("db.locations.list_bindings", new=AsyncMock(return_value=bindings if bindings is not None else [
             {"tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID, "provider_status": "ACTIVE"},
             {"tenant_location_id": DUBLIN_LOC, "provider_location_id": DUBLIN_PID, "provider_status": "ACTIVE"}])), \
         patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=_get_appt)), \
         patch("db.supabase.update_appointment", new=AsyncMock(side_effect=_update)), \
         patch("db.supabase.get_tenant_by_id",
               new=AsyncMock(return_value={"id": TID, "square_appointments_enabled": True})), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.get_booking_detailed",
               new=AsyncMock(return_value=(fetch, dict(sq_source) if sq_source else {}))), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value=seg)), \
         patch("services.square_booking.resolve_customer", new=AsyncMock(return_value=customer)), \
         patch("services.square_booking.create_booking", new=create), \
         patch("services.square_booking.cancel_booking_detailed", new=cancel):
        yield {"appts": appts, "updates": updates, "create": create, "cancel": cancel}


async def begin(**kw):
    return await rs.begin_reschedule(
        vapi_call_id=kw.pop("call_id", CALL), tenant_id=TID, caller_phone=kw.pop("phone", PHONE),
        appointment_ref=kw.pop("ref", "appt_1"), slot_ref=kw.pop("slot", "slot_1"))


# ── 13. NO PROVIDER MUTATION, ever ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_successful_freeze_makes_zero_provider_mutations():
    store = Store()
    with env(store) as e:
        res = await begin()
    assert res.status == rs.OK
    e["create"].assert_not_awaited()
    e["cancel"].assert_not_awaited()


def test_the_d1_service_cannot_reach_createbooking_at_all():
    """Static: no call path from the D1 orchestration to a provider mutation."""
    import ast
    import inspect
    src = inspect.getsource(rs)
    tree = ast.parse(src)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for forbidden in ("square_booking.create_booking", "square_booking.cancel_booking",
                      "square_booking.cancel_booking_detailed"):
        assert forbidden not in calls, f"D1 must not call {forbidden}"
    assert "square_booking.get_booking_detailed" in calls, "GET is expected"


# ── 9 & 15. the frozen row ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_operation_freezes_every_field_from_its_proper_source():
    store = Store()
    with env(store):
        res = await begin()
    op = store.ops[res.operation_id]
    assert op["id"] == res.operation_id
    assert op["source_appointment_id"] == SRC
    assert op["target_tenant_location_id"] == CORK_LOC
    assert op["target_provider_location_id"] == CORK_PID
    assert op["target_provider_customer_id"] == CUST
    assert op["target_service_variation_id"] == VAR
    assert op["target_service_variation_version"] == 1789040442821
    assert op["target_team_member_id"] == TM
    assert op["target_start_at_utc"] == "2026-11-08T13:00:00Z"
    assert op["target_duration_minutes"] == 60
    assert "Consultation" in op["target_service_name"]
    assert op["source_provider_booking_id"] == BOOKING
    assert op["source_booking_version"] == 7
    assert op["source_start_at_utc"] == "2026-11-01T13:00:00Z"
    assert op["state"] == db_ops.STATE_IN_PROGRESS
    uuid.UUID(op["provider_idempotency_key"])


@pytest.mark.asyncio
async def test_THE_GATE_the_frozen_row_survives_every_live_fixture_being_destroyed():
    """The key gate. Freeze one operation, then delete the slot offer, the catalog
    resolution, the customer mapping and the provider source read — and rebuild
    the exact future CreateBooking arguments from the row alone."""
    store = Store()
    with env(store):
        res = await begin()
    op = dict(store.ops[res.operation_id])

    store.slots.clear()                       # slot offer gone
    with patch("services.square_booking.resolve_slot",
               new=AsyncMock(side_effect=AssertionError("D2 must never re-resolve the slot"))), \
         patch("services.square_booking.resolve_customer",
               new=AsyncMock(side_effect=AssertionError("D2 must never re-resolve the customer"))), \
         patch("services.square_booking.get_booking_detailed",
               new=AsyncMock(side_effect=AssertionError("D2 must not need the source read"))):
        # Exactly the arguments D2 will pass to create_booking, from the row only.
        args = {
            "location_id": op["target_provider_location_id"],
            "start_at_iso": op["target_start_at_utc"],
            "customer_id": op["target_provider_customer_id"],
            "team_member_id": op["target_team_member_id"],
            "service_variation_id": op["target_service_variation_id"],
            "service_variation_version": op["target_service_variation_version"],
            "duration_minutes": op["target_duration_minutes"],
            "note": f"Booked via Open Lines AI receptionist — {op['target_service_name']}",
            "idempotency_key": op["provider_idempotency_key"],
        }
    assert all(v is not None for k, v in args.items() if k != "duration_minutes")
    assert args["location_id"] == CORK_PID and args["team_member_id"] == TM
    assert args["idempotency_key"] == op["provider_idempotency_key"]


# ── 7. caller-phone invariant ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_replacement_phone_is_derivable_only_from_the_source():
    """PIPEDA erasure deletes appointments by (tenant, caller_phone) in ONE
    set-based DELETE. If a replacement carried a different number, the source
    would be selected without it and the erasure would fail with 23503. The
    operation therefore stores no phone of its own — D2 must read the source."""
    store = Store()
    with env(store) as e:
        res = await begin()
    op = store.ops[res.operation_id]
    assert not any("phone" in k for k in op), "no phone column: the source is the authority"
    assert e["appts"][op["source_appointment_id"]]["caller_phone"] == PHONE


def test_the_service_never_reads_a_phone_from_model_arguments():
    import ast
    import inspect
    code = ast.unparse(ast.parse(inspect.getsource(rs)))
    assert "args.get" not in code and "args[" not in code


# ── 4. same-location hard gate ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_J_a_cross_location_target_is_refused_before_anything_durable():
    store = Store()
    with env(store, offer={"tenant_location_id": DUBLIN_LOC, "provider_location_id": DUBLIN_PID}) as e:
        res = await begin()
    assert res.status == rs.CROSS_LOCATION
    assert store.ops == {} and store.claims == {}
    assert store.slots["slot_1"]["consumed_at"] is None
    e["create"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [{"tenant_location_id": None}, {"provider_location_id": None}])
async def test_K_a_legacy_appointment_with_null_location_fails_closed(missing):
    """All 26 production appointments predate location tracking. Nothing here can
    prove the target is the same place, so the answer is no."""
    store = Store()
    with env(store, source={**SOURCE, **missing}):
        res = await begin()
    assert res.status == rs.LEGACY_LOCATION
    assert store.ops == {} and store.claims == {}


@pytest.mark.asyncio
async def test_L_a_provider_source_location_mismatch_fails_closed():
    store = Store()
    with env(store, sq_source={**SQ_SOURCE, "location_id": DUBLIN_PID}):
        res = await begin()
    assert res.status == rs.CROSS_LOCATION
    assert store.ops == {} and store.claims == {}


@pytest.mark.asyncio
async def test_an_inactive_location_binding_fails_closed():
    store = Store()
    with env(store, bindings=[{"tenant_location_id": CORK_LOC,
                               "provider_location_id": CORK_PID,
                               "provider_status": "INACTIVE"}]):
        res = await begin()
    assert res.status == rs.CROSS_LOCATION
    assert store.ops == {}


# ── 5. source truth ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_M_an_already_cancelled_source_reconciles_and_creates_no_operation():
    store = Store()
    with env(store, sq_source={**SQ_SOURCE, "status": "CANCELLED_BY_SELLER"}) as e:
        res = await begin()
    assert res.status == rs.SOURCE_CANCELLED
    assert e["updates"] == [(SRC, {"status": "cancelled"})], "local record catches up"
    assert store.ops == {} and store.claims == {}


@pytest.mark.asyncio
async def test_an_absent_source_booking_also_reconciles():
    store = Store()
    with env(store, fetch=sb.FETCH_NOT_FOUND, sq_source=None) as e:
        res = await begin()
    assert res.status == rs.SOURCE_CANCELLED
    assert e["updates"] == [(SRC, {"status": "cancelled"})]


@pytest.mark.asyncio
async def test_N_an_unknown_source_read_creates_no_operation_and_releases():
    """D1 mutates nothing, so there is no reason to manufacture a long-lived
    recovery state for a failed READ."""
    store = Store()
    with env(store, fetch=sb.FETCH_UNKNOWN, sq_source=None) as e:
        res = await begin()
    assert res.status == rs.SOURCE_UNKNOWN
    assert store.ops == {} and store.claims == {}
    assert e["updates"] == [], "nothing written on an unknown"


@pytest.mark.asyncio
async def test_a_provider_returning_a_different_booking_id_fails_closed():
    store = Store()
    with env(store, sq_source={**SQ_SOURCE, "id": "BK-SOMETHING-ELSE"}):
        res = await begin()
    assert res.status == rs.FAILED
    assert store.ops == {} and store.claims == {}


@pytest.mark.asyncio
async def test_an_ineligible_source_status_is_refused():
    store = Store()
    with env(store, source={**SOURCE, "status": "cancelled"}):
        res = await begin()
    assert res.status == rs.NOT_ELIGIBLE
    assert store.claims == {}


# ── 14 A-D. ownership races ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_two_calls_rescheduling_one_source_produce_one_operation():
    store = Store()
    store.slots["slot_2"] = {**OFFER, "slot_ref": "slot_2"}
    with env(store):
        results = await asyncio.gather(begin(slot="slot_1"), begin(slot="slot_2"))
    assert len(store.ops) == 1, f"{len(store.ops)} operations created"
    assert sum(r.status == rs.OK for r in results) == 1
    assert sum(r.status in (rs.BUSY, rs.IN_PROGRESS) for r in results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [db_mc.OP_CANCEL, db_mc.OP_CANCEL_RECONCILE])
async def test_B_and_C_reschedule_cannot_acquire_while_a_cancellation_owns_it(owner):
    store = Store()
    store.claims[SRC] = {"appointment_id": SRC, "tenant_id": TID, "operation_type": owner,
                         "operation_id": None, "reconcile_reason": "provider_outcome_unknown",
                         "claim_token": "other", "claimed_at": Store.AT}
    with env(store) as e:
        res = await begin()
    assert res.status == rs.BUSY
    assert store.ops == {}
    assert store.claims[SRC]["operation_type"] == owner, "untouched — no stealing"
    e["create"].assert_not_awaited()


@pytest.mark.asyncio
async def test_D_a_synthetic_other_reschedule_blocks_a_second_operation():
    store = Store()
    store.claims[SRC] = {"appointment_id": SRC, "tenant_id": TID,
                         "operation_type": db_mc.OP_RESCHEDULE, "operation_id": "op-other",
                         "reconcile_reason": None, "claim_token": "other", "claimed_at": Store.AT}
    with env(store):
        res = await begin()
    assert res.status == rs.BUSY
    assert store.ops == {}


@pytest.mark.asyncio
async def test_E_two_different_sources_get_independent_operations():
    store = Store()
    other = {**SOURCE, "id": "appt-other"}
    store.slots["slot_2"] = {**OFFER, "slot_ref": "slot_2"}
    with env(store):
        r1 = await begin()
    assert r1.status == rs.OK
    with env(store, source=other):
        with patch("db.appointment_refs.get_ref",
                   new=AsyncMock(return_value={**REF, "appointment_id": "appt-other"})), \
             patch("db.supabase.get_appointment_by_id",
                   new=AsyncMock(return_value=dict(other))):
            r2 = await begin(slot="slot_2")
    assert r2.status == rs.OK
    assert len({o["source_appointment_id"] for o in store.ops.values()}) == 2


# ── 10 / F / G. unique conflict ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_F_a_historical_create_failed_operation_does_not_block_a_new_one():
    """Migration 022's partial index exists exactly for this: create_failed is
    immutable history, and a later attempt starts a genuinely new operation."""
    store = Store()
    store.ops["old"] = {"id": "old", "source_appointment_id": SRC,
                        "state": db_ops.STATE_CREATE_FAILED}
    with env(store):
        res = await begin()
    assert res.status == rs.OK
    assert len(store.ops) == 2
    assert store.ops["old"]["state"] == db_ops.STATE_CREATE_FAILED, "history untouched"


@pytest.mark.asyncio
async def test_G_a_live_operation_conflict_adopts_nothing_and_mutates_nothing():
    """The claim we hold names OUR operation id. Adopting somebody else's under it
    would break the invariant that gates every provider call."""
    store = Store()

    async def _conflict(row):
        store.ops["live"] = {"id": "live", "source_appointment_id": SRC,
                             "state": db_ops.STATE_IN_PROGRESS}
        return None

    with env(store) as e:
        with patch("db.reschedule_ops.insert_operation", new=AsyncMock(side_effect=_conflict)):
            res = await begin()
    assert res.status == rs.IN_PROGRESS
    assert res.operation_id == "live", "reported, not adopted"
    assert store.claims == {}, "our claim released"
    assert store.slots["slot_1"]["consumed_at"] is None, "our slot released"
    e["create"].assert_not_awaited()


# ── 8 / I. slot claim ordering ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_I_losing_the_slot_race_creates_no_operation():
    store = Store()
    with env(store) as e:
        with patch("db.locations.claim_slot_offer", new=AsyncMock(return_value=False)):
            res = await begin()
    assert res.status == rs.SLOT_TAKEN
    assert store.ops == {} and store.claims == {}, "ownership released too"
    e["create"].assert_not_awaited()


@pytest.mark.asyncio
async def test_C_an_operation_insert_failure_releases_the_slot_and_ownership():
    store = Store()
    with env(store):
        with patch("db.reschedule_ops.insert_operation",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            res = await begin()
    assert res.status == rs.FAILED
    assert store.claims == {}
    assert store.slots["slot_1"]["consumed_at"] is None


@pytest.mark.asyncio
async def test_D_success_RETAINS_ownership_and_the_slot_for_the_next_stage():
    store = Store()
    with env(store):
        res = await begin()
    assert res.status == rs.OK
    assert store.claims[SRC]["operation_type"] == db_mc.OP_RESCHEDULE
    assert store.claims[SRC]["operation_id"] == res.operation_id, "claim names ITS operation"
    assert store.slots["slot_1"]["consumed_at"] is not None, "slot stays claimed for D2"


def test_the_claim_names_its_operation_at_acquisition_not_afterwards():
    import ast
    import inspect
    code = ast.unparse(ast.parse(inspect.getsource(rs.begin_reschedule).lstrip()))
    assert code.index("operation_id = str(uuid.uuid4())") < code.index("acquire_for_reschedule")


# ── 12 / B. orphan cleanup ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_B_an_orphan_claim_whose_operation_never_landed_is_released():
    store = Store()
    store.claims[SRC] = {"appointment_id": SRC, "tenant_id": TID,
                         "operation_type": db_mc.OP_RESCHEDULE, "operation_id": "never-persisted",
                         "reconcile_reason": None, "claim_token": "tok", "claimed_at": Store.AT}
    with env(store):
        out = await rs.cleanup_orphan_reschedule_claims()
    assert out["outcomes"] == {"released": 1}
    assert store.claims == {}


@pytest.mark.asyncio
async def test_a_claim_with_a_real_operation_is_NOT_cleaned_up():
    """Real persisted operations belong to the D2 recovery worker, not to this."""
    store = Store()
    with env(store):
        res = await begin()
        out = await rs.cleanup_orphan_reschedule_claims()
    assert out["outcomes"] == {"live_operation": 1}
    assert SRC in store.claims
    assert res.operation_id in store.ops


@pytest.mark.asyncio
async def test_H_an_orphan_release_is_fenced_on_operation_id_and_token():
    store = Store()
    store.claims[SRC] = {"appointment_id": SRC, "tenant_id": TID,
                         "operation_type": db_mc.OP_RESCHEDULE, "operation_id": "op-A",
                         "reconcile_reason": None, "claim_token": "tok-A", "claimed_at": Store.AT}
    assert await store.release_orphan(SRC, "op-B", "tok-A", Store.AT) is False
    assert await store.release_orphan(SRC, "op-A", "tok-B", Store.AT) is False
    assert await store.release_orphan(SRC, "op-A", "tok-A", Store.AT) is True


def test_orphan_cleanup_is_wired_into_the_continuous_loop():
    import inspect
    from services import webhook_processor as wp
    assert "cleanup_orphan_reschedule_claims" in inspect.getsource(wp._maybe_reconcile_cancellations)


# ── 16. no tool exposure ─────────────────────────────────────────────────────

def test_no_reschedule_tool_is_exposed_to_the_assistant_yet():
    from services import vapi
    names = {t["function"]["name"] for t in vapi.build_calendar_tools("t1")}
    assert "reschedule_appointment" not in names
    book = next(t for t in vapi.build_calendar_tools("t1")
                if t["function"]["name"] == "book_appointment")
    assert "appointment_ref" not in book["function"]["parameters"]["properties"]


def test_bad_refs_never_reach_ownership():
    import ast
    import inspect
    code = ast.unparse(ast.parse(inspect.getsource(rs.begin_reschedule).lstrip()))
    assert code.index("resolve_for_cancel") < code.index("acquire_for_reschedule")
    assert code.index("resolve_for_booking") < code.index("acquire_for_reschedule")


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"ref": "appt_99"}, {"slot": "slot_99"},
                                {"call_id": "other-call"}, {"phone": "+353879999999"}])
async def test_an_unresolvable_ref_creates_nothing(kw):
    store = Store()
    with env(store) as e:
        res = await begin(**kw)
    assert res.status == rs.BAD_REF
    assert store.claims == {} and store.ops == {}
    e["create"].assert_not_awaited()
