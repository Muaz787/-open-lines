"""
W5.1 — the Square query window that made every booking impossible.

resolve_slot() asked SearchAvailability for a 2-minute range. Square answers that
with 400 INVALID_TIME_RANGE, "Min query range is 1 hour." The exception was caught
and the function returned None, so BOTH booking paths — the new multi-location one
and the legacy single-location one — told every caller the time had just been taken.
It had been that way since the original Square Appointments commit, and no test
caught it because every test mocked resolve_slot or search_availability. Only a
real call to Square found it.

The fix widens the QUERY, not the MATCH. Square's hour is a floor imposed on the
request; it must never become permission to book a time, service, person or place
other than the one that was offered. Most of what follows tests that distinction.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from services import square_booking as sb

DUBLIN, CORK = "L9SA1AQ7XBM6K", "L0Q8GTAZCHD42"
VAR_CONS, VAR_FIT = "JWVLRYEEU3P5L3H6ZKVTDMOE", "V-FIT"
TM_A, TM_B = "TMYJ_qnlfeZkQ7nu", "TM-OTHER"


def _at(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 9, 14, h, m, tzinfo=timezone.utc)


def _avail(hhmm, *, location=DUBLIN, variation=VAR_CONS, team=TM_A, version=1789040442821):
    return {"start_at": _at(hhmm).isoformat().replace("+00:00", "Z"),
            "location_id": location,
            "appointment_segments": [{"team_member_id": team,
                                      "service_variation_id": variation,
                                      "service_variation_version": version,
                                      "duration_minutes": 60}]}


THREE_SLOTS = [_avail("13:00"), _avail("13:30"), _avail("14:00")]


async def _resolve(returns, at, *, location=DUBLIN, variation=VAR_CONS, team_ids=None):
    """Run the real resolve_slot against a scripted Square response. Returns the
    segment it chose and the spy, so a test can assert on the query as well as
    the answer."""
    spy = AsyncMock(return_value=returns)
    with patch("services.square_booking.search_availability", new=spy):
        out = await sb.resolve_slot("tok", location, variation,
                                    [TM_A] if team_ids is None else team_ids, _at(at))
    return out, spy


# ── 1. the defect itself ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_window_is_at_least_the_square_minimum_of_one_hour():
    """The whole bug in one assertion. Anything under an hour is a 400 and every
    booking fails closed."""
    _, spy = await _resolve(THREE_SLOTS, "13:00")
    start_iso, end_iso = spy.await_args.args[4], spy.await_args.args[5]
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    assert end - start >= timedelta(hours=1), f"{start_iso} -> {end_iso} is under Square's floor"


@pytest.mark.asyncio
async def test_the_window_starts_at_the_requested_time_not_before_it():
    """Widening backwards would ask Square about times already past."""
    _, spy = await _resolve(THREE_SLOTS, "13:00")
    assert spy.await_args.args[4] == "2026-09-14T13:00:00Z"


def test_the_window_is_a_named_constant_not_a_literal():
    assert sb.RESOLVE_QUERY_WINDOW_MINUTES >= 60


# ── 2 & 3. exact match, never nearest ────────────────────────────────────────

@pytest.mark.asyncio
async def test_exact_requested_start_is_selected_from_a_wider_result_set():
    """Square now returns 13:00, 13:30 and 14:00 for a 13:00 request. Only the
    first is ours; the other two are read and discarded."""
    seg, _ = await _resolve(THREE_SLOTS, "13:00")
    assert seg is not None
    assert seg["start_at"] == "2026-09-14T13:00:00Z"
    assert seg["team_member_id"] == TM_A
    assert seg["service_variation_version"] == 1789040442821
    assert seg["duration_minutes"] == 60


@pytest.mark.asyncio
async def test_a_time_square_does_not_offer_returns_none_not_the_nearest_slot():
    """13:15 requested, 13:00/13:30/14:00 available. Booking the nearest would put
    a caller in a chair fifteen minutes from when they agreed to arrive."""
    seg, _ = await _resolve(THREE_SLOTS, "13:15")
    assert seg is None


@pytest.mark.asyncio
async def test_no_first_result_fallback_when_the_exact_time_is_absent():
    """The wider window makes avails[0] a plausible-looking answer. It is not one."""
    seg, _ = await _resolve([_avail("13:30"), _avail("14:00")], "13:00")
    assert seg is None


@pytest.mark.asyncio
async def test_an_empty_result_set_is_still_none():
    seg, _ = await _resolve([], "13:00")
    assert seg is None


@pytest.mark.asyncio
async def test_a_square_error_still_fails_closed():
    with patch("services.square_booking.search_availability",
               new=AsyncMock(side_effect=RuntimeError("400 INVALID_TIME_RANGE"))):
        assert await sb.resolve_slot("tok", DUBLIN, VAR_CONS, [TM_A], _at("13:00")) is None


# ── 4. staff substitution ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_team_member_at_the_exact_time_returns_none():
    """A caller who asked for a named stylist must not be handed a different one
    because Square's response drifted from the filter we sent."""
    seg, _ = await _resolve([_avail("13:00", team=TM_B)], "13:00", team_ids=[TM_A])
    assert seg is None


