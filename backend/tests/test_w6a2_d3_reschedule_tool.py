"""
W6A2-D3 — the reschedule tool, and everything the assistant is allowed to say.

D1 froze, D2 mutated. D3 is the part a caller actually touches, and its risk is a
different shape: not a lost booking, but a false sentence. "Your appointment is
moved" is a claim about two provider mutations, and it is wrong in five of the
outcomes below. So the tests that matter most here are the ones asserting what
the assistant is told NOT to say.

The second theme is improvised recovery. When an outcome is uncertain, the model
must not try a second reschedule, a booking, or a cancellation to "fix" it --
durable server-side recovery already owns those states, and a second mutation is
how one uncertain booking becomes two certain ones. That policy is asserted from
the tool result itself, not only from the prompt, because the result is what the
model reads in the moment it decides.
"""
import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from db import mutation_claims as db_mc, reschedule_ops as db_ops
from routers import tools
from services import reschedule, reschedule_execute as rx
from services import reschedule_intent as ri
from services import square_booking as sb

TID, CALL, PHONE = "t-dani", "call-1", "+353871234567"
CORK_LOC, CORK_PID = "loc-cork", "L0Q8GTAZCHD42"
DUB_LOC, DUB_PID = "loc-dublin", "L9SA1AQ7XBM6K"
SRC_BOOKING, NEW_BOOKING = "BK-SRC", "BK-NEW"
VAR, TM, CUST = "VAR-CONSULT", "TM-AOIFE", "SQCUST-1"
SERVICE = "Consultation"

TENANT = {"id": TID, "business_name": "DANI Test", "calendar_timezone": "Europe/Dublin",
          "square_appointments_enabled": True}
ADOPTED = [{"id": CORK_LOC, "name": "Cork"}, {"id": DUB_LOC, "name": "Dublin"}]


def appt(aid, *, loc=CORK_LOC, pid=CORK_PID, booking=SRC_BOOKING, svc=SERVICE,
         when="2026-11-01T13:00:00+00:00", status="confirmed", phone=PHONE):
    return {"id": aid, "tenant_id": TID, "caller_phone": phone, "caller_name": "Aoife",
            "service": svc, "appointment_datetime": when, "duration_minutes": 60,
            "status": status, "google_event_id": booking, "vapi_call_id": "call-0",
            "tenant_location_id": loc, "provider_location_id": pid,
            "rescheduled_from_appointment_id": None}


SQ_SOURCE = {"id": SRC_BOOKING, "status": "ACCEPTED", "location_id": CORK_PID,
             "version": 7, "start_at": "2026-11-01T13:00:00Z"}
SEG = {"team_member_id": TM, "service_variation_version": 1789040442821,
       "duration_minutes": 60, "start_at": "2026-11-08T13:00:00Z"}


