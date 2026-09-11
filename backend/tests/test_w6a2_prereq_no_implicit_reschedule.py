"""
W6A2 prerequisite B — booking creates. It never cancels.

Two implicit-reschedule behaviours survived into production.

The live one was Google/Outlook: book_appointment looked up the caller's EARLIEST
active appointment (limit 1, no flag, no confirmation) and cancelled its calendar
event before creating the new one. A caller with two bookings who asked for a
third lost one of them silently, chosen by whichever happened to be sooner.

The dead one was the legacy Square path, gated on args.get("reschedule") — a
field no tool schema ever exposed, so it could not run. Dead destructive code is
its own hazard: the next person to add the argument would have shipped implicit
rescheduling without meaning to.

Both are gone. Moving an appointment will arrive as an explicit
reschedule_appointment(appointment_ref, slot_ref); until then it is simply not
offered, which is the safe interim state rather than the destructive one.
"""
import ast
import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools

TID, CALL, PHONE = "t-cal", "call-1", "+353871234567"


def _executable(fn):
    """Docstrings stripped: prose describing what a function does NOT do must not
    satisfy or fail a guard about what it does. This bit us three times in earlier
    workstreams."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant):
                node.body.pop(0)
    return ast.unparse(tree)


def _calls(fn):
    return [ast.unparse(n.func) for n in ast.walk(ast.parse(_executable(fn)))
            if isinstance(n, ast.Call)]


def appt(aid, when, event_id):
    return {"id": aid, "tenant_id": TID, "caller_phone": PHONE, "service": "Consultation",
            "appointment_datetime": when, "status": "confirmed", "google_event_id": event_id,
            "duration_minutes": 60}


EXISTING_1 = appt("a-1", "2026-10-01T13:00:00+00:00", "EV-1")
EXISTING_2 = appt("a-2", "2026-10-02T13:00:00+00:00", "EV-2")


class CalCtx:
    """Drives the real book_appointment against a calendar tenant."""

    def __init__(self, provider="google", existing=()):
        self.provider = provider
        self.existing = list(existing)
        self.cancelled = []
        self.created = []
        self.inserted = []
        self.updated = []
        token = ("microsoft_refresh_token" if provider == "microsoft"
                 else "google_refresh_token")
        self.tenant = {"id": TID, "business_name": "Cal Tenant", token: "rt",
                       "calendar_timezone": "Europe/Dublin", "appointment_duration_minutes": 60,
                       "slot_capacity": 5, "square_appointments_enabled": False,
                       "opening_hour": 0, "closing_hour": 23, "open_days": [0, 1, 2, 3, 4, 5, 6]}

    async def _cancel(self, rt, event_id):
        self.cancelled.append(event_id)

    async def _create(self, **kw):
        self.created.append(kw)
        return {"id": f"EV-NEW{len(self.created)}"}

    def __enter__(self):
        self._p = [
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))),
            patch("db.supabase.get_active_appointment_by_phone",
                  new=AsyncMock(return_value=self.existing[0] if self.existing else None)),
            patch("db.supabase.get_active_appointments_between",
                  new=AsyncMock(return_value=list(self.existing))),
            patch("db.supabase.get_active_staff", new=AsyncMock(return_value=[])),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=None)),
            patch("db.supabase.insert_appointment",
                  new=AsyncMock(side_effect=lambda d: (self.inserted.append(d), {"id": "new"})[1])),
            patch("db.supabase.update_appointment",
                  new=AsyncMock(side_effect=lambda i, d: self.updated.append((i, d)))),
            patch("db.supabase.update_tenant", new=AsyncMock()),
            patch("services.calendar.cancel_event", new=AsyncMock(side_effect=self._cancel)),
            patch("services.ms_calendar.cancel_event", new=AsyncMock(side_effect=self._cancel)),
            patch("services.calendar.create_event", new=AsyncMock(side_effect=self._create)),
            patch("services.ms_calendar.create_event", new=AsyncMock(side_effect=self._create)),
            patch("services.analytics.capture"),
            patch("routers.payments._deposit_provider", new=lambda t: None),
            patch("services.zapier.emit", new=AsyncMock()),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def book(self, time_str="15:00"):
        body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
            "name": "book_appointment", "arguments": json.dumps({
                "caller_name": "Aoife", "caller_phone": PHONE, "service": "Consultation",
                "date": "2026-10-05", "time": time_str})}}],
            "call": {"id": CALL, "customer": {"number": PHONE}}}}
        return await tools.book_appointment(_Req(), TID, body)


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}
    url = type("u", (), {"path": "/tools/x/book"})()


# ── 1-5. the live defect, per provider ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_a_booking_with_no_existing_appointment_creates_an_event(provider):
    with CalCtx(provider) as c:
        res = await c.book()
    assert len(c.created) == 1, res["results"][0]["result"][:300]
    assert c.cancelled == []
    assert len(c.inserted) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_a_booking_with_one_existing_appointment_cancels_nothing(provider):
    """The defect itself. Before this change the caller's existing event was
    cancelled first, with no flag and no confirmation."""
    with CalCtx(provider, existing=[EXISTING_1]) as c:
        await c.book()
    assert c.cancelled == [], f"{provider} booking cancelled {c.cancelled}"
    assert len(c.created) == 1, "and the new booking still happens"
    assert len(c.inserted) == 1, "as a NEW appointment row"
    assert c.updated == [], "never by overwriting the existing row"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_a_booking_with_several_existing_appointments_cancels_none(provider):
    """Two bookings and a limit(1) lookup is exactly how the wrong one got picked."""
    with CalCtx(provider, existing=[EXISTING_1, EXISTING_2]) as c:
        await c.book()
    assert c.cancelled == []
    assert len(c.inserted) == 1
    assert c.updated == []


@pytest.mark.asyncio
async def test_the_new_appointment_is_inserted_not_written_over_the_old_one():
    with CalCtx("google", existing=[EXISTING_1]) as c:
        await c.book()
    assert c.inserted[0]["google_event_id"] == "EV-NEW1"
    assert all(i != EXISTING_1["id"] for i, _ in c.updated)


# ── 6 & 7. static guards on the booking paths ────────────────────────────────

def test_the_ordinary_booking_path_cannot_call_cancel_event():
    calls = _calls(tools.book_appointment)
    for destructive in ("cal_svc.cancel_event", "ms_cal_svc.cancel_event",
                        "square_booking.cancel_booking", "square_booking.cancel_booking_detailed"):
        assert destructive not in calls, f"book_appointment must not call {destructive}"


def test_the_ordinary_booking_path_does_not_select_an_appointment_to_destroy():
    code = _executable(tools.book_appointment)
    assert "get_active_appointment_by_phone" not in code
    assert "existing_appt" not in code


def test_the_legacy_square_path_cannot_cancel_or_update():
    calls = _calls(tools._square_book_appointment)
    assert "square_booking.cancel_booking" not in calls
    assert "db.update_appointment" not in calls
    assert "db.insert_appointment" in calls


def test_no_executable_reschedule_flag_survives_in_any_booking_path():
    for fn in (tools.book_appointment, tools._square_book_appointment,
               tools._multi_location_book):
        code = _executable(fn)
        assert 'args.get(\'reschedule\')' not in code, fn.__name__
        assert 'args.get("reschedule")' not in code, fn.__name__


# ── 8 & 9. the other two providers are untouched ─────────────────────────────

def test_the_multi_location_path_is_unchanged_and_still_cancels_nothing():
    calls = _calls(tools._multi_location_book)
    for destructive in ("square_booking.cancel_booking", "cal_svc.cancel_event",
                        "ms_cal_svc.cancel_event", "db.update_appointment"):
        assert destructive not in calls
    assert "db.insert_appointment" in calls


def test_the_slot_claim_prerequisite_is_still_in_place():
    """Prerequisite A must survive Prerequisite B untouched."""
    src = inspect.getsource(tools._multi_location_book)
    assert src.index("slot_offers.claim(") < src.index("square_booking.create_booking(")
    assert "BookingOutcomeUnknown" in src


def test_w6a1_cancellation_helpers_are_untouched():
    """Deleting reschedule code must not take the explicit cancel path with it.

    C4 moved the provider half into services/appointment_cancellation so the
    refund path and the deferred-intent worker share one implementation; the tool
    now delegates. The property still worth pinning is that the cancel tool
    reaches a real provider cancellation, wherever that code lives.
    """
    calls = _calls(tools.cancel_appointment)
    assert "_cancel_square_booking" in calls
    sq = _calls(tools._cancel_square_booking)
    assert "appointment_cancellation.cancel_square_booking" in sq
    from services import appointment_cancellation
    assert "square_booking.cancel_booking_detailed" in _calls(
        appointment_cancellation.cancel_square_booking)


# ── 10. the tool contract ────────────────────────────────────────────────────

def test_book_appointment_exposes_no_reschedule_surface():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "book_appointment")
    props = t["function"]["parameters"]["properties"]
    for forbidden in ("reschedule", "appointment_ref", "existing_appointment", "cancel_existing"):
        assert forbidden not in props, f"book_appointment must not expose {forbidden}"


def test_book_appointment_still_carries_slot_ref_and_no_location():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "book_appointment")
    props = t["function"]["parameters"]["properties"]
    assert "slot_ref" in props and "location" not in props


def test_reschedule_appointment_now_exists_and_takes_only_opaque_refs():
    """Prereq B held the line until the engine existed. D3 opened it -- with the
    contract B was protecting: two opaque, call-scoped references and nothing
    else. No date, time, location, service, provider id or phone number."""
    from services import vapi
    tool = next(x for x in vapi.build_calendar_tools("t1", supports_reschedule=True)
                if x["function"]["name"] == "reschedule_appointment")
    props = tool["function"]["parameters"]["properties"]
    assert set(props) == {"appointment_ref", "slot_ref"}
    assert tool["function"]["parameters"]["required"] == []


# ── prompt truthfulness ──────────────────────────────────────────────────────

def test_the_prompt_no_longer_claims_booking_can_reschedule():
    from services import vapi
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "book_appointment")
    desc = t["function"]["description"].lower()
    assert "reschedule" not in desc
    assert "never moves, replaces or cancels" in desc


def test_the_prompt_no_longer_promises_the_backend_cancels_the_old_appointment():
    from services import vapi
    src = inspect.getsource(vapi)
    assert "The backend cancels the old appointment and creates the new one." not in src
    assert "book OR reschedule" not in src
    assert "new bookings AND reschedules" not in src


def test_the_prompt_tells_the_model_how_to_move_without_improvising():
    from services import vapi
    src = inspect.getsource(vapi)
    assert "MOVING AN EXISTING APPOINTMENT" in src
    assert "NEVER use it to move an existing one" in src
    # the enduring one: success may never be claimed ahead of the tool
    assert "NEVER say an appointment has been moved until the tool result says it is done" in src


def test_the_prompt_does_not_offer_cancel_then_book_as_a_way_to_move():
    """Cancel-then-book is the UNSAFE ordering, not a safe interim.

    Cancel succeeds, the replacement booking then fails or the slot disappears,
    and the caller is left with nothing. W6A2's whole lifecycle exists to create
    the replacement FIRST and cancel second. Offering the reverse sequence in the
    prompt would ship exactly the failure the workstream is being built to
    prevent — so the model must not be told to chain them at all.
    """
    from services import vapi
    src = inspect.getsource(vapi).lower()
    for workflow in ("offer to cancel it and book", "cancel then book", "cancel and rebook",
                     "cancel the old appointment before booking",
                     "cancel it and book a fresh time"):
        assert workflow not in src, f"prompt must not sequence cancellation into a rebooking: {workflow!r}"
    assert "never cancel an appointment as a way of moving it" in src
    assert "you must never chain them" in src


def test_the_prompt_keeps_booking_moving_and_cancelling_separate():
    from services import vapi
    src = inspect.getsource(vapi)
    assert "only ever creates a NEW appointment" in src
    # cross-location is still not emulated by cancel+rebook
    assert "do NOT cancel or rebook to fake it" in src
    # and the model is told not to improvise a recovery
    assert ("Do NOT call reschedule_appointment, book_appointment or "
            "cancel_appointment again to try to fix it") in src


# ── the availability self-exclusion remnant ──────────────────────────────────

def test_availability_no_longer_excludes_the_callers_own_appointment():
    """That exclusion only made sense while booking replaced the old appointment.
    It doesn't any more, so the slot is simply occupied — and advertising it would
    offer a time the booking path then refuses on capacity."""
    code = _executable(tools.check_availability)
    assert "get_active_appointment_by_phone" not in code
    assert "exclude_event_id" not in code
    assert "exclude_range" not in code


def test_availability_cancels_nothing():
    calls = _calls(tools.check_availability)
    for destructive in ("cal_svc.cancel_event", "ms_cal_svc.cancel_event",
                        "square_booking.cancel_booking", "db.update_appointment",
                        "db.insert_appointment"):
        assert destructive not in calls


def test_the_singular_lookup_is_gone_from_the_tools_router_entirely():
    import routers.tools as t
    src = ast.unparse(ast.parse(inspect.getsource(t)))
    assert "get_active_appointment_by_phone" not in src


def test_the_plural_cancellation_lookup_is_untouched():
    """W6A1 enumeration must survive: removing the singular lookup must not take
    the plural one with it."""
    from db import supabase as dbs
    assert hasattr(dbs, "get_active_appointments_by_phone")
    code = _executable(tools._list_cancellable)
    assert "get_active_appointments_by_phone" in code


@pytest.mark.asyncio
async def test_a_caller_holding_a_slot_is_not_offered_that_slot_back():
    """End to end: the caller's own 15:00 must count as busy like anyone else's."""
    seen = {}

    async def _slots(**kw):
        seen.update(kw)
        return ["3:00 PM", "3:30 PM"]

    own = appt("a-own", "2026-10-05T14:00:00+00:00", "EV-OWN")
    with CalCtx("google", existing=[own]) as c, \
         patch("services.calendar.list_free_slots", new=AsyncMock(side_effect=_slots)):
        body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
            "name": "check_availability", "arguments": json.dumps(
                {"date": "2026-10-05", "caller_phone": PHONE})}}],
            "call": {"id": CALL, "customer": {"number": PHONE}}}}
        await tools.check_availability(_Req(), TID, body)

    assert seen, "list_free_slots was not reached"
    assert "exclude_event_id" not in seen, "the caller's own event must not be excluded"
    assert "exclude_range" not in seen
    assert c.cancelled == []
