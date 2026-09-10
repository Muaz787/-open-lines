"""
W6A1 — cancel the appointment the caller chose, or cancel nothing.

cancel_appointment took NO arguments. It read the caller's number, took the
earliest active appointment, and cancelled it. For one location that is usually
the right guess. For DANI it means a caller with a Cork consultation and a Dublin
fitting loses whichever is sooner, silently, and finds out by turning up.

It was worse than a wrong guess: a failed Square cancel was logged and stepped
over, and the row was then marked cancelled anyway — so the caller was told it
was done while the booking stayed live in the merchant's calendar.

Both are closed here. The tests that matter most are the ones where nothing
happens: an invalid ref, a location that does not match Square's own copy, a
provider that failed, a second caller's ref. In every one of those the correct
behaviour is to destroy nothing and say so.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import appointment_refs as ar, square_booking as sb

TID = "t-dani"
CALL = "call-1"
PHONE = "+353871234567"
OTHER_PHONE = "+353879999999"
CORK_PID, DUBLIN_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K"
CORK_LOC, DUBLIN_LOC = "loc-cork", "loc-dublin"

TENANT = {"id": TID, "business_name": "DANI Test", "square_appointments_enabled": True,
          "calendar_timezone": "Europe/Dublin"}
ADOPTED = [{"id": CORK_LOC, "name": "Cork"}, {"id": DUBLIN_LOC, "name": "Dublin"}]


def appt(aid, *, loc=CORK_LOC, pid=CORK_PID, booking="BK-CORK", svc="Consultation",
         when="2026-09-14T13:00:00+00:00", status="confirmed", phone=PHONE):
    return {"id": aid, "tenant_id": TID, "caller_phone": phone, "service": svc,
            "appointment_datetime": when, "status": status, "google_event_id": booking,
            "tenant_location_id": loc, "provider_location_id": pid}


CORK = appt("a-cork")
DUBLIN = appt("a-dublin", loc=DUBLIN_LOC, pid=DUBLIN_PID, booking="BK-DUBLIN",
              svc="Dress Fitting", when="2026-09-15T14:30:00+00:00")


class Refs:
    """A fake call_appointment_refs enforcing the real constraints: composite PK,
    the full-identity lookup, and consume-once."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}
        self.lock = asyncio.Lock()

    async def insert_refs(self, rows):
        for r in rows:
            self.rows[(r["vapi_call_id"], r["appointment_ref"])] = {**r, "consumed_at": None}

    async def count_refs(self, call_id):
        return len([r for r in self.rows.values() if r["vapi_call_id"] == call_id])

    async def get_ref(self, call_id, ref, tenant_id, caller_phone):
        r = self.rows.get((call_id, ref))
        if not r or r["tenant_id"] != tenant_id or r["caller_phone"] != caller_phone:
            return None                      # wrong call/tenant/caller: simply not yours
        return dict(r)

    async def consume_ref(self, call_id, ref):
        async with self.lock:
            r = self.rows.get((call_id, ref))
            if r and r["consumed_at"] is None:
                r["consumed_at"] = "now"
                return True
            return False

    async def release_ref(self, call_id, ref):
        r = self.rows.get((call_id, ref))
        if r:
            r["consumed_at"] = None

    async def delete_refs(self, call_id):
        for k in [k for k, v in self.rows.items() if v["vapi_call_id"] == call_id]:
            del self.rows[k]

    async def purge_expired_refs(self, now_iso):
        gone = [k for k, v in self.rows.items() if str(v["expires_at"]) < now_iso]
        for k in gone:
            del self.rows[k]
        return len(gone)