class World:
    """One in-memory world carrying the real constraints across the whole chain:
    ref PK + full-identity lookup, slot-offer claim CAS, the mutation-claim PK,
    the live-source uniqueness, and migration 018's lineage uniqueness."""

    def __init__(self, appointments=None, offers=None):
        self.appts = {a["id"]: dict(a) for a in (appointments or [appt("a-cork")])}
        self.refs: dict[tuple, dict] = {}
        self.slots: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.ops: dict[str, dict] = {}
        self.events: list[tuple] = []
        self.created_bookings: list[dict] = []
        self.cancelled_bookings: list[str] = []
        self.lock = asyncio.Lock()
        self._n = 0
        for o in (offers or [self.offer("slot_1")]):
            self.slots[o["slot_ref"]] = o

    def offer(self, ref, *, loc=CORK_LOC, pid=CORK_PID, service_name=SERVICE,
              start="2026-11-08T13:00:00Z", var=VAR):
        return {"slot_ref": ref, "vapi_call_id": CALL, "tenant_id": TID,
                "tenant_location_id": loc, "provider_location_id": pid,
                "service_variation_id": var, "service_variation_version": 1789040442821,
                "service_name": service_name, "team_member_id": TM,
                "start_at_utc": start, "duration_minutes": 60,
                "expires_at": "2099-01-01T00:00:00+00:00",
                "consumed_at": None, "booking_id": None}

    def _now(self):
        self._n += 1
        return f"2026-09-11T12:{self._n:02d}:00+00:00"

    # -- appointments ------------------------------------------------------
    async def active_by_phone(self, tenant_id, phone):
        return [dict(a) for a in self.appts.values()
                if a["caller_phone"] == phone and a["status"] in ("confirmed", "pending_payment")]

    async def get_appt(self, aid):
        return dict(self.appts[aid]) if aid in self.appts else None

    async def update_appt(self, aid, patch_):
        if aid in self.appts:
            self.appts[aid].update(patch_)
        return dict(self.appts.get(aid) or {})

    async def by_lineage(self, src):
        for a in self.appts.values():
            if a.get("rescheduled_from_appointment_id") == src:
                return dict(a)
        return None

    async def insert_appt(self, row):
        async with self.lock:
            src = row.get("rescheduled_from_appointment_id")
            if src and any(a.get("rescheduled_from_appointment_id") == src
                           for a in self.appts.values()):
                raise RuntimeError("duplicate key ... appointments_rescheduled_from_unique (23505)")
            new = {**row, "id": f"a-new-{len(self.appts)}"}
            self.appts[new["id"]] = new
            return dict(new)

    # -- refs --------------------------------------------------------------
    async def insert_refs(self, rows):
        for r in rows:
            self.refs[(r["vapi_call_id"], r["appointment_ref"])] = {**r, "consumed_at": None}

    async def count_refs(self, call_id):
        return len([k for k in self.refs if k[0] == call_id])

    async def get_ref(self, call_id, ref, tenant_id, phone):
        r = self.refs.get((call_id, ref))
        if not r or r["tenant_id"] != tenant_id or r["caller_phone"] != phone:
            return None
        return dict(r)

    async def consume_ref(self, call_id, ref):
        r = self.refs.get((call_id, ref))
        if r and r["consumed_at"] is None:
            r["consumed_at"] = self._now()
            return True
        return False

    async def release_ref(self, call_id, ref):
        r = self.refs.get((call_id, ref))
        if r:
            r["consumed_at"] = None

    # -- slot offers -------------------------------------------------------
    async def get_slot(self, call_id, ref, tenant_id):
        r = self.slots.get(ref)
        if not r or r["vapi_call_id"] != call_id or r["tenant_id"] != tenant_id:
            return None
        return dict(r)

    async def claim_slot(self, call_id, ref, tenant_id):
        async with self.lock:
            r = self.slots.get(ref)
            if r and r["consumed_at"] is None:
                r["consumed_at"] = "claimed"
                return True
            return False

    async def release_slot(self, call_id, ref):
        r = self.slots.get(ref)
        if r and r["booking_id"] is None:
            r["consumed_at"] = None

    async def consume_slot(self, call_id, ref, booking_id):
        r = self.slots.get(ref)
        if r and r["booking_id"] is None:
            r["consumed_at"], r["booking_id"] = self._now(), booking_id
        return dict(r or {})

    # -- claims ------------------------------------------------------------
    async def get_claim(self, aid):
        return dict(self.claims[aid]) if aid in self.claims else None

    async def acquire_resched(self, aid, tid, op_id, token):
        async with self.lock:
            if aid in self.claims:
                return None
            self.claims[aid] = {"appointment_id": aid, "tenant_id": tid,
                                "operation_type": db_mc.OP_RESCHEDULE,
                                "operation_id": op_id, "reconcile_reason": None,
                                "claim_token": token, "claimed_at": self._now()}
            return dict(self.claims[aid])

    async def release_claim(self, aid, token, at):
        r = self.claims.get(aid)
        if r and r["claim_token"] == token and r["claimed_at"] == at:
            del self.claims[aid]
            return True
        return False

    # -- operations --------------------------------------------------------
    async def insert_op(self, row):
        async with self.lock:
            if any(o["source_appointment_id"] == row["source_appointment_id"]
                   and o["state"] in db_ops.LIVE_STATES for o in self.ops.values()):
                return None
            self.ops[row["id"]] = dict(row)
            return dict(row)

    async def get_op(self, op_id):
        return dict(self.ops[op_id]) if op_id in self.ops else None

    async def live_for_source(self, src):
        for o in self.ops.values():
            if o["source_appointment_id"] == src and o["state"] in db_ops.LIVE_STATES:
                return dict(o)
        return None

    async def _trans(self, op_id, token, froms, patch_):
        async with self.lock:
            r = self.ops.get(op_id)
            if not (r and r["claim_token"] == token and r["state"] in froms):
                return False
            r.update(patch_)
            r["claimed_at"] = self._now()
            return True

    async def mark_create_failed(self, o, t):
        return await self._trans(o, t, (db_ops.STATE_IN_PROGRESS,),
                                 {"state": db_ops.STATE_CREATE_FAILED})

    async def mark_replacement_created(self, o, t, rid):
        return await self._trans(o, t, (db_ops.STATE_IN_PROGRESS,),
                                 {"state": db_ops.STATE_REPLACEMENT_CREATED,
                                  "replacement_appointment_id": rid})

    async def mark_cancel_failed(self, o, t, reason):
        return await self._trans(o, t, (db_ops.STATE_REPLACEMENT_CREATED,
                                        db_ops.STATE_CANCEL_FAILED),
                                 {"state": db_ops.STATE_CANCEL_FAILED,
                                  "cancel_failure_reason": reason})

    async def mark_completed(self, o, t):
        return await self._trans(o, t, (db_ops.STATE_REPLACEMENT_CREATED,
                                        db_ops.STATE_CANCEL_FAILED),
                                 {"state": db_ops.STATE_COMPLETED})

    async def adopt(self, o, prev, new):
        r = self.ops.get(o)
        if r and r["claim_token"] == prev:
            r["claim_token"] = new
            return True
        return False


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}


