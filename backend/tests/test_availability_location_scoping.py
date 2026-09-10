"""
W4 — the caller-visible behaviour: location-scoped availability, and the booking
boundary that keeps multi-location booking shut until W5.

The assertion that recurs is "zero Square calls". Every fail-closed path is
verified not by what it says but by proving SearchAvailability was never reached —
a friendly message that still queried the wrong city would pass a wording check and
fail a caller.

Fixture mirrors the live Square test merchant:
    Dress Fitting  -> Cork only
    Consultation   -> all locations
    Aoife Test     -> Cork + Dublin
    Niamh Test     -> Cork only
    Muaz Muhamed   -> all current and future
"""
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools

CORK_PID, DUBLIN_PID, LIMERICK_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"


def _loc(slug, name, lid, bookable=True, active=True, tz="Europe/Dublin"):
    return {"id": lid, "slug": slug, "name": name, "aliases": [], "active": active,
            "booking_enabled": bookable, "timezone": tz, "is_default": False}


def _bind(lid, pid, status="ACTIVE", tz="Europe/Dublin"):
    return {"id": f"b-{lid}", "tenant_location_id": lid, "provider": "square",
            "provider_location_id": pid, "provider_status": status,
            "provider_timezone": tz}


CORK = {**_loc("cork", "Cork", "loc-cork"), "_binding": _bind("loc-cork", CORK_PID)}
DUBLIN = {**_loc("dublin", "Dublin", "loc-dublin"), "_binding": _bind("loc-dublin", DUBLIN_PID)}
LIMERICK = {**_loc("limerick", "Limerick", "loc-lim"), "_binding": _bind("loc-lim", LIMERICK_PID)}
ADOPTED = [CORK, DUBLIN, LIMERICK]

SERVICES = [
    {"square_variation_id": "V-FIT", "name": "Dress Fitting — Regular",
     "present_at_all_locations": False, "location_ids": [CORK_PID],
     "absent_location_ids": [], "team_member_ids": ["TM-MUAZ"], "duration_minutes": 60},
    {"square_variation_id": "V-CONS", "name": "Consultation — Regular",
     "present_at_all_locations": True, "location_ids": [], "absent_location_ids": [],
     "team_member_ids": ["TM-MUAZ"], "duration_minutes": 60},
]
STAFF = [
    {"square_team_member_id": "TM-MUAZ", "display_name": "Muaz Muhamed",
     "assigned_all_locations": True, "location_ids": []},
    {"square_team_member_id": "TM-AOIFE", "display_name": "Aoife Test",
     "assigned_all_locations": False, "location_ids": [CORK_PID, DUBLIN_PID]},
    {"square_team_member_id": "TM-NIAMH", "display_name": "Niamh Test",
     "assigned_all_locations": False, "location_ids": [CORK_PID]},
]

TENANT = {"id": "t-dani", "business_name": "DANI", "square_appointments_enabled": True,
          "square_location_id": CORK_PID, "calendar_timezone": "America/Toronto"}


def _args(**over):
    return {"date": "2026-09-12", "_call_id": "call-1", **over}


class _Ctx:
    """Everything the multi-location branch touches, stubbed. `slots` records every
    Square availability call so 'zero Square calls' is provable."""

    def __init__(self, state=None, adopted=ADOPTED):
        self.state = state or {"vapi_call_id": "call-1", "tenant_id": "t-dani",
                               "active_location_id": None, "initial_location_id": None,
                               "switch_count": 0, "location_source": "unknown"}
        self.adopted = adopted
        self.slots = AsyncMock(return_value=["2:30 PM", "4:00 PM"])

    def __enter__(self):
        self._p = [
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=SERVICES)),
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=STAFF)),
            patch("services.call_location.get_or_create",
                  new=AsyncMock(return_value=self.state)),
            patch("db.locations.update_call_state", new=AsyncMock()),
            patch("services.square_booking.available_slot_strings", new=self.slots),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def run(self, **args):
        return await tools._multi_location_availability(
            "tc-1", TENANT, "t-dani", _args(**args), "2026-09-12", "", self.adopted)

    def square_called(self):
        return self.slots.await_count > 0

    def location_used(self):
        return self.slots.await_args.kwargs["provider_location_id"]

    def text(self, res):
        return res["results"][0]["result"]


# ── the happy path ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caller_names_cork_and_gets_cork_availability():
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork", service="Dress Fitting")
    assert ctx.square_called()
    assert ctx.location_used() == CORK_PID
    assert "Cork" in ctx.text(res)


@pytest.mark.asyncio
async def test_success_response_names_the_location_back():
    """The caller's audible check that we heard the right city."""
    with _Ctx() as ctx:
        res = await ctx.run(location="the Cork shop", service="Consultation")
    assert "Cork has availability" in ctx.text(res)


@pytest.mark.asyncio
async def test_provider_ids_never_appear_in_what_the_assistant_is_told():
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork", service="Consultation")
    spoken = ctx.text(res)
    for pid in (CORK_PID, DUBLIN_PID, LIMERICK_PID, "loc-cork"):
        assert pid not in spoken