class Ctx:
    def __init__(self, candidates=(), refs=None, appts=None, tenant=None,
                 booking=None, cancel=(sb.CANCEL_OK, {}), get_booking_error=None):
        self.refs = refs or Refs()
        self.candidates = list(candidates)
        self.appts = {a["id"]: a for a in (appts or candidates)}
        self.tenant = tenant or TENANT
        self.booking = booking
        self.cancel_result = cancel
        self.get_booking_error = get_booking_error
        self.cancel_calls = []
        self.updates = []

    async def _get_booking(self, token, bid):
        if self.get_booking_error:
            raise self.get_booking_error
        if self.booking is not None:
            return self.booking
        loc = CORK_PID if bid == "BK-CORK" else DUBLIN_PID
        return {"id": bid, "status": "ACCEPTED", "location_id": loc, "version": 0}

    async def _cancel(self, token, bid):
        self.cancel_calls.append(bid)
        return self.cancel_result

    async def _update(self, aid, patch):
        self.updates.append((aid, patch))
        return {}

    def __enter__(self):
        self._p = [
            patch("db.appointment_refs.insert_refs", new=AsyncMock(side_effect=self.refs.insert_refs)),
            patch("db.appointment_refs.count_refs", new=AsyncMock(side_effect=self.refs.count_refs)),
            patch("db.appointment_refs.get_ref", new=AsyncMock(side_effect=self.refs.get_ref)),
            patch("db.appointment_refs.consume_ref", new=AsyncMock(side_effect=self.refs.consume_ref)),
            patch("db.appointment_refs.release_ref", new=AsyncMock(side_effect=self.refs.release_ref)),
            patch("db.supabase.get_active_appointments_by_phone",
                  new=AsyncMock(return_value=self.candidates)),
            patch("db.supabase.get_appointment_by_id",
                  new=AsyncMock(side_effect=lambda aid: self.appts.get(aid))),
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
            patch("db.supabase.update_appointment", new=AsyncMock(side_effect=self._update)),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=None)),
            patch("services.call_location.is_multi_location",
                  new=AsyncMock(return_value=(True, ADOPTED))),
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
            patch("services.square_booking.get_booking", new=AsyncMock(side_effect=self._get_booking)),
            patch("services.square_booking.cancel_booking_detailed", new=AsyncMock(side_effect=self._cancel)),
            patch("services.analytics.capture"),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def call(self, ref=None, phone=PHONE, call_id=CALL, args_extra=None):
        args = dict(args_extra or {})
        if ref:
            args["appointment_ref"] = ref
        body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
            "name": "cancel_appointment", "arguments": __import__("json").dumps(args)}}],
            "call": {"id": call_id, "customer": {"number": phone}}}}
        return await tools.cancel_appointment(_Req(), TID, body)

    @staticmethod
    def text(res):
        return res["results"][0]["result"]

    def cancelled_ids(self):
        return [aid for aid, p in self.updates if p.get("status") == "cancelled"]


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}
    url = type("u", (), {"path": "/tools/x/cancel"})()


# ── 1-3. enumeration ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_appointments_mutates_nothing():
    with Ctx(candidates=[]) as c:
        res = await c.call()
    assert c.cancel_calls == [] and c.updates == []
    assert "don't see any upcoming appointment" in c.text(res)


@pytest.mark.asyncio
async def test_a_single_candidate_is_listed_not_cancelled():
    """The defect in one test. One match is still a guess about which appointment
    the caller meant, so the first call lists and stops."""
    with Ctx(candidates=[CORK]) as c:
        res = await c.call()
    assert c.cancel_calls == [], "the first call must never reach the provider"
    assert c.updates == []
    spoken = c.text(res)
    assert "Consultation" in spoken and "Cork" in spoken and "appt_1" in spoken
    assert "confirm" in spoken.lower()


@pytest.mark.asyncio
async def test_multiple_candidates_are_all_listed_in_time_order():
    with Ctx(candidates=[CORK, DUBLIN]) as c:
        res = await c.call()
    spoken = c.text(res)
    assert c.cancel_calls == []
    assert "appt_1" in spoken and "appt_2" in spoken
    assert spoken.index("Consultation") < spoken.index("Dress Fitting")
    assert "Cork" in spoken and "Dublin" in spoken


# ── 4 & 23. what the model is allowed to see ─────────────────────────────────

@pytest.mark.asyncio
async def test_the_listing_leaks_no_identifier_of_any_kind():
    with Ctx(candidates=[CORK, DUBLIN]) as c:
        res = await c.call()
    spoken = c.text(res)
    for leaked in (CORK_PID, DUBLIN_PID, "BK-CORK", "BK-DUBLIN",
                   "a-cork", "a-dublin", CORK_LOC, DUBLIN_LOC):
        assert leaked not in spoken, f"{leaked} reached the model"