@contextlib.contextmanager
def env(w, *, create=None, cancel=(sb.CANCEL_OK, {}, ""), fetch=sb.FETCH_FOUND,
        sq_source=SQ_SOURCE, seg=SEG, customer=("ok", CUST), sq_sequence=None):
    """sq_sequence lets the source read CHANGE between D1's freeze and D2's
    pre-cancel recheck — which is exactly what a merchant editing the booking
    mid-flight looks like."""
    seq = list(sq_sequence or [])

    async def _fetch(token, booking_id):
        if seq:
            nxt = seq.pop(0) if len(seq) > 1 else seq[0]
            return (sb.FETCH_FOUND, dict(nxt)) if nxt else (sb.FETCH_NOT_FOUND, {})
        return (fetch, dict(sq_source) if sq_source else {})

    async def _create(token, **kw):
        w.created_bookings.append(kw)
        return {"id": NEW_BOOKING, "status": "ACCEPTED", "version": 0,
                "location_id": kw.get("location_id")}

    async def _cancel(token, booking_id):
        w.cancelled_bookings.append(booking_id)
        return cancel

    create_mock = create or AsyncMock(side_effect=_create)

    with patch.multiple("db.supabase",
                        get_active_appointments_by_phone=AsyncMock(side_effect=w.active_by_phone),
                        get_appointment_by_id=AsyncMock(side_effect=w.get_appt),
                        get_appointment_by_rescheduled_from=AsyncMock(side_effect=w.by_lineage),
                        insert_appointment=AsyncMock(side_effect=w.insert_appt),
                        update_appointment=AsyncMock(side_effect=w.update_appt),
                        get_tenant_by_id=AsyncMock(return_value=dict(TENANT))), \
         patch.multiple("db.appointment_refs",
                        insert_refs=AsyncMock(side_effect=w.insert_refs),
                        count_refs=AsyncMock(side_effect=w.count_refs),
                        get_ref=AsyncMock(side_effect=w.get_ref),
                        consume_ref=AsyncMock(side_effect=w.consume_ref),
                        release_ref=AsyncMock(side_effect=w.release_ref)), \
         patch.multiple("db.locations",
                        get_slot_offer=AsyncMock(side_effect=w.get_slot),
                        claim_slot_offer=AsyncMock(side_effect=w.claim_slot),
                        release_slot_offer=AsyncMock(side_effect=w.release_slot),
                        consume_slot_offer=AsyncMock(side_effect=w.consume_slot),
                        list_locations=AsyncMock(return_value=[
                            {"id": CORK_LOC, "active": True, "booking_enabled": True},
                            {"id": DUB_LOC, "active": True, "booking_enabled": True}]),
                        list_bindings=AsyncMock(return_value=[
                            {"tenant_location_id": CORK_LOC, "provider_location_id": CORK_PID,
                             "provider_status": "ACTIVE"},
                            {"tenant_location_id": DUB_LOC, "provider_location_id": DUB_PID,
                             "provider_status": "ACTIVE"}])), \
         patch.multiple("db.mutation_claims",
                        get_claim=AsyncMock(side_effect=w.get_claim),
                        acquire_reschedule_claim=AsyncMock(side_effect=w.acquire_resched),
                        release_claim=AsyncMock(side_effect=w.release_claim)), \
         patch.multiple("db.reschedule_ops",
                        insert_operation=AsyncMock(side_effect=w.insert_op),
                        get_operation=AsyncMock(side_effect=w.get_op),
                        get_live_operation_for_source=AsyncMock(side_effect=w.live_for_source),
                        mark_create_failed=AsyncMock(side_effect=w.mark_create_failed),
                        mark_replacement_created=AsyncMock(side_effect=w.mark_replacement_created),
                        mark_cancel_failed=AsyncMock(side_effect=w.mark_cancel_failed),
                        mark_completed=AsyncMock(side_effect=w.mark_completed),
                        adopt_claim_token=AsyncMock(side_effect=w.adopt)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(True, ADOPTED))), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.get_booking_detailed",
               new=AsyncMock(side_effect=_fetch)), \
         patch("services.square_booking.resolve_slot", new=AsyncMock(return_value=seg)), \
         patch("services.square_booking.resolve_customer", new=AsyncMock(return_value=customer)), \
         patch("services.square_booking.create_booking", new=create_mock), \
         patch("services.square_booking.cancel_booking_detailed",
               new=AsyncMock(side_effect=_cancel)), \
         patch("services.analytics.capture",
               new=lambda *a, **k: w.events.append((a[1] if len(a) > 1 else "", k))):
        yield {"create": create_mock}


