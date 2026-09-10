"""
W4.1 — the defects a real voice call exposed that no unit test had.

Call 01a08c5e-… ran 4m29s and never booked. Seven of nine check_availability
calls came back "Which service would you like at Cork?" because the multi-location
branch required a `service` argument that DID NOT EXIST in the tool schema. The
model could not answer; it escaped only by hallucinating an unsupported field. The
legacy branch had masked the same gap for years by silently falling back to
services[0] — the exact behaviour W4 was told to remove.

It also invented caller_phone "+00000000000", which the booking guard happened to
stop before it became a Square customer record.

These tests reproduce that call turn by turn.
"""
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import vapi

CORK_PID, DUBLIN_PID, LIMERICK_PID = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"


def _loc(slug, name, lid, pid, bookable=True):
    return {"id": lid, "slug": slug, "name": name, "aliases": [], "active": True,
            "booking_enabled": bookable, "timezone": "Europe/Dublin", "is_default": False,
            "_binding": {"tenant_location_id": lid, "provider": "square",
                         "provider_location_id": pid, "provider_status": "ACTIVE",
                         "provider_timezone": "America/Toronto"}}


CORK = _loc("cork", "Cork", "loc-cork", CORK_PID)
DUBLIN = _loc("dublin", "Dublin", "loc-dublin", DUBLIN_PID)
LIMERICK = _loc("limerick", "Limerick", "loc-lim", LIMERICK_PID)
ADOPTED = [CORK, DUBLIN, LIMERICK]

SERVICES = [
    {"square_variation_id": "V-FIT", "name": "Dress Fitting — Regular",
     "present_at_all_locations": False, "location_ids": [CORK_PID],
     "absent_location_ids": [], "team_member_ids": ["TM-MUAZ"], "duration_minutes": 60},
    {"square_variation_id": "V-CONS", "name": "Consultation (example service) — Regular",
     "present_at_all_locations": True, "location_ids": [], "absent_location_ids": [],
     "team_member_ids": ["TM-MUAZ"], "duration_minutes": 60},
]
STAFF = [{"square_team_member_id": "TM-MUAZ", "display_name": "Muaz Muhamed",
          "assigned_all_locations": True, "location_ids": []}]

TENANT = {"id": "t-dani", "business_name": "DANI Test — Internal",
          "square_appointments_enabled": True, "square_location_id": CORK_PID,
          "calendar_timezone": "America/Toronto"}


class _Ctx:
    def __init__(self, active=None, adopted=ADOPTED, services=SERVICES):
        self.state = {"vapi_call_id": "call-1", "tenant_id": "t-dani",
                      "active_location_id": active, "initial_location_id": active,
                      "switch_count": 0, "location_source": "caller_selected"}
        self.adopted = adopted
        self.services = services
        self.slots = AsyncMock(return_value=[
            {"start_at_utc": "2026-09-14T18:00:00Z", "display": "2:00 PM",
             "team_member_id": "TM-MUAZ", "service_variation_version": 1, "duration_minutes": 60},
            {"start_at_utc": "2026-09-14T18:30:00Z", "display": "2:30 PM",
             "team_member_id": "TM-MUAZ", "service_variation_version": 1, "duration_minutes": 60},
        ])

    def __enter__(self):
        self._p = [
            patch("db.supabase.get_square_services", new=AsyncMock(return_value=self.services)),
            patch("db.supabase.get_square_staff", new=AsyncMock(return_value=STAFF)),
            patch("services.call_location.get_or_create", new=AsyncMock(return_value=self.state)),
            patch("db.locations.update_call_state", new=AsyncMock()),
            patch("services.square_booking.available_slots", new=self.slots),
            patch("services.slot_offers.create_offers", new=AsyncMock(
                return_value=[{"slot_ref": "slot_1", "display": "2:00 PM"},
                              {"slot_ref": "slot_2", "display": "2:30 PM"}])),
            patch("services.call_location.set_active_service",
                  new=AsyncMock(side_effect=lambda st, svc: st)),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    async def run(self, **args):
        return await tools._multi_location_availability(
            "tc-1", TENANT, "t-dani", {"date": "2026-09-14", "_call_id": "call-1", **args},
            "2026-09-14", "", self.adopted)

    def called(self):
        return self.slots.await_count > 0

    def pid(self):
        return self.slots.await_args.kwargs["provider_location_id"]

    def variation(self):
        return self.slots.await_args.kwargs["service_variation_id"]

    def text(self, r):
        return r["results"][0]["result"]


# ── the schema gap itself ────────────────────────────────────────────────────

def test_check_availability_now_accepts_a_service():
    """The defect in one assertion: without this field the model literally could
    not answer the question the backend was asking it."""
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "check_availability")
    props = t["function"]["parameters"]["properties"]
    assert "service" in props
    assert "location" in props
    desc = props["service"]["description"].lower()
    assert "never invent" in desc and "identifier" in desc


def test_book_appointment_still_has_no_location_parameter():
    """W4.1 must not widen the booking surface."""
    t = next(x for x in vapi.build_calendar_tools("t1")
             if x["function"]["name"] == "book_appointment")
    assert "location" not in t["function"]["parameters"]["properties"]


# ── the real call, turn by turn ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_turn2_cork_plus_dress_fitting_queries_only_cork():
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork", service="dress fitting", period="any")
    assert ctx.called()
    assert ctx.pid() == CORK_PID
    assert ctx.variation() == "V-FIT"
    assert "Cork" in ctx.text(res)