@pytest.mark.asyncio
async def test_the_location_timezone_beats_the_tenant_timezone():
    """DANI is Europe/Dublin. The tenant row still says America/Toronto and must
    not be consulted."""
    with _Ctx() as ctx:
        await ctx.run(location="Cork", service="Consultation")
    assert ctx.slots.await_args.kwargs["timezone"] == "Europe/Dublin"


@pytest.mark.asyncio
async def test_provider_timezone_is_the_fallback_when_the_location_has_none():
    cork = {**CORK, "timezone": None}
    with _Ctx(adopted=[cork, DUBLIN]) as ctx:
        await ctx.run(location="Cork", service="Consultation")
    assert ctx.slots.await_args.kwargs["timezone"] == "Europe/Dublin"


@pytest.mark.asyncio
async def test_no_silent_toronto_when_no_location_timezone_is_known():
    cork = {**CORK, "timezone": None, "_binding": _bind("loc-cork", CORK_PID, tz=None)}
    with _Ctx(adopted=[cork, DUBLIN]) as ctx:
        res = await ctx.run(location="Cork", service="Consultation")
    assert not ctx.square_called()
    assert "America/Toronto" not in ctx.text(res)


# ── fail closed: every one of these must make ZERO Square calls ──────────────

@pytest.mark.asyncio
async def test_no_location_means_no_square_request():
    with _Ctx() as ctx:
        res = await ctx.run(service="Dress Fitting")
    assert not ctx.square_called()
    assert "Cork, Dublin or Limerick" in ctx.text(res)


@pytest.mark.asyncio
async def test_unknown_location_asks_rather_than_guessing():
    with _Ctx() as ctx:
        res = await ctx.run(location="Galway", service="Consultation")
    assert not ctx.square_called()
    assert "Which location" in ctx.text(res) or "not sure which" in ctx.text(res)


@pytest.mark.asyncio
async def test_service_not_offered_at_that_location_never_reaches_square():
    """The DANI scenario: Dress Fitting is Cork-only. Asking for it in Dublin must
    be answered from our own data, with no Cork result leaking in."""
    with _Ctx() as ctx:
        res = await ctx.run(location="Dublin", service="Dress Fitting")
    assert not ctx.square_called()
    spoken = ctx.text(res)
    assert "Dublin" in spoken and "isn't offered" in spoken
    assert "2:30" not in spoken


@pytest.mark.asyncio
async def test_staff_not_assigned_there_never_reaches_square():
    with _Ctx() as ctx:
        res = await ctx.run(location="Dublin", service="Consultation", staff="Niamh Test")
    assert not ctx.square_called()
    assert "Niamh Test isn't available at Dublin" in ctx.text(res)


@pytest.mark.asyncio
async def test_staff_assigned_to_both_locations_is_accepted_at_either():
    for loc, pid in (("Cork", CORK_PID), ("Dublin", DUBLIN_PID)):
        with _Ctx() as ctx:
            await ctx.run(location=loc, service="Consultation", staff="Aoife Test")
        assert ctx.square_called() and ctx.location_used() == pid


@pytest.mark.asyncio
async def test_all_locations_staff_works_at_limerick():
    with _Ctx() as ctx:
        await ctx.run(location="Limerick", service="Consultation", staff="Muaz Muhamed")
    assert ctx.location_used() == LIMERICK_PID


@pytest.mark.asyncio
async def test_missing_binding_never_reaches_square():
    broken = {**DUBLIN, "_binding": _bind("loc-dublin", DUBLIN_PID, status="MISSING")}
    broken["_binding"]["provider_location_id"] = ""
    with _Ctx(adopted=[CORK, broken]) as ctx:
        res = await ctx.run(location="Dublin", service="Consultation")
    assert not ctx.square_called()


@pytest.mark.asyncio
async def test_disabled_location_is_not_offered_and_cannot_be_chosen():
    disabled = {**DUBLIN, "booking_enabled": False}
    with _Ctx(adopted=[CORK, disabled, LIMERICK]) as ctx:
        res = await ctx.run(location="Dublin", service="Consultation")
    assert not ctx.square_called()
    assert "Dublin" not in ctx.text(res).replace("Dublin?", "")   # not offered as an option


@pytest.mark.asyncio
async def test_no_bookable_locations_at_all_fails_closed():
    none_bookable = [{**l, "booking_enabled": False} for l in ADOPTED]
    with _Ctx(adopted=none_bookable) as ctx:
        res = await ctx.run(location="Cork", service="Consultation")
    assert not ctx.square_called()


@pytest.mark.asyncio
async def test_missing_call_id_fails_closed_with_no_anonymous_state():
    with _Ctx() as ctx:
        res = await tools._multi_location_availability(
            "tc-1", TENANT, "t-dani", {"date": "2026-09-12", "_call_id": ""},
            "2026-09-12", "", ADOPTED)
    assert not ctx.square_called()