async def call(ref=None, slot=None, phone=PHONE, call_id=CALL):
    args = {}
    if ref:
        args["appointment_ref"] = ref
    if slot:
        args["slot_ref"] = slot
    body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
        "name": "reschedule_appointment", "arguments": json.dumps(args)}}],
        "call": {"id": call_id, "customer": {"number": phone}}}}
    res = await tools.reschedule_appointment(_Req(), TID, body)
    return res["results"][0]["result"]


# ═══════════════════════════════════════════════════════════════════════════
# §12 — tool contract matrix
# ═══════════════════════════════════════════════════════════════════════════

def test_A_schema_has_exactly_appointment_ref_and_slot_ref():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "reschedule_appointment")
    props = t["function"]["parameters"]["properties"]
    assert set(props) == {"appointment_ref", "slot_ref"}
    assert t["function"]["parameters"]["required"] == []


def test_B_no_provider_location_customer_date_or_time_arguments():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "reschedule_appointment")
    props = set(t["function"]["parameters"]["properties"])
    forbidden = {"date", "time", "location", "service", "staff", "caller_phone",
                 "caller_name", "provider_booking_id", "square_location_id",
                 "customer_id", "booking_id", "reschedule", "tenant_location_id"}
    assert not (props & forbidden)


@pytest.mark.asyncio
async def test_C_valid_refs_invoke_the_engine_exactly_once():
    w = World()
    with env(w) as e:
        await call()                                  # stage 1 mints appt_1
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 1
    assert w.cancelled_bookings == [SRC_BOOKING]
    assert "moved" in text.lower()


@pytest.mark.asyncio
async def test_D_completed_reads_as_a_truthful_success():
    w = World()
    with env(w):
        await call()
        text = await call("appt_1", "slot_1")
    assert "has been moved" in text
    assert "old time is cancelled" in text
    assert ri.message_for(ri.COMPLETED) == text