@pytest.mark.asyncio
async def test_the_listing_carries_location_service_date_and_time():
    with Ctx(candidates=[CORK]) as c:
        res = await c.call()
    spoken = c.text(res)
    for expected in ("Consultation", "Cork", "September", "2:00 PM"):
        assert expected in spoken


# ── 5-9. refs fail closed ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_invented_ref_cancels_nothing():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        res = await c.call(ref="appt_99")
    assert c.cancel_calls == [] and c.updates == []
    assert "couldn't find that appointment" in c.text(res)


@pytest.mark.asyncio
async def test_an_expired_ref_cancels_nothing():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        c.refs.rows[(CALL, "appt_1")]["expires_at"] = "2020-01-01T00:00:00+00:00"
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == []
    assert "out of date" in c.text(res)


@pytest.mark.asyncio
async def test_a_ref_from_another_call_cancels_nothing():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        res = await c.call(ref="appt_1", call_id="a-different-call")
    assert c.cancel_calls == []
    assert "couldn't find that appointment" in c.text(res)


@pytest.mark.asyncio
async def test_a_ref_from_another_tenant_cancels_nothing():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        c.refs.rows[(CALL, "appt_1")]["tenant_id"] = "someone-else"
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == []


@pytest.mark.asyncio
async def test_another_callers_ref_cannot_be_consumed():
    """The caller phone is part of the lookup, not a check after it — so this is
    'not yours', which is a harder thing to get wrong than a comparison."""
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        res = await c.call(ref="appt_1", phone=OTHER_PHONE)
    assert c.cancel_calls == []
    assert "couldn't find that appointment" in c.text(res)


@pytest.mark.asyncio
async def test_no_call_id_fails_closed():
    with Ctx(candidates=[CORK]) as c:
        res = await c.call(call_id="")
    assert c.cancel_calls == []
    assert "can't look that up" in c.text(res)


# ── 10 & 19. idempotency ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_consumed_ref_issues_no_second_cancellation():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        await c.call(ref="appt_1")
        assert c.cancel_calls == ["BK-CORK"]
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == ["BK-CORK"], "a retry must not cancel twice"
    assert "already been cancelled" in c.text(res)


@pytest.mark.asyncio
async def test_an_appointment_cancelled_between_listing_and_execution():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        c.appts["a-cork"] = {**CORK, "status": "cancelled"}
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == []
    assert "isn't active any more" in c.text(res)


# ── 20. real concurrency at the destructive boundary ─────────────────────────

@pytest.mark.asyncio
async def test_two_simultaneous_cancels_on_one_ref_reach_the_provider_once():
    """Two tool calls arriving together — a Vapi retry is ordinary. The claim CAS
    is the boundary; only one can win it."""
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        results = await asyncio.gather(c.call(ref="appt_1"), c.call(ref="appt_1"))
    assert len(c.cancel_calls) == 1, f"provider called {len(c.cancel_calls)} times"
    assert c.cancelled_ids() == ["a-cork"]
    assert sum("already been cancelled" in c.text(r) for r in results) == 1


# ── 11, 12, 21, 22. location safety ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_matching_square_location_permits_the_cancel():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == ["BK-CORK"]
    assert c.cancelled_ids() == ["a-cork"]


@pytest.mark.asyncio
async def test_a_square_location_mismatch_fails_closed_before_cancelling():
    """The stale-local-row case: our row says Cork, Square says the booking is in
    Dublin. Cancelling on a phone match alone would destroy a Dublin booking the
    caller never mentioned."""
    with Ctx(candidates=[CORK],
             booking={"id": "BK-CORK", "status": "ACCEPTED",
                      "location_id": DUBLIN_PID, "version": 0}) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == [], "must refuse before CancelBooking"
    assert c.updates == [], "and write nothing — the booking is still live"
    assert "remains in place" in c.text(res)


@pytest.mark.asyncio
async def test_choosing_cork_cannot_cancel_dublin():
    with Ctx(candidates=[CORK, DUBLIN]) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancel_calls == ["BK-CORK"]
    assert "BK-DUBLIN" not in c.cancel_calls
    assert c.cancelled_ids() == ["a-cork"]