@pytest.mark.asyncio
async def test_a_provider_id_supplied_as_the_location_is_refused():
    """The model must never be able to steer Square directly."""
    with _Ctx() as ctx:
        res = await ctx.run(location=CORK_PID, service="Consultation")
    assert not ctx.square_called()


# ── switching ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_switching_cork_to_dublin_changes_the_provider_id_used():
    with _Ctx() as ctx:
        await ctx.run(location="Cork", service="Consultation")
        assert ctx.location_used() == CORK_PID
    with _Ctx(state={"vapi_call_id": "call-1", "tenant_id": "t-dani",
                     "active_location_id": "loc-cork", "initial_location_id": "loc-cork",
                     "switch_count": 0, "location_source": "caller_selected"}) as ctx2:
        await ctx2.run(location="Dublin", service="Consultation")
        assert ctx2.location_used() == DUBLIN_PID


@pytest.mark.asyncio
async def test_established_state_is_reused_without_re_asking():
    with _Ctx(state={"vapi_call_id": "call-1", "tenant_id": "t-dani",
                     "active_location_id": "loc-cork", "initial_location_id": "loc-cork",
                     "switch_count": 0, "location_source": "caller_selected"}) as ctx:
        await ctx.run(service="Consultation")
    assert ctx.square_called() and ctx.location_used() == CORK_PID


# ── legacy path untouched ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_location_tenant_takes_the_legacy_branch():
    """No location question, no new state, legacy pointer still used."""
    body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
        "name": "check_availability", "arguments": '{"date": "2026-09-12"}'}}],
        "call": {"id": "call-legacy"}}}
    legacy = AsyncMock(return_value={"results": [{"toolCallId": "tc-1", "result": "legacy"}]})
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=TENANT)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(False, []))), \
         patch("routers.tools._square_availability_response", new=legacy), \
         patch("routers.tools._multi_location_availability", new=AsyncMock()) as multi, \
         patch("services.call_location.get_or_create", new=AsyncMock()) as create:
        out = await tools.check_availability(_FakeReq(), "t-1", body)
    legacy.assert_awaited_once()
    multi.assert_not_awaited()
    create.assert_not_awaited()
    assert out["results"][0]["result"] == "legacy"


class _FakeReq:
    """slowapi's limiter is stubbed in conftest; the handler only needs .client."""
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}
    url = type("u", (), {"path": "/tools/x/availability"})()


# ── the booking boundary ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_location_booking_is_blocked_with_zero_create_booking_calls():
    """The tool stays exposed on the assistant, so 'we did not modify booking' is
    not a safeguard. This guard is."""
    body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
        "name": "book_appointment", "arguments":
        '{"caller_name":"A","caller_phone":"+353871234567","service":"Consultation",'
        '"date":"2026-09-12","time":"14:00"}'}}], "call": {"id": "call-1"}}}
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=TENANT)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(True, ADOPTED))), \
         patch("routers.tools._square_book_appointment", new=AsyncMock()) as book, \
         patch("services.square_booking.create_booking", new=AsyncMock()) as create:
        out = await tools.book_appointment(_FakeReq(), "t-dani", body)

    book.assert_not_awaited()
    create.assert_not_awaited()
    assert "not able to complete the booking" in out["results"][0]["result"]


@pytest.mark.asyncio
async def test_single_location_booking_is_untouched_by_the_guard():
    body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
        "name": "book_appointment", "arguments":
        '{"caller_name":"A","caller_phone":"+16475551234","service":"Cut",'
        '"date":"2026-09-12","time":"14:00"}'}}], "call": {"id": "call-2"}}}
    booked = AsyncMock(return_value={"results": [{"toolCallId": "tc-1", "result": "booked"}]})
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=TENANT)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(False, []))), \
         patch("routers.tools._square_book_appointment", new=booked):
        out = await tools.book_appointment(_FakeReq(), "t-1", body)
    booked.assert_awaited_once()
    assert out["results"][0]["result"] == "booked"


# ── structural guards ────────────────────────────────────────────────────────

def test_the_multi_location_branch_cannot_reach_the_legacy_pointer():
    """Not a global ban: single-location compatibility still uses the pointer on
    purpose. This pins the NEW branch only."""
    import ast
    import inspect

    fn = ast.parse(inspect.getsource(tools._multi_location_availability)).body[0]
    # Executable code only — the docstring names the things it must never touch.
    code = "\n".join(ast.unparse(n) for n in fn.body if not isinstance(n, ast.Expr))
    assert "square_location_id" not in code
    assert "is_default" not in code
    assert "locations[0]" not in code


def test_the_legacy_pointer_is_still_used_somewhere_on_purpose():
    """Guards the opposite mistake: ripping out compatibility while W4 still needs
    single-location tenants to work exactly as before."""
    import inspect
    assert "square_location_id" in inspect.getsource(tools._square_book_appointment)