@pytest.mark.asyncio
async def test_E_create_failed_says_the_original_is_still_in_place():
    w = World()
    boom = AsyncMock(side_effect=RuntimeError("HTTP 400"))
    with env(w, create=boom):
        await call()
        text = await call("appt_1", "slot_1")
    assert "ORIGINAL appointment is still in place" in text
    assert "moved" not in text.lower().replace("could not be booked", "")
    assert w.appts["a-cork"]["status"] == "confirmed"
    assert w.cancelled_bookings == []


@pytest.mark.asyncio
async def test_F_busy_makes_no_provider_mutation():
    w = World()
    w.claims["a-cork"] = {"appointment_id": "a-cork", "tenant_id": TID,
                          "operation_type": db_mc.OP_CANCEL, "operation_id": None,
                          "reconcile_reason": None, "claim_token": "other",
                          "claimed_at": "2026-09-11T11:00:00+00:00"}
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert "already being changed" in text
    assert "Do NOT call reschedule_appointment" in text


@pytest.mark.asyncio
async def test_G_source_changed_end_to_end_never_cancels_the_merchants_edit():
    """D1 freezes against version 7; the merchant then edits; D2 must refuse.

    The replacement is real by then, so the honest outcome is "both exist, a human
    must look" — never "moved", and never a cancellation of the edited booking.
    """
    w = World()
    edited = {**SQ_SOURCE, "version": 99, "start_at": "2026-11-01T17:00:00Z"}
    with env(w, sq_sequence=[SQ_SOURCE, edited]) as e:
        await call()
        text = await call("appt_1", "slot_1")

    assert e["create"].await_count == 1            # the replacement was made
    assert w.cancelled_bookings == []              # the edit was NOT cancelled
    assert w.appts["a-cork"]["status"] == "confirmed"
    assert await w.by_lineage("a-cork") is not None

    op = next(iter(w.ops.values()))
    assert op["state"] == db_ops.STATE_CANCEL_FAILED
    assert op["cancel_failure_reason"] == rx.REASON_SOURCE_CHANGED
    assert w.claims                                # ownership HELD for an operator

    assert text == ri.message_for(ri.SOURCE_CHANGED)
    assert "has been moved" not in text


@pytest.mark.asyncio
async def test_G2_source_changed_outcome_maps_to_a_human_attention_message():
    text = ri.message_for(ri.SOURCE_CHANGED)
    assert "changed by the business" in text
    assert "Do NOT tell the caller their appointment was moved" in text
    assert "Do NOT call reschedule_appointment" in text


@pytest.mark.asyncio
async def test_H_cancel_failed_and_unknown_are_never_represented_as_completed():
    for outcome in (ri.CANCEL_FAILED, ri.UNRESOLVED, ri.SOURCE_CHANGED):
        text = ri.message_for(outcome)
        assert "has been moved" not in text
        assert "Do NOT" in text
    # and the engine's uncertain states map into that family, never to COMPLETED
    for engine_state in (rx.CANCEL_RETRYABLE, rx.CANCEL_UNKNOWN, rx.CREATE_UNKNOWN,
                         rx.FENCED, rx.INCIDENT, rx.SOURCE_CHANGED):
        assert ri._FROM_D2[engine_state] != ri.COMPLETED


