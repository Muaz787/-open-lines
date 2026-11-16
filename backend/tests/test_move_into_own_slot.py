"""
Moving an appointment to a time that overlaps its own current slot.

16 Nov 2026: a caller with a 9:00-10:00 Square appointment asked for 9:30. Every
booking, including the one being moved, counted as busy, so 9:30 was never
offered and the assistant said it was unavailable.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from routers import tools
from services import self_overlap as so, square_booking as sb
from services import square_inplace_reschedule as sq_in
from tests import test_reschedule_all_providers as cal
from tests import test_square_deposit_reschedule as sqd
from tests import test_w6a2_d3_reschedule_tool as d3

TZ = ZoneInfo("America/Toronto")


def t(h, m=0, day=20):
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


# ═════════════════════════════ the coverage rule ═════════════════════════════

def test_nine_thirty_is_free_once_the_nine_oclock_moves():
    """Own slot 9-10 and Square's free 10-11 together cover 9:30-10:30."""
    free = [t(10), t(10, 30), t(11)]
    assert so.covered(t(9, 30), 60, t(9), 60, free, 60)
    assert so.extra_starts(own_start=t(9), minutes=60, free_starts=free,
                           not_before=t(8)) == [t(9, 30)]


def test_a_neighbouring_booking_still_blocks():
    """Someone else at 10:00-10:30: Square's first free start is 10:30, so
    nothing proves 10:00-10:30 free and 9:30 is NOT offered."""
    free = [t(10, 30), t(11), t(11, 30)]
    assert not so.covered(t(9, 30), 60, t(9), 60, free, 60)
    assert so.extra_starts(own_start=t(9), minutes=60, free_starts=free, not_before=t(8)) == []


def test_earlier_times_need_proof_of_the_time_before():
    free = [t(8), t(10), t(10, 30)]          # 8-9 free, own 9-10, 10-11 free
    got = so.extra_starts(own_start=t(9), minutes=60, free_starts=free, not_before=t(7))
    assert t(8, 30) in got and t(9, 30) in got
    # opening at 9: no window proves 8:30-9:00, so 8:30 is never offered
    assert t(8, 30) not in so.extra_starts(own_start=t(9), minutes=60,
                                           free_starts=[t(10)], not_before=t(7))


def test_never_the_current_time_never_the_past_never_another_day():
    free = [t(10), t(10, 30)]
    got = so.extra_starts(own_start=t(9), minutes=60, free_starts=free, not_before=t(9, 40))
    assert got == [], "9:30 is already past"
    late = so.extra_starts(own_start=t(23, 30), minutes=60,
                           free_starts=[t(0, 30, day=21)], not_before=t(7))
    assert all(x.date() == t(23, 30).date() for x in late)


@pytest.mark.parametrize("starts,want", [
    ([t(10), t(10, 30), t(11)], 30), ([t(10), t(10, 15), t(10, 30)], 15),
    ([t(10)], 30), ([t(10), t(12)], 30)])
def test_spacing_follows_squares_own_offers(starts, want):
    assert so.step_minutes(starts) == want


def test_overlap():
    assert so.overlaps(t(9, 30), 60, t(9), 60)
    assert not so.overlaps(t(10), 60, t(9), 60)
    assert not so.overlaps(t(8), 60, t(9), 60)


# ═══════════════════ Square: offering and re-checking the time ════════════════

def _booking(start=t(9), tm="TM-1"):
    return {"id": "BK-1", "status": "ACCEPTED", "location_id": "L1", "version": 2,
            "start_at": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "appointment_segments": [{"team_member_id": tm, "service_variation_id": "V1",
                                      "service_variation_version": 7, "duration_minutes": 60}]}


def _avail(*starts, tm="TM-1"):
    return [{"start_at": s.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
             "appointment_segments": [{"team_member_id": tm}]} for s in starts]