@pytest.mark.asyncio
async def test_turn3_dress_fitting_at_dublin_refuses_without_substituting_consultation():
    with _Ctx(active="loc-cork") as ctx:
        res = await ctx.run(location="Dublin", service="dress fitting")
    assert not ctx.called()
    spoken = ctx.text(res)
    assert "Dublin" in spoken and "isn't offered" in spoken
    assert "2:00" not in spoken            # no Cork times leak


@pytest.mark.asyncio
async def test_turn4_consultation_at_dublin_uses_dublin():
    with _Ctx(active="loc-dublin") as ctx:
        await ctx.run(location="Dublin", service="consultation")
    assert ctx.pid() == DUBLIN_PID
    assert ctx.variation() == "V-CONS"


@pytest.mark.asyncio
async def test_turn5_booking_without_a_slot_ref_promises_nothing():
    body = {"message": {"toolCallList": [{"id": "tc-1", "function": {
        "name": "book_appointment", "arguments":
        '{"caller_name":"A","caller_phone":"+353871234567","service":"Dress Fitting",'
        '"date":"2026-09-14","time":"14:00"}'}}],
        "call": {"id": "call-1", "customer": {"number": "+353871234567"}}}}
    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=TENANT)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(True, ADOPTED))), \
         patch("routers.tools._square_book_appointment", new=AsyncMock()) as book, \
         patch("services.square_booking.create_booking", new=AsyncMock()) as create:
        out = await tools.book_appointment(_Req(), "t-dani", body)
    book.assert_not_awaited()
    create.assert_not_awaited()
    spoken = out["results"][0]["result"].lower()
    assert "check availability first" in spoken
    for word in ("confirmed", "held", "pending"):
        assert f"has been {word}" not in spoken


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}
    url = type("u", (), {"path": "/tools/x/book"})()


# ── no hidden fallbacks ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_service_with_several_available_asks_which():
    """Correct behaviour — but now the model has a field to answer with."""
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork")
    assert not ctx.called()
    assert "Which service" in ctx.text(res)


@pytest.mark.asyncio
async def test_no_service_with_exactly_one_available_proceeds():
    """Documented deliberately: with a single eligible service there is nothing to
    choose between, so this is determinism, not a fallback to an arbitrary first
    item. With two or more it always asks."""
    only_one = [SERVICES[0]]
    with _Ctx(services=only_one) as ctx:
        await ctx.run(location="Cork")
    assert ctx.called() and ctx.variation() == "V-FIT"


@pytest.mark.asyncio
async def test_unknown_service_clarifies_and_queries_nothing():
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork", service="bridal makeover")
    assert not ctx.called()
    assert "isn't offered" in ctx.text(res)


@pytest.mark.asyncio
async def test_service_is_never_silently_swapped_for_the_first_one():
    """The legacy _match_square_service returns services[0] on no match. The
    multi-location branch must never inherit that."""
    with _Ctx() as ctx:
        res = await ctx.run(location="Cork", service="something we do not do")
    assert not ctx.called()
    assert "Dress Fitting" not in ctx.text(res).split("There we do:")[0]


# ── caller identity ──────────────────────────────────────────────────────────

def test_call_metadata_beats_a_model_supplied_number():
    body = {"message": {"call": {"customer": {"number": "+353871234567"}}}}
    assert tools.trusted_caller_phone(body, {"caller_phone": "+353000000001"}) == "+353871234567"


@pytest.mark.parametrize("fake", ["+00000000000", "+10000000000", "0000000000",
                                  "+1234567890", "123", "+11111111111"])
def test_invented_numbers_are_discarded_when_metadata_is_absent(fake):
    """The rehearsal's actual value was +00000000000. Without metadata the model's
    guess must not become a customer record."""
    assert tools.trusted_caller_phone({"message": {}}, {"caller_phone": fake}) == ""


def test_a_real_number_is_still_accepted_when_metadata_is_absent():
    """Reschedules rely on this; the fix must not break them."""
    assert tools.trusted_caller_phone({"message": {}}, {"caller_phone": "+353871234567"}) \
        == "+353871234567"


def test_missing_everything_yields_empty_not_a_placeholder():
    assert tools.trusted_caller_phone({"message": {}}, {}) == ""


# ── the service menu the assistant sees ──────────────────────────────────────

@pytest.mark.asyncio
async def test_menu_is_grouped_by_location_and_names_only():
    from services import square_booking
    with patch("db.supabase.get_square_services", new=AsyncMock(return_value=SERVICES)), \
         patch("services.call_location.is_multi_location",
               new=AsyncMock(return_value=(True, ADOPTED))):
        block = await square_booking.service_menu_block(TENANT)

    assert "Cork: Consultation (example service), Dress Fitting" in block
    assert "Dublin: Consultation (example service)" in block
    assert "Dublin: Consultation (example service), Dress Fitting" not in block
    for leaked in (CORK_PID, DUBLIN_PID, "V-FIT", "V-CONS", "loc-cork", "variation"):
        assert leaked not in block


def test_variation_suffix_is_dropped_for_speech():
    from services import square_booking
    assert square_booking._display_service_name("Dress Fitting — Regular") == "Dress Fitting"
    assert square_booking._display_service_name("Consultation") == "Consultation"
    assert square_booking._display_service_name("") == ""


@pytest.mark.asyncio
async def test_non_square_tenant_gets_no_menu():
    from services import square_booking
    assert await square_booking.service_menu_block(
        {"id": "t-1", "square_appointments_enabled": False}) == ""