@pytest.mark.asyncio
async def test_H2_a_failed_source_cancellation_tells_the_caller_they_may_have_both():
    w = World()
    with env(w, cancel=(sb.CANCEL_UNKNOWN, {}, "")):
        await call()
        text = await call("appt_1", "slot_1")
    assert "could NOT be cancelled" in text
    assert "may still have both" in text
    assert "has been moved" not in text
    assert w.appts["a-cork"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_I_expired_appointment_ref_asks_for_a_fresh_list():
    w = World()
    with env(w) as e:
        await call()
        w.refs[(CALL, "appt_1")]["expires_at"] = "2020-01-01T00:00:00+00:00"
        text = await call("appt_1", "slot_1")
    assert "out of date" in text
    assert "list the appointments again" in text
    assert e["create"].await_count == 0


@pytest.mark.asyncio
async def test_J_expired_slot_ref_asks_for_fresh_availability():
    w = World()
    with env(w) as e:
        await call()
        w.slots["slot_1"]["expires_at"] = "2020-01-01T00:00:00+00:00"
        text = await call("appt_1", "slot_1")
    assert "check_availability again" in text
    assert e["create"].await_count == 0


@pytest.mark.asyncio
async def test_K_cross_location_is_refused_before_any_provider_mutation():
    w = World(offers=[World().offer("slot_1", loc=DUB_LOC, pid=DUB_PID)])
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert "DIFFERENT location isn't something I can do" in text
    assert "Do NOT cancel it and do NOT book a new one instead" in text
    assert not w.claims                       # ownership never taken


def test_L_book_appointment_still_has_no_reschedule_behaviour():
    from services import vapi
    book = next(x for x in vapi.build_calendar_tools("t1")
                if x["function"]["name"] == "book_appointment")
    props = set(book["function"]["parameters"]["properties"])
    assert "appointment_ref" not in props
    assert "never moves, replaces or cancels" in book["function"]["description"]


def test_M_cancel_appointment_is_not_a_substitute_for_moving():
    from services import vapi
    src = __import__("inspect").getsource(vapi)
    assert "NEVER use it to move an existing one" in src
    assert "never cancel an appointment as a way of moving it" in src.lower()
    cancel = next(x for x in vapi.build_calendar_tools("t1")
                  if x["function"]["name"] == "cancel_appointment")
    assert set(cancel["function"]["parameters"]["properties"]) == {"appointment_ref"}


# ═══════════════════════════════════════════════════════════════════════════
# §3 — selection: never guess which appointment
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_selection_one_appointment_is_listed_not_moved():
    w = World()
    with env(w) as e:
        text = await call()
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert "one upcoming appointment" in text
    assert "confirm they want it moved" in text


@pytest.mark.asyncio
async def test_selection_two_appointments_asks_which_one():
    w = World(appointments=[appt("a-cork"),
                            appt("a-dub", loc=DUB_LOC, pid=DUB_PID, booking="BK-DUB",
                                 svc="Dress Fitting", when="2026-11-02T14:30:00+00:00")])
    with env(w) as e:
        text = await call()
    assert "2 upcoming appointments" in text
    assert "ask which one they want moved" in text
    assert e["create"].await_count == 0


@pytest.mark.asyncio
async def test_selection_never_reveals_internal_identifiers():
    w = World()
    with env(w):
        text = await call()
    for secret in (SRC_BOOKING, CORK_PID, CUST, VAR, TM, "a-cork"):
        assert secret not in text
    assert "WITHOUT the reference" in text


@pytest.mark.asyncio
async def test_an_appointment_ref_without_a_slot_ref_asks_for_availability():
    w = World()
    with env(w) as e:
        await call()
        text = await call("appt_1")
    assert "not a new time" in text
    assert "check_availability" in text
    assert e["create"].await_count == 0
    assert not w.claims


# ═══════════════════════════════════════════════════════════════════════════
# §5 — the service-preservation decision, made explicit
# ═══════════════════════════════════════════════════════════════════════════

def test_service_preservation_is_an_explicit_named_decision():
    assert ri.REQUIRE_SAME_SERVICE is True


@pytest.mark.asyncio
async def test_a_slot_for_a_different_service_is_refused_before_ownership():
    w = World(offers=[World().offer("slot_1", service_name="Dress Fitting")])
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert not w.claims
    assert "different service" in text
    assert "keeps the SAME service" in text


@pytest.mark.asyncio
async def test_an_appointment_with_no_recorded_service_fails_closed():
    w = World(appointments=[appt("a-cork", svc="")])
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert "different service" in text


# ═══════════════════════════════════════════════════════════════════════════
# §8 — the model must never improvise a recovery
# ═══════════════════════════════════════════════════════════════════════════

def test_every_uncertain_outcome_forbids_a_second_mutation():
    for outcome in ri.NO_RETRY:
        text = ri.message_for(outcome)
        assert "Do NOT call reschedule_appointment, book_appointment or " \
               "cancel_appointment again" in text, outcome


def test_no_uncertain_outcome_claims_success_or_failure_it_cannot_prove():
    unresolved = ri.message_for(ri.UNRESOLVED)
    assert "Do NOT say the appointment was moved" in unresolved
    assert "do NOT say it failed" in unresolved


def test_only_completed_carries_success_wording():
    successes = [o for o, m in ri._MESSAGES.items() if "has been moved" in m]
    assert successes == [ri.COMPLETED]


def test_the_prompt_forbids_improvised_recovery_too():
    from services import vapi
    src = __import__("inspect").getsource(vapi)
    assert ("Do NOT call reschedule_appointment, book_appointment or "
            "cancel_appointment again to try to fix it") in src


# ═══════════════════════════════════════════════════════════════════════════
# §10 — identity cannot be injected
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_replacement_inherits_the_source_caller_phone_exactly():
    w = World()
    with env(w):
        await call()
        await call("appt_1", "slot_1")
    repl = await w.by_lineage("a-cork")
    assert repl["caller_phone"] == w.appts["a-cork"]["caller_phone"] == PHONE


@pytest.mark.asyncio
async def test_a_model_supplied_phone_cannot_reach_the_engine():
    """The schema has no phone field, and call metadata wins regardless."""
    w = World()
    with env(w):
        await call()
        body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
            "name": "reschedule_appointment", "arguments": json.dumps(
                {"appointment_ref": "appt_1", "slot_ref": "slot_1",
                 "caller_phone": "+19999999999"})}}],
            "call": {"id": CALL, "customer": {"number": PHONE}}}}
        await tools.reschedule_appointment(_Req(), TID, body)
    repl = await w.by_lineage("a-cork")
    assert repl["caller_phone"] == PHONE