async def test_own_slot_extras_offers_nine_thirty_for_the_same_team_member():
    with patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("services.square_booking.get_booking_detailed",
                  new=AsyncMock(return_value=(sb.FETCH_FOUND, _booking()))), \
            patch("services.square_booking.search_availability",
                  new=AsyncMock(return_value=_avail(t(10), t(10, 30), t(11)))) as search, \
            patch("services.square_booking.datetime") as fake_dt:
        fake_dt.now.return_value = t(6).astimezone(timezone.utc)
        fake_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        fake_dt.fromisoformat = datetime.fromisoformat
        rows = await sb.own_slot_extras({"id": "x"}, booking_id="BK-1", date_str="2026-11-20",
                                        timezone="America/Toronto", provider_location_id="L1",
                                        service_variation_id="V1")
    assert [r["display"] for r in rows] == ["9:30 AM"]
    assert rows[0]["team_member_id"] == "TM-1" and rows[0]["duration_minutes"] == 60
    assert rows[0]["service_variation_version"] == 7
    assert search.await_args.args[3] == ["TM-1"], "only that team member's calendar"


@pytest.mark.parametrize("change", [
    {"location_id": "L-OTHER"}, {"status": "CANCELLED_BY_SELLER"},
    {"appointment_segments": [{"team_member_id": "TM-1", "service_variation_id": "V-OTHER",
                               "duration_minutes": 60}]}])
async def test_own_slot_extras_only_for_that_booking_service_and_place(change):
    with patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
            patch("services.square_booking.get_booking_detailed",
                  new=AsyncMock(return_value=(sb.FETCH_FOUND, {**_booking(), **change}))), \
            patch("services.square_booking.search_availability", new=AsyncMock()) as search:
        rows = await sb.own_slot_extras({"id": "x"}, booking_id="BK-1", date_str="2026-11-20",
                                        timezone="America/Toronto", provider_location_id="L1",
                                        service_variation_id="V1")
    assert rows == [] and search.await_count == 0


async def test_the_recheck_uses_a_fresh_read():
    with patch("services.square_booking.search_availability",
               new=AsyncMock(return_value=_avail(t(10), t(10, 30)))):
        assert await sb.free_once_moved("tok", location_id="L1", variation_id="V1",
                                        team_member_id="TM-1", own_start=t(9), minutes=60,
                                        target=t(9, 30))
    with patch("services.square_booking.search_availability",
               new=AsyncMock(return_value=_avail(t(10, 30)))):
        assert not await sb.free_once_moved("tok", location_id="L1", variation_id="V1",
                                            team_member_id="TM-1", own_start=t(9), minutes=60,
                                            target=t(9, 30))


# ═════════════ Square: the move itself goes in place (UpdateBooking) ═════════

