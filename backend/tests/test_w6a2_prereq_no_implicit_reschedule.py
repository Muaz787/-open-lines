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
    """Deleting reschedule code must not take the explicit cancel path with it."""
    calls = _calls(tools.cancel_appointment)
    assert "_cancel_square_booking" in calls
    sq = _calls(tools._cancel_square_booking)
    assert "square_booking.cancel_booking_detailed" in sq


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


def test_reschedule_appointment_does_not_exist_yet():
    from services import vapi
    names = {x["function"]["name"] for x in vapi.build_calendar_tools("t1")}
    assert "reschedule_appointment" not in names


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


def test_the_prompt_tells_the_model_moving_is_unsupported_rather_than_silent():
    from services import vapi
    src = inspect.getsource(vapi)
    assert "MOVING AN EXISTING APPOINTMENT" in src
    assert "It does NOT move or replace an existing one" in src
    assert "Never tell a caller their appointment has been moved" in src