@pytest.mark.asyncio
async def test_another_callers_ref_is_not_usable():
    w = World()
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1", phone="+353879999999")
    assert e["create"].await_count == 0
    assert "couldn't match that" in text or "look up the appointment" in text


# ═══════════════════════════════════════════════════════════════════════════
# §11 — analytics never announce an unproven success
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_success_analytics_fire_only_on_a_proven_completion():
    w = World()
    with env(w):
        await call()
        await call("appt_1", "slot_1")
    names = [e[0] for e in w.events]
    assert "reschedule_requested" in names
    assert "reschedule_completed" in names


@pytest.mark.asyncio
async def test_an_uncertain_outcome_is_recorded_as_partial_not_completed():
    w = World()
    with env(w, cancel=(sb.CANCEL_UNKNOWN, {}, "")):
        await call()
        await call("appt_1", "slot_1")
    names = [e[0] for e in w.events]
    assert "reschedule_completed" not in names
    assert "reschedule_partial" in names


@pytest.mark.asyncio
async def test_a_definitive_create_failure_is_recorded_as_such():
    w = World()
    with env(w, create=AsyncMock(side_effect=RuntimeError("HTTP 400"))):
        await call()
        await call("appt_1", "slot_1")
    names = [e[0] for e in w.events]
    assert "reschedule_create_failed" in names
    assert "reschedule_completed" not in names


# ═══════════════════════════════════════════════════════════════════════════
# §14 — full internal end-to-end
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_14_full_end_to_end_listing_to_completion():
    w = World()
    with env(w) as e:
        listed = await call()
        assert "appt_1" in listed
        text = await call("appt_1", "slot_1")

    assert text == ri.message_for(ri.COMPLETED)

    # exactly one replacement CreateBooking, built from the frozen operation
    assert e["create"].await_count == 1
    sent = w.created_bookings[0]
    op = next(iter(w.ops.values()))
    assert sent["location_id"] == op["target_provider_location_id"]
    assert sent["customer_id"] == op["target_provider_customer_id"]
    assert sent["idempotency_key"] == op["provider_idempotency_key"]

    # exactly one source CancelBooking
    assert w.cancelled_bookings == [SRC_BOOKING]

    # local truth
    assert w.appts["a-cork"]["status"] == "cancelled"
    repl = await w.by_lineage("a-cork")
    assert repl and repl["status"] == "confirmed"
    assert repl["google_event_id"] == NEW_BOOKING
    assert repl["rescheduled_from_appointment_id"] == "a-cork"
    assert repl["caller_phone"] == PHONE
    assert repl["tenant_location_id"] == CORK_LOC

    # operation, ownership, slot, ref
    assert op["state"] == db_ops.STATE_COMPLETED
    assert op["replacement_appointment_id"] == repl["id"]
    assert not w.claims                                   # ownership released
    assert w.slots["slot_1"]["booking_id"] == NEW_BOOKING  # slot finalized
    assert w.refs[(CALL, "appt_1")]["consumed_at"]         # ref spent