@pytest.fixture
def no_test_window(monkeypatch, inplace_runs_store):
    for v in ("SQUARE_INPLACE_TEST_TENANT_ID", "SQUARE_INPLACE_TEST_LOCATION_ID",
              "SQUARE_INPLACE_TEST_CALLER_PHONE", "SQUARE_INPLACE_TEST_EXPIRES_AT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.delenv("SQUARE_DEPOSIT_MOVES", raising=False)
    inplace_runs_store.rows.clear()


HALF = sqd.SRC + timedelta(minutes=30)


@pytest.mark.parametrize("payments", [(), sqd.PAID], ids=["no deposit", "paid deposit"])
async def test_nine_to_nine_thirty_moves_the_booking_itself(payments, no_test_window,
                                                            calendar_moves_store):
    with sqd.SqWorld(payments=payments).env() as w, \
            patch("services.square_booking.free_once_moved", new=AsyncMock(return_value=True)) as fm:
        w.offer["start_at_utc"] = sqd.z(HALF)
        await w.call()
        said = await w.move()
    assert said.startswith("Done, re-read just now"), said
    assert len(w.updates) == 1 and w.updates[0][2] == sqd.z(HALF), "one UpdateBooking, to 9:30"
    assert w.booking["id"] == "BK-1" and w.appt["id"] == "a-1", "same booking, same row"
    assert fm.await_args.kwargs["team_member_id"] == sqd.TM, "re-checked for the same team member"


async def test_if_it_is_no_longer_free_nothing_moves(no_test_window, calendar_moves_store):
    with sqd.SqWorld().env() as w, \
            patch("services.square_booking.free_once_moved", new=AsyncMock(return_value=False)):
        w.offer["start_at_utc"] = sqd.z(HALF)
        await w.call()
        said = await w.move()
    assert said == sq_in._MESSAGES[sq_in.STAFF_UNAVAILABLE]
    assert w.updates == [] and not w.owners


async def test_if_square_refuses_the_overlap_nothing_changes(no_test_window, calendar_moves_store):
    """Square doesn't document whether UpdateBooking accepts a time overlapping the
    booking's own slot, and the sandbox can't write. A refusal must be harmless."""
    with sqd.SqWorld().env() as w, \
            patch("services.square_booking.free_once_moved", new=AsyncMock(return_value=True)):
        w.offer["start_at_utc"] = sqd.z(HALF)
        w.update_mode = "forbidden"
        await w.call()
        said = await w.move()
    assert w.updates == [] and not w.moved() and not w.owners
    assert "nothing" in said.lower() or "still" in said.lower(), said


async def test_a_time_clear_of_its_own_slot_still_uses_the_old_path(no_test_window,
                                                                    calendar_moves_store):
    from services import reschedule_intent as ri
    with sqd.SqWorld().env() as w, \
            patch("services.square_inplace_reschedule.move", new=AsyncMock()) as inplace, \
            patch("services.reschedule.begin_reschedule",
                  new=AsyncMock(side_effect=RuntimeError("old path"))):
        await w.call()
        await w.move()               # TARGET is 16:00, two hours after the 14:00 source
    inplace.assert_not_awaited()


# ═════════════════════ availability, with and without the ref ════════════════

async def test_square_availability_adds_own_slot_times_only_when_moving():
    tenant = {"id": sqd.TID, "square_location_id": "L1", "calendar_timezone": "America/Toronto"}
    services = [{"name": "Consultation — Regular", "square_variation_id": "V1",
                 "duration_minutes": 60, "team_member_ids": ["TM-1"]}]
    base = [{"start_at_utc": "2026-11-20T15:00:00Z", "display": "10:00 AM", "team_member_id": "TM-1",
             "duration_minutes": 60}]
    extra = [{"start_at_utc": "2026-11-20T14:30:00Z", "display": "9:30 AM", "team_member_id": "TM-1",
              "duration_minutes": 60, "own_slot": True}]
    made = {}

    async def offers(**kw):
        made["slots"] = [s["display"] for s in kw["slots"]]
        return [{"slot_ref": f"slot_{i}", "display": s["display"]} for i, s in enumerate(kw["slots"], 1)]

    async def run(args):
        with patch("db.supabase.get_square_services", new=AsyncMock(return_value=services)), \
                patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[])), \
                patch("services.square_booking.available_slots", new=AsyncMock(return_value=list(base))), \
                patch("services.square_booking.own_slot_extras", new=AsyncMock(return_value=extra)) as ex, \
                patch("routers.tools._moving_appointment",
                      new=AsyncMock(side_effect=lambda c, ti, ph, ref: (
                          {"id": "a-1", "google_event_id": "BK-1"} if ref == "appt_1" else None))), \
                patch("services.slot_offers.create_offers", new=AsyncMock(side_effect=offers)):
            res = await tools._square_availability_response(
                "tc", tenant, sqd.TID, {"_call_id": "c1", **args}, "2026-11-20", "", caller_phone="+1")
        return res["results"][0]["result"], ex

    said, ex = await run({"moving_appointment_ref": "appt_1"})
    assert made["slots"] == ["9:30 AM", "10:00 AM"] and "free once it moves" in said
    said, ex = await run({})
    assert made["slots"] == ["10:00 AM"] and ex.await_count == 0 and "free once it moves" not in said


@pytest.mark.parametrize("provider", cal.PROVIDERS)
async def test_google_and_outlook_ignore_only_the_named_appointment(provider):
    seen = []
    w = cal.CalWorld(provider)

    async def free(**kw):
        seen.append(kw.get("exclude_event_id"))
        return ["9:00 AM", "9:30 AM"]
    w.list_free = free

    async def availability(**args):
        body = {"message": {"toolCallList": [{"id": "tc", "function": {
            "name": "check_availability", "arguments": json.dumps(args)}}],
            "call": {"id": cal.CALL, "customer": {"number": cal.PHONE}}}}
        res = await tools.check_availability(d3._Req(), cal.TID, body)
        return res["results"][0]["result"]

    with w.env():
        await w.call()                                       # lists appt_1
        said_move = await availability(date="2026-11-04", moving_appointment_ref="appt_1")
        said_new = await availability(date="2026-11-04")
        said_bad = await availability(date="2026-11-04", moving_appointment_ref="appt_99")
    assert seen == ["EV-a-1", None, None]
    assert "free once it moves" in said_move and "free once it moves" not in said_new
    assert "free once it moves" not in said_bad