@pytest.mark.asyncio
async def test_any_eligible_member_is_accepted_when_several_were_offered():
    """The 'when applicable' half: with no single member required, Square picking
    one from the list we sent is the intended behaviour, not a substitution."""
    seg, _ = await _resolve([_avail("13:00", team=TM_B)], "13:00", team_ids=[TM_A, TM_B])
    assert seg is not None and seg["team_member_id"] == TM_B


@pytest.mark.asyncio
async def test_a_segment_with_no_team_member_is_not_bookable():
    seg, _ = await _resolve([_avail("13:00", team=None)], "13:00", team_ids=[])
    assert seg is None


# ── 5. service substitution ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_service_variation_at_the_exact_time_returns_none():
    seg, _ = await _resolve([_avail("13:00", variation=VAR_FIT)], "13:00", variation=VAR_CONS)
    assert seg is None


@pytest.mark.asyncio
async def test_the_right_variation_later_in_the_window_does_not_rescue_a_wrong_one_now():
    """Mixed response: our variation exists, but only at a time we did not ask for."""
    seg, _ = await _resolve([_avail("13:00", variation=VAR_FIT), _avail("13:30")],
                            "13:00", variation=VAR_CONS)
    assert seg is None


# ── 6. location substitution ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_availability_from_another_location_is_rejected():
    """The one that matters for DANI: Cork's 13:00 must never satisfy a Dublin
    booking, however the payload arrived."""
    seg, _ = await _resolve([_avail("13:00", location=CORK)], "13:00", location=DUBLIN)
    assert seg is None


@pytest.mark.asyncio
async def test_the_location_we_query_is_the_location_we_were_given():
    _, spy = await _resolve(THREE_SLOTS, "13:00", location=DUBLIN)
    assert spy.await_args.args[1] == DUBLIN


@pytest.mark.asyncio
async def test_w5_booking_path_cannot_book_a_dublin_offer_while_the_call_is_on_cork():
    """End-to-end through _multi_location_book: the location lock refuses before
    resolve_slot or CreateBooking is reached, so the widened window is never even
    consulted for the wrong location."""
    from routers import tools
    from services import slot_offers

    offer = {"tenant_location_id": "loc-dublin", "provider_location_id": DUBLIN,
             "service_variation_id": VAR_CONS, "start_at_utc": "2026-09-14T13:00:00Z",
             "team_member_id": TM_A, "service_name": "Consultation"}
    adopted = [{"id": "loc-dublin", "name": "Dublin", "active": True, "booking_enabled": True},
               {"id": "loc-cork", "name": "Cork", "active": True, "booking_enabled": True}]

    with patch("services.call_location.get_or_create",
               new=AsyncMock(return_value={"vapi_call_id": "c1", "active_location_id": "loc-cork"})), \
         patch("services.slot_offers.resolve_for_booking",
               new=AsyncMock(return_value=(slot_offers.WRONG_LOCATION, offer))), \
         patch("services.square_booking.resolve_slot", new=AsyncMock()) as rs, \
         patch("services.square_booking.create_booking", new=AsyncMock()) as cb:
        out = await tools._multi_location_book(
            "tc-1", "c1", {"id": "t-dani"}, "t-dani", {"slot_ref": "slot_1"},
            caller_name="A", caller_phone="+353871234567", adopted=adopted)

    rs.assert_not_awaited()
    cb.assert_not_awaited()
    spoken = out["results"][0]["result"]
    assert "Dublin" in spoken and "Cork" in spoken


# ── 7. the legacy path still behaves as it did ───────────────────────────────

@pytest.mark.asyncio
async def test_legacy_full_roster_call_still_lets_square_pick_the_free_member():
    """The single-location path passes every team member it has when the caller
    named nobody. That must keep working exactly as before — this fix must not
    turn 'anyone' into 'nobody'."""
    seg, _ = await _resolve([_avail("13:00", team=TM_B)], "13:00", team_ids=[TM_A, TM_B])
    assert seg is not None and seg["team_member_id"] == TM_B


@pytest.mark.asyncio
async def test_legacy_named_staff_refusal_is_unchanged():
    """tools._square_book_appointment reads a falsy return as 'that person isn't
    free', which is still the message a caller should hear."""
    seg, _ = await _resolve([_avail("13:00", team=TM_B)], "13:00", team_ids=[TM_A])
    assert not (seg and seg.get("team_member_id"))


@pytest.mark.asyncio
async def test_availabilities_without_a_location_id_are_not_discarded():
    """Square omits fields it considers implied. Treating a missing location_id as
    a mismatch would break the legacy path for no gain."""
    a = _avail("13:00")
    a.pop("location_id")
    seg, _ = await _resolve([a], "13:00")
    assert seg is not None