@pytest.mark.asyncio
async def test_choosing_dublin_cannot_cancel_cork():
    with Ctx(candidates=[CORK, DUBLIN]) as c:
        await c.call()
        await c.call(ref="appt_2")
    assert c.cancel_calls == ["BK-DUBLIN"]
    assert c.cancelled_ids() == ["a-dublin"]


# ── 13-17. provider outcomes ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_success_marks_the_row_cancelled_and_consumes_the_ref():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]
    assert c.refs.rows[(CALL, "appt_1")]["consumed_at"] is not None


@pytest.mark.asyncio
async def test_a_failed_provider_cancel_leaves_the_status_completely_untouched():
    """The lie W6A1 removes: the row used to be marked cancelled regardless.

    And the status is left EXACTLY as it was — not moved to some third value.
    appointments.status is business state, not an operation result, and the
    codebase reads it two incompatible ways: the cancellation enumeration and the
    reschedule lookups filter IN ('confirmed','pending_payment'), while the
    capacity guard filters != 'cancelled'. A third value is invisible to the first
    group and active to the second, so a caller could never retry a cancellation
    that failed.
    """
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.updates == [], "an unproven cancellation must write nothing at all"
    spoken = c.text(res).lower()
    assert "couldn't confirm the cancellation" in spoken
    assert "appointment remains in place" in spoken
    assert "has been cancelled" not in spoken


@pytest.mark.asyncio
async def test_an_unknown_provider_outcome_is_also_not_reported_as_cancelled():
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_UNKNOWN, {})) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.updates == []
    assert "couldn't confirm" in c.text(res).lower()


# ── status is business state, never an operation result ──────────────────────