def test_the_tool_and_the_listing_tell_the_model_to_pass_the_ref():
    from services import vapi
    tools_ = vapi.build_calendar_tools("t", supports_reschedule=True)
    ca = next(x for x in tools_ if x.get("function", {}).get("name") == "check_availability")
    assert "moving_appointment_ref" in ca["function"]["parameters"]["properties"]
    import inspect
    assert "moving_appointment_ref" in inspect.getsource(tools._list_cancellable)


# ═════════ 16 Nov, second call: a webhook-stamped single location ═════════════
# Square's booking.created webhook stamps the business's one location on the
# appointment (tenant_location_id 809e1fca…, provider L0Q8…). Offers for a
# single-location business carry no tenant location, so every move was refused as
# "cross-location". The same booking, the same place.

def _stamp(w):
    w.appt["tenant_location_id"] = sqd.LOC_ID
    w.appt["provider_location_id"] = sqd.LOC_PID
    return w


@pytest.mark.parametrize("payments", [(), sqd.PAID], ids=["no deposit", "paid deposit"])
async def test_a_stamped_single_location_appointment_moves_to_nine_thirty(
        payments, no_test_window, calendar_moves_store):
    with _stamp(sqd.SqWorld(payments=payments)).env() as w, \
            patch("services.square_booking.free_once_moved", new=AsyncMock(return_value=True)):
        w.offer["start_at_utc"] = sqd.z(HALF)
        assert w.offer["tenant_location_id"] is None
        await w.call()
        said = await w.move()
    assert said.startswith("Done, re-read just now"), said
    assert len(w.updates) == 1 and w.updates[0][2] == sqd.z(HALF)


async def test_a_stamped_deposit_appointment_moves_to_any_time(no_test_window, calendar_moves_store):
    with _stamp(sqd.SqWorld(payments=sqd.PAID)).env() as w:
        await w.call()
        said = await w.move()
    assert said.startswith("Done, re-read just now"), said


async def test_a_stamped_appointment_reaches_the_ordinary_move(no_test_window, calendar_moves_store):
    """No deposit, not overlapping: precheck no longer says cross-location; the
    move reaches D1 (here stopped on purpose)."""
    from services import reschedule as rs
    with _stamp(sqd.SqWorld()).env() as w, \
            patch("services.reschedule.begin_reschedule",
                  new=AsyncMock(return_value=rs.Result(rs.NOT_ELIGIBLE))) as d1:
        await w.call()
        await w.move()
    d1.assert_awaited_once()


@pytest.mark.parametrize("case", ["multi-location", "other square location", "binding dead",
                                  "offer names a location", "no provider id"])
async def test_the_stamp_counts_only_for_the_one_live_location(case):
    from services import reschedule as rs
    tenant = {"square_appointments_enabled": True, "square_location_id": "L1"}
    offer = {"tenant_location_id": None, "provider_location_id": "L1"}
    src_pid, live, multi = "L1", True, False
    if case == "multi-location":
        multi = True
    elif case == "other square location":
        src_pid = "L2"
    elif case == "binding dead":
        live = False
    elif case == "offer names a location":
        offer["tenant_location_id"] = "loc-1"
    else:
        src_pid = ""
    with patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(multi, []))), \
            patch("services.reschedule._binding_is_live", new=AsyncMock(return_value=live)):
        assert not await rs.stamped_single_location(tenant, "t", "loc-1", src_pid, offer)
    with patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))), \
            patch("services.reschedule._binding_is_live", new=AsyncMock(return_value=True)):
        assert await rs.stamped_single_location(
            tenant, "t", "loc-1", "L1", {"tenant_location_id": None, "provider_location_id": "L1"})


def test_d1_normalises_the_stamp_before_its_location_gate():
    import inspect
    from services import reschedule as rs
    src = inspect.getsource(rs._under_ownership)
    assert src.index("stamped_single_location") < src.index("if not src_loc:")