@pytest.mark.asyncio
async def test_14b_a_second_identical_tool_call_does_not_book_twice():
    w = World()
    with env(w) as e:
        await call()
        await call("appt_1", "slot_1")
        second = await call("appt_1", "slot_1")
    assert e["create"].await_count == 1
    lineage = [a for a in w.appts.values()
               if a.get("rescheduled_from_appointment_id") == "a-cork"]
    assert len(lineage) == 1
    assert "has been moved" not in second


# ═══════════════════════════════════════════════════════════════════════════
# §13 — conversation simulations
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sim_1_move_my_friday_appointment_to_3pm():
    w = World()
    with env(w):
        listed = await call()
        assert "Cork" in listed and "appt_1" in listed
        done = await call("appt_1", "slot_1")
    assert done == ri.message_for(ri.COMPLETED)
    assert w.appts["a-cork"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_sim_2_two_appointments_the_assistant_must_ask():
    w = World(appointments=[appt("a-cork"),
                            appt("a-dub", loc=DUB_LOC, pid=DUB_PID, booking="BK-DUB",
                                 when="2026-11-02T14:30:00+00:00")])
    with env(w) as e:
        text = await call()
    assert "ask which one" in text
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []


@pytest.mark.asyncio
async def test_sim_3_desired_time_unavailable_nothing_is_cancelled():
    w = World()
    with env(w, seg=None) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert w.appts["a-cork"]["status"] == "confirmed"
    assert "just been taken" in text
    assert "check_availability again" in text


@pytest.mark.asyncio
async def test_sim_4_cross_location_request_explains_and_destroys_nothing():
    w = World(offers=[World().offer("slot_1", loc=DUB_LOC, pid=DUB_PID)])
    with env(w) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert w.appts["a-cork"]["status"] == "confirmed"
    assert "the team can move it between locations" in text


@pytest.mark.asyncio
async def test_sim_5_source_changed_says_team_attention_and_no_retry():
    text = ri.message_for(ri.SOURCE_CHANGED)
    assert "was NOT cancelled" in text
    assert "team needs to confirm" in text
    assert "Do NOT call reschedule_appointment, book_appointment or " \
           "cancel_appointment again" in text


@pytest.mark.asyncio
async def test_sim_6_cancel_failed_avoids_saying_your_appointment_is_moved():
    w = World()
    with env(w, cancel=(sb.CANCEL_FAILED, {}, "SOME_CODE")):
        await call()
        text = await call("appt_1", "slot_1")
    assert "has been moved" not in text
    assert "may still have both" in text
    # the replacement really does exist — the message must not deny it either
    assert await w.by_lineage("a-cork") is not None


@pytest.mark.asyncio
async def test_sim_7_unknown_outcome_reports_uncertainty_and_stops():
    w = World()
    with env(w, create=AsyncMock(side_effect=sb.BookingOutcomeUnknown("timeout"))) as e:
        await call()
        text = await call("appt_1", "slot_1")
    assert e["create"].await_count == 1
    assert w.cancelled_bookings == []
    assert "cannot tell you whether it went through" in text
    assert "Do NOT call reschedule_appointment" in text
    # the slot stays claimed and ownership stays held for recovery
    assert w.slots["slot_1"]["consumed_at"] == "claimed"
    assert w.claims


@pytest.mark.asyncio
async def test_sim_8_caller_changes_their_mind_before_the_tool_runs():
    w = World()
    with env(w) as e:
        await call()                       # listed only
    assert e["create"].await_count == 0
    assert w.cancelled_bookings == []
    assert not w.claims
    assert not w.ops
    assert w.appts["a-cork"]["status"] == "confirmed"