@pytest.mark.parametrize("outcome", [sb.CANCEL_FAILED, sb.CANCEL_UNKNOWN, sb.CANCEL_NOT_FOUND])
@pytest.mark.asyncio
async def test_1_a_confirmed_appointment_stays_confirmed_when_the_provider_fails(outcome):
    with Ctx(candidates=[CORK], cancel=(outcome, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.updates == []
    assert c.appts["a-cork"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_2_a_pending_payment_appointment_stays_pending_payment():
    held = appt("a-held", status="pending_payment")
    with Ctx(candidates=[held], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.updates == []
    assert c.appts["a-held"]["status"] == "pending_payment"


@pytest.mark.asyncio
async def test_3_a_location_mismatch_leaves_the_status_untouched():
    with Ctx(candidates=[CORK],
             booking={"id": "BK-CORK", "status": "ACCEPTED",
                      "location_id": DUBLIN_PID, "version": 0}) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == [] and c.updates == []
    assert "remains in place" in c.text(res)


@pytest.mark.asyncio
async def test_4_a_provider_fetch_failure_leaves_the_status_untouched():
    with Ctx(candidates=[CORK], get_booking_error=RuntimeError("connection reset")) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancel_calls == [] and c.updates == []


@pytest.mark.asyncio
async def test_5_a_failed_cancellation_still_appears_in_the_next_enumeration():
    """The retry path only exists if the appointment is still visible. This is the
    concrete consequence of not inventing a third status."""
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
        listing = c.text(await c.call())
    assert "Consultation" in listing and "Cork" in listing


@pytest.mark.asyncio
async def test_6_the_same_unconsumed_ref_can_be_retried_after_a_provider_failure():
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
        assert c.refs.rows[(CALL, "appt_1")]["consumed_at"] is None
        c.cancel_result = (sb.CANCEL_OK, {})
        res = await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]
    assert "cancelled" in c.text(res).lower()


@pytest.mark.asyncio
async def test_7_the_caller_can_retry_from_a_completely_fresh_call():
    """Refs die with the call, so recovery must work from durable state alone."""
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
        c.refs.rows.clear()                       # the first call ended
        c.cancel_result = (sb.CANCEL_OK, {})
        listing = c.text(await c.call(call_id="call-2"))
        assert "Consultation" in listing
        await c.call(ref="appt_1", call_id="call-2")
    assert c.cancelled_ids() == ["a-cork"]


def test_8_and_9_active_lookups_still_treat_a_failed_cancellation_as_active():
    """Audited rather than asserted at runtime: the deposit/reschedule/busy-list
    lookups whitelist ('confirmed','pending_payment') and the capacity guard
    blacklists 'cancelled'. Leaving the status alone is the only value that both
    groups agree is active — which is precisely why no third value is written."""
    import ast
    import inspect
    from db import supabase as dbs

    for fn in (dbs.get_active_appointment_by_phone, dbs.get_active_appointments_by_phone):
        code = ast.unparse(ast.parse(inspect.getsource(fn).lstrip()))
        assert "'confirmed', 'pending_payment'" in code

    guard = ast.unparse(ast.parse(inspect.getsource(dbs.get_active_appointments_between).lstrip()))
    assert "neq('status', 'cancelled')" in guard

    # And the cancellation path writes no status other than 'cancelled'.
    cancel_src = ast.unparse(ast.parse(inspect.getsource(tools.cancel_appointment).lstrip()))
    assert "cancel_failed" not in cancel_src


@pytest.mark.asyncio
async def test_11_provider_success_with_a_failed_local_write_tells_the_truth():
    """Square is cancelled; our record is not. Saying the appointment remains in
    place would be the opposite lie to the one W6A1 removed."""
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        with patch("db.supabase.update_appointment",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            res = await c.call(ref="appt_1")
    spoken = c.text(res).lower()
    assert "has been cancelled with the business" in spoken
    assert "remains in place" not in spoken
    assert c.cancel_calls == ["BK-CORK"]
    # The ref stays CONSUMED so nothing can re-enter the destructive path.
    assert c.refs.rows[(CALL, "appt_1")]["consumed_at"] is not None


@pytest.mark.asyncio
async def test_11b_after_a_partial_failure_the_ref_cannot_drive_another_mutation():
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        with patch("db.supabase.update_appointment",
                   new=AsyncMock(side_effect=RuntimeError("db down"))):
            await c.call(ref="appt_1")
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == ["BK-CORK"], "no second provider mutation"
    assert "already been cancelled" in c.text(res)


@pytest.mark.asyncio
async def test_a_failed_cancel_leaves_the_ref_usable_for_a_retry():
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_FAILED, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
        assert c.refs.rows[(CALL, "appt_1")]["consumed_at"] is None
        c.cancel_result = (sb.CANCEL_OK, {})
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]


@pytest.mark.asyncio
async def test_a_booking_already_cancelled_at_the_provider_reconciles_locally():
    """Intent is already satisfied and our own record is the stale thing. The
    detailed helper checks status before sending anything, so this issues no
    second mutation — reconciling is strictly better than leaving a wrong row."""
    with Ctx(candidates=[CORK], cancel=(sb.CANCEL_ALREADY, {})) as c:
        await c.call()
        await c.call(ref="appt_1")
    assert c.cancelled_ids() == ["a-cork"]


@pytest.mark.asyncio
async def test_a_provider_fetch_failure_cancels_nothing():
    with Ctx(candidates=[CORK], get_booking_error=RuntimeError("connection reset")) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == []
    assert c.cancelled_ids() == []
    assert "couldn't confirm" in c.text(res).lower()


@pytest.mark.asyncio
async def test_an_appointment_with_no_provider_booking_id_cancels_nothing():
    no_booking = appt("a-none", booking="")
    with Ctx(candidates=[no_booking]) as c:
        await c.call()
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == [] and c.cancelled_ids() == []
    assert "can't cancel that one automatically" in c.text(res)


@pytest.mark.asyncio
async def test_a_snapshot_that_no_longer_matches_the_row_fails_closed():
    """Belt and braces against local drift between listing and execution."""
    with Ctx(candidates=[CORK]) as c:
        await c.call()
        c.appts["a-cork"] = {**CORK, "provider_location_id": DUBLIN_PID}
        res = await c.call(ref="appt_1")
    assert c.cancel_calls == []
    assert "doesn't line up" in c.text(res)


# ── 24 & 25. caller identity ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_caller_phone_comes_from_telephony_metadata():
    with Ctx(candidates=[CORK]) as c, \
         patch("db.supabase.get_active_appointments_by_phone",
               new=AsyncMock(return_value=[CORK])) as lookup:
        await c.call()
    assert lookup.await_args.args[1] == PHONE


@pytest.mark.asyncio
async def test_a_model_supplied_phone_cannot_override_the_trusted_one():
    """The model claiming another caller's number must not select their
    appointments — metadata wins outright."""
    with Ctx(candidates=[CORK]) as c, \
         patch("db.supabase.get_active_appointments_by_phone",
               new=AsyncMock(return_value=[CORK])) as lookup:
        await c.call(args_extra={"caller_phone": OTHER_PHONE})
    assert lookup.await_args.args[1] == PHONE


# ── 26 & 27. lifecycle ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_of_call_cleanup_removes_appointment_refs():
    import inspect
    from routers import webhooks
    src = inspect.getsource(webhooks.vapi_call_ended)
    assert "_appt_refs.clear(call_id)" in src


@pytest.mark.asyncio
async def test_ttl_purge_removes_expired_refs():
    refs = Refs()
    with patch("db.appointment_refs.insert_refs", new=AsyncMock(side_effect=refs.insert_refs)), \
         patch("db.appointment_refs.count_refs", new=AsyncMock(side_effect=refs.count_refs)), \
         patch("db.appointment_refs.purge_expired_refs",
               new=AsyncMock(side_effect=refs.purge_expired_refs)):
        await ar.create_refs(vapi_call_id=CALL, tenant_id=TID,
                             caller_phone=PHONE, appointments=[CORK])
        refs.rows[(CALL, "appt_1")]["expires_at"] = "2020-01-01T00:00:00+00:00"
        assert await ar.purge_expired() == 1
    assert refs.rows == {}


def test_retention_reports_the_appointment_ref_purge():
    import inspect
    from services import retention
    src = inspect.getsource(retention.run_retention)
    assert "appointment_refs.purge_expired()" in src
    assert "call_appointment_refs_purged" in src


# ── 28. no limit(1) on the destructive path ──────────────────────────────────

def test_cancellation_never_uses_the_singular_limit1_lookup():
    """Enforced on executable code, not prose: the singular helper still exists for
    the non-destructive callers, but cancellation must never reach for it."""
    import ast
    import inspect
    for fn in (tools.cancel_appointment, tools._list_cancellable, tools._cancel_square_booking):
        tree = ast.parse(inspect.getsource(fn).lstrip())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                if node.body and isinstance(node.body[0], ast.Expr) \
                        and isinstance(node.body[0].value, ast.Constant):
                    node.body.pop(0)
        code = ast.unparse(tree)
        assert "get_active_appointment_by_phone" not in code, fn.__name__
        assert "limit(1)" not in code


def test_the_plural_lookup_applies_no_limit():
    """AST, not text: the docstring deliberately mentions .limit(1) to explain what
    it is NOT doing, and a substring check would fail on the explanation."""
    import ast
    import inspect
    from db import supabase as dbs
    tree = ast.parse(inspect.getsource(dbs.get_active_appointments_by_phone).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                node.body.pop(0)
    code = ast.unparse(tree)
    assert ".limit(" not in code
    assert "order('appointment_datetime', desc=False)" in code


# ── 29. the tool contract ────────────────────────────────────────────────────

def test_cancel_appointment_accepts_an_optional_appointment_ref():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "cancel_appointment")
    props = t["function"]["parameters"]["properties"]
    assert "appointment_ref" in props
    assert t["function"]["parameters"]["required"] == []
    desc = props["appointment_ref"]["description"].lower()
    assert "never invent" in desc and "never read one aloud" in desc


def test_cancel_appointment_takes_no_location_argument():
    """The ref is authoritative; a location argument would be a second, weaker
    way to say which appointment — and the two could disagree."""
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "cancel_appointment")
    props = t["function"]["parameters"]["properties"]
    assert set(props) == {"appointment_ref"}


def test_the_booking_tool_is_unchanged_by_w6a1():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "book_appointment")
    props = t["function"]["parameters"]["properties"]
    assert "slot_ref" in props and "location" not in props
    assert "appointment_ref" not in props
