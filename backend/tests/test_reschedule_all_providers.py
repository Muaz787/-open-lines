"""
Rescheduling across Google, Outlook and Square (single- and multi-location).

On 3 November a caller asked to move an appointment booked on an earlier call and
was told it couldn't be done. Each provider now moves appointments with its own
supported operation:

  Google / Outlook   the event is moved in place with one PATCH; the appointment
                     row, its id and anything linked to it stay as they were.
  Square             the existing W6A2 engine (replacement booking, then cancel),
                     now also for single-location businesses at their own location.

Matrix (every row is a test below):

  case                               Google  Outlook  Square-single  Square-multi
  success, earlier-call appointment    x       x          x              (W6A2 suite)
  unavailable slot / closed            x       x          x              (W6A2 suite)
  team member busy                     x       x          n/a: Square    n/a
  retry after success                  x       x          x              (W6A2 suite)
  concurrent requests                  x       x          x              x
  definite provider failure            x       x          x              (W6A2 suite)
  uncertain provider outcome           x       x          x              (W6A2 suite)
  provider moved, our row not          x       x          n/a            n/a
  deposit owed / paid                  kept    kept       refused        refused
  date contradicts caller's words      x       x          n/a: slot refs n/a
  appointment changed since listed     x       x          (W6A2 suite)   (W6A2 suite)
  wording and tools match capability   x       x          x              x
"""
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tests import test_w6a1_safe_cancellation as w6a1
from tests import test_w6a2_d3_reschedule_tool as d3
from routers import tools
from services import calendar_reschedule as cr, mutation_ownership, relative_dates, vapi
from services import reschedule_intent as ri

TID, CALL, PHONE = "t-ol", "call-now", "+16475550100"
NOW = datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc)          # 6 p.m. Monday, Toronto
SOURCE_UTC = "2026-11-04T14:00:00+00:00"                         # Wed 9:00 a.m.
TARGET_DATE, TARGET_TIME = "2026-11-05", "10:00"                 # Thu 10:00 a.m.
TARGET_UTC = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
PROVIDERS = ["google", "microsoft"]


def appointment(aid="a-1", *, when=SOURCE_UTC, status="confirmed", staff=None, call="call-earlier"):
    return {"id": aid, "tenant_id": TID, "caller_phone": PHONE, "caller_name": "Sam",
            "service": "Demo", "appointment_datetime": when, "duration_minutes": 60,
            "status": status, "google_event_id": f"EV-{aid}", "vapi_call_id": call,
            "staff_id": staff, "tenant_location_id": None, "provider_location_id": None}


class CalWorld:
    def __init__(self, provider, appts=None, *, free=None):
        self.provider = provider
        token = "microsoft_refresh_token" if provider == "microsoft" else "google_refresh_token"
        self.tenant = {"id": TID, "business_name": "Open Lines", token: "rt",
                       "calendar_timezone": "America/Toronto", "business_days": [0, 1, 2, 3, 4, 5, 6],
                       "business_hours_start": 9, "business_hours_end": 17,
                       "appointment_duration_minutes": 60, "slot_capacity": 1,
                       "twilio_subaccount_sid": "AC", "twilio_auth_token": "x",
                       "twilio_phone_number": "+14385550000"}
        self.appts = {a["id"]: dict(a) for a in (appts or [appointment()])}
        self.events = {a["google_event_id"]: a["appointment_datetime"] for a in self.appts.values()}
        self.free = free if free is not None else ["9:00 AM", "10:00 AM", "11:00 AM"]
        self.refs = w6a1.Refs()
        self.owners: dict[str, str] = {}
        self.patches, self.sms = [], []
        self.patch_error = None          # raised by the next patch
        self.patch_lands = False         # whether that failing patch moved the event anyway
        self.get_fails = False
        self.update_fails = False
        self.patch_delay = 0
        self.payment_calls = 0

    # db
    def active(self, *_):
        return [dict(a) for a in self.appts.values() if a["status"] in ("confirmed", "pending_payment")]

    async def get_appt(self, aid):
        return dict(self.appts[aid]) if aid in self.appts else None

    async def update_appt(self, aid, data):
        if self.update_fails:
            raise RuntimeError("write lost")
        self.appts[aid].update(data)

    async def payment(self, *_):
        self.payment_calls += 1
        return None

    # ownership (migration 021: one owner per appointment)
    async def acquire(self, aid, tid, op_id):
        if aid in self.owners:
            return mutation_ownership.BUSY, None
        self.owners[aid] = op_id
        return mutation_ownership.ACQUIRED, mutation_ownership.Claim(aid, op_id, "2026-11-02T23:00:00+00:00", "reschedule")

    async def release(self, claim):
        self.owners.pop(claim.appointment_id, None)
        return True

    async def release_raw(self, aid, token, claimed_at):
        if self.owners.get(aid) == token:
            self.owners.pop(aid)
            return True
        return False

    # provider
    async def list_free(self, **kw):
        return list(self.free)

    async def patch_event(self, rt, event_id, start_dt, duration, tz):
        if self.patch_delay:
            await asyncio.sleep(self.patch_delay)
        new = start_dt.astimezone(timezone.utc).isoformat()
        if self.patch_error is not None:
            err, self.patch_error = self.patch_error, None
            if self.patch_lands:
                self.events[event_id] = new
                self.patches.append((event_id, new))
            raise err
        self.events[event_id] = new
        self.patches.append((event_id, new))
        return {}

    async def get_event(self, rt, event_id):
        if self.get_fails:
            raise RuntimeError("calendar unreachable")
        if event_id not in self.events:
            return None
        start = datetime.fromisoformat(self.events[event_id])
        if self.provider == "microsoft":
            return {"start": {"dateTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000"),
                              "timeZone": "UTC"}}
        return {"status": "confirmed", "start": {"dateTime": start.isoformat()}}

    async def send_sms(self, **kw):
        self.sms.append(kw["body"])
        return True

    @contextlib.contextmanager
    def env(self):
        svc = "services.ms_calendar" if self.provider == "microsoft" else "services.calendar"
        ps = [
            patch.object(relative_dates, "_utcnow", lambda: NOW),
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
            patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=self.get_appt)),
            patch("db.supabase.update_appointment", new=AsyncMock(side_effect=self.update_appt)),
            patch("db.supabase.get_active_appointments_by_phone", new=AsyncMock(side_effect=self.active)),
            patch("db.supabase.get_active_appointments_between", new=AsyncMock(side_effect=self.active)),
            patch("db.supabase.get_active_staff", new=AsyncMock(return_value=[])),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(side_effect=self.payment)),
            patch("db.appointment_refs.insert_refs", new=AsyncMock(side_effect=self.refs.insert_refs)),
            patch("db.appointment_refs.count_refs", new=AsyncMock(side_effect=self.refs.count_refs)),
            patch("db.appointment_refs.get_ref", new=AsyncMock(side_effect=self.refs.get_ref)),
            patch("db.appointment_refs.consume_ref", new=AsyncMock(side_effect=self.refs.consume_ref)),
            patch("db.appointment_refs.release_ref", new=AsyncMock(side_effect=self.refs.release_ref)),
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))),
            patch("services.mutation_ownership.acquire_for_reschedule", new=AsyncMock(side_effect=self.acquire)),
            patch("services.mutation_ownership.release", new=AsyncMock(side_effect=self.release)),
            patch("db.mutation_claims.release_claim", new=AsyncMock(side_effect=self.release_raw)),
            patch(f"{svc}.list_free_slots", new=AsyncMock(side_effect=self.list_free)),
            patch(f"{svc}.patch_event", new=AsyncMock(side_effect=self.patch_event)),
            patch(f"{svc}.get_event", new=AsyncMock(side_effect=self.get_event)),
            patch("services.telephony.send_sms", new=AsyncMock(side_effect=self.send_sms)),
            patch("services.analytics.capture"),
        ]
        for p in ps:
            p.start()
        try:
            yield self
        finally:
            for p in ps:
                p.stop()

    async def call(self, **args):
        body = {"message": {"toolCallList": [{"id": "tc", "function": {
            "name": "reschedule_appointment", "arguments": json.dumps(args)}}],
            "call": {"id": CALL, "customer": {"number": PHONE}}}}
        res = await tools.reschedule_appointment(d3._Req(), TID, body)
        return res["results"][0]["result"]

    async def move(self, ref="appt_1", date=TARGET_DATE, time=TARGET_TIME, **extra):
        return await self.call(appointment_ref=ref, date=date, time=time, **extra)


def at(w, aid="a-1"):
    return datetime.fromisoformat(w.appts[aid]["appointment_datetime"].replace("Z", "+00:00"))


# ═══════════════════════════ Google and Outlook ═══════════════════════════════

@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_success_moves_an_earlier_calls_appointment_in_place(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        listed = await w.call()
        said = await w.move()
    assert "appt_1" in listed and "Wednesday, November 4 at 9:00 AM" in listed
    assert w.patches == [("EV-a-1", TARGET_UTC.isoformat())], "one PATCH of the same event"
    assert at(w) == TARGET_UTC and w.appts["a-1"]["status"] == "confirmed"
    assert w.appts["a-1"]["google_event_id"] == "EV-a-1", "same event, same row"
    assert said.startswith("Done, re-read just now") and "Thursday, November 5 at 10:00 AM" in said
    assert len(w.sms) == 1 and "moved to Thursday, November 5 at 10:00 AM" in w.sms[0]
    assert "(1 in total)" in said
    assert not w.owners, "ownership released"
    op = next(iter(calendar_moves_store.rows.values()))
    assert op["state"] == "completed"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_unavailable_time_moves_nothing(provider):
    with CalWorld(provider, free=["9:00 AM", "11:00 AM"]).env() as w:
        await w.call()
        said = await w.move()
    assert w.patches == [] and at(w) == datetime.fromisoformat(SOURCE_UTC)
    assert "isn't free" in said and "Nothing has been moved" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_outside_opening_hours_moves_nothing(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        said = await w.move(time="18:00")
    assert w.patches == [] and "not open" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_team_member_busy_moves_nothing(provider):
    busy = appointment("a-2", when=TARGET_UTC.isoformat(), staff="st-1")
    busy["caller_phone"] = "+19999999999"
    with CalWorld(provider, [appointment(staff="st-1"), busy]).env() as w:
        await w.call()
        said = await w.move()
    assert w.patches == [] and "isn't free" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_its_own_slot_does_not_block_a_small_move(provider):
    """9:00 to 9:30 on the same day overlaps itself; that must not count as busy."""
    with CalWorld(provider, free=["9:00 AM", "9:30 AM", "10:00 AM"]).env() as w:
        await w.call()
        said = await w.move(date="2026-11-04", time="09:30")
    assert said.startswith("Done") and len(w.patches) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_retry_after_success_moves_nothing_again(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        await w.move()
        again = await w.move()
    assert len(w.patches) == 1 and again.startswith("Already done, re-read just now")
    assert len(w.sms) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_concurrent_moves_send_one_patch(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.patch_delay = 0.01
        a, b = await asyncio.gather(w.move(), w.move(time="11:00"))
    assert len(w.patches) == 1
    assert sum(s.startswith("Done") for s in (a, b)) == 1
    # The loser is refused without a second PATCH: either the appointment is owned
    # right now, or the winner's operation is still unsettled.
    loser = a if b.startswith("Done") else b
    assert "being changed right now" in loser


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_definite_failure_keeps_the_original(provider, calendar_moves_store):
    req = httpx.Request("PATCH", "https://example.test")
    with CalWorld(provider).env() as w:
        await w.call()
        w.patch_error = httpx.HTTPStatusError("bad", request=req, response=httpx.Response(400, request=req))
        said = await w.move()
        retry = await w.move()
    assert "still on Wednesday, November 4 at 9:00 AM" in said
    assert retry.startswith("Done"), "a definite failure frees the appointment for a new attempt"
    assert sorted(op["state"] for op in calendar_moves_store.rows.values()) == ["completed", "failed"]


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_uncertain_outcome_that_landed_is_recognised(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        w.patch_error, w.patch_lands = httpx.ReadTimeout("timed out"), True
        said = await w.move()
    assert said.startswith("Done") and at(w) == TARGET_UTC and len(w.patches) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_unknown_outcome_holds_and_is_settled_by_reading(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.patch_error, w.get_fails = httpx.ReadTimeout("timed out"), True
        first = await w.move()
        again = await w.move()                     # still unknown: must not PATCH again
        assert w.patches == [] and "couldn't confirm" in first and "couldn't confirm" in again
        assert "a-1" in w.owners, "the appointment stays owned"
        # Later the calendar can be read: the move never landed. Recovery declares
        # it failed, releases the appointment, and a new attempt can run.
        w.get_fails = False
        later = NOW + timedelta(seconds=cr.STALE_SECONDS + 5)
        op = next(iter(calendar_moves_store.rows.values()))
        op["updated_at"] = (later - timedelta(seconds=cr.STALE_SECONDS + 1)).isoformat()
        with patch.object(cr, "datetime", wraps=datetime) as dt:
            dt.now.return_value = later
            settled = await cr.run_recovery()
        assert settled == {cr.FAILED: 1} and not w.owners
        final = await w.move()
    assert final.startswith("Done") and len(w.patches) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_provider_moved_but_our_row_not_is_finished_later(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.update_fails = True
        said = await w.move()
        assert "record hasn't caught up" in said and w.sms == []
        assert len(w.patches) == 1 and "a-1" in w.owners
        w.update_fails = False
        op = next(iter(calendar_moves_store.rows.values()))
        op["updated_at"] = (NOW - timedelta(hours=1)).isoformat()
        settled = await cr.run_recovery()
    assert settled == {cr.COMPLETED: 1} and at(w) == TARGET_UTC and not w.owners
    assert len(w.patches) == 1, "recovery never re-sends the move"


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("status", ["confirmed", "pending_payment"])
async def test_cal_deposit_status_is_kept_and_payments_are_never_touched(provider, status):
    with CalWorld(provider, [appointment(status=status)]).env() as w:
        await w.call()
        said = await w.move()
    assert said.startswith("Done")
    assert w.appts["a-1"]["status"] == status, "deposit-pending stays deposit-pending"
    assert w.payment_calls == 0, "no charge, no refund, no payment lookup at all"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_date_that_contradicts_the_callers_words_is_refused(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        said = await w.move(date="2026-11-05", date_phrase="the day after tomorrow")
    assert w.patches == [] and "2026-11-04" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_appointment_changed_since_it_was_listed(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        w.appts["a-1"]["appointment_datetime"] = "2026-11-04T16:00:00+00:00"   # moved elsewhere
        said = await w.move()
    assert w.patches == [] and "changed since I read it out" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_a_cancelled_appointment_is_not_moved(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        w.appts["a-1"]["status"] = "cancelled"
        said = await w.move()
    assert w.patches == [] and "isn't active" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_no_time_yet_asks_for_availability(provider):
    with CalWorld(provider).env() as w:
        await w.call()
        said = await w.call(appointment_ref="appt_1")
    assert w.patches == [] and "check_availability" in said


# ═══════════════════════════ Square, single-location ══════════════════════════

SINGLE_TENANT = {**d3.TENANT, "square_location_id": d3.CORK_PID}


@contextlib.contextmanager
def single_env(w, **kw):
    with patch.object(d3, "TENANT", SINGLE_TENANT), d3.env(w, **kw) as e, \
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))):
        yield e


def single_world(**appt_kw):
    src = d3.appt("a-single", loc=None, pid=None, **appt_kw)
    return d3.World([src], [d3.World.offer(None, "slot_1", loc=None, pid=d3.CORK_PID)])


async def test_square_single_success_moves_to_the_offered_slot():
    w = single_world()
    with single_env(w) as e:
        await d3.call()
        said = await d3.call("appt_1", "slot_1")
    assert said == ri.message_for(ri.COMPLETED)
    assert e["create"].await_count == 1 and w.created_bookings[0]["location_id"] == d3.CORK_PID
    assert w.cancelled_bookings == [d3.SRC_BOOKING]
    repl = await w.by_lineage("a-single")
    assert repl and repl["tenant_location_id"] is None and repl["provider_location_id"] == d3.CORK_PID


async def test_square_single_unavailable_slot_moves_nothing():
    w = single_world()
    with single_env(w, seg=None) as e:
        await d3.call()
        await d3.call("appt_1", "slot_1")
    assert e["create"].await_count == 0 and w.cancelled_bookings == []


async def test_square_single_retry_after_success_books_nothing_twice():
    w = single_world()
    with single_env(w) as e:
        await d3.call()
        await d3.call("appt_1", "slot_1")
        await d3.call("appt_1", "slot_1")
    assert e["create"].await_count == 1 and w.cancelled_bookings == [d3.SRC_BOOKING]


async def test_square_single_concurrent_requests_book_once():
    w = single_world()
    with single_env(w) as e:
        await d3.call()
        await asyncio.gather(d3.call("appt_1", "slot_1"), d3.call("appt_1", "slot_1"))
    assert e["create"].await_count == 1 and len(w.cancelled_bookings) == 1


async def test_square_single_provider_failure_keeps_the_original():
    w = single_world()
    from services import square_booking as sb
    with single_env(w, create=AsyncMock(side_effect=sb.BookingCreateRefused("400")
                                        if hasattr(sb, "BookingCreateRefused") else RuntimeError("400"))):
        await d3.call()
        await d3.call("appt_1", "slot_1")
    assert w.cancelled_bookings == [] and w.appts["a-single"]["status"] == "confirmed"


async def test_square_single_uncertain_outcome_stops():
    from services import square_booking as sb
    w = single_world()
    with single_env(w, create=AsyncMock(side_effect=sb.BookingOutcomeUnknown("timeout"))):
        await d3.call()
        said = await d3.call("appt_1", "slot_1")
    assert said == ri.message_for(ri.UNRESOLVED) and w.cancelled_bookings == []


async def test_square_single_offer_at_another_location_is_refused():
    w = d3.World([d3.appt("a-single", loc=None, pid=None)],
                 [d3.World.offer(None, "slot_1", loc=None, pid=d3.DUB_PID)])
    with single_env(w) as e:
        await d3.call()
        await d3.call("appt_1", "slot_1")
    assert e["create"].await_count == 0


async def test_square_single_location_rule_does_not_apply_to_multi_location_businesses():
    """A legacy row at a business that now has several locations stays refused."""
    w = d3.World([d3.appt("a-single", loc=None, pid=None)],
                 [d3.World.offer(None, "slot_1", loc=None, pid=d3.CORK_PID)])
    with patch.object(d3, "TENANT", SINGLE_TENANT), d3.env(w) as e:      # multi-location
        await d3.call()
        await d3.call("appt_1", "slot_1")
    assert e["create"].await_count == 0


# ═════════════════════ Square deposits: single and multi ══════════════════════

@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("deposit", ["paid", "owed"])
async def test_square_deposit_appointments_are_handed_to_the_team(multi, deposit):
    status = "pending_payment" if deposit == "owed" else "confirmed"
    if multi:
        w = d3.World([d3.appt("a-cork", status=status)])
        ctx = d3.env(w)
    else:
        w = single_world(status=status)
        ctx = single_env(w)
    payment = {"id": "p1", "status": "paid"} if deposit == "paid" else None
    with ctx as e, patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=payment)):
        await d3.call()
        said = await d3.call("appt_1", "slot_1")
    assert said == ri.message_for(ri.PAYMENT_ON_FILE)
    assert e["create"].await_count == 0 and w.cancelled_bookings == []


@pytest.mark.parametrize("multi", [False, True])
async def test_square_concurrent_requests_book_once(multi):
    w = d3.World() if multi else single_world()
    ctx = d3.env(w) if multi else single_env(w)
    with ctx as e:
        await d3.call()
        await asyncio.gather(*(d3.call("appt_1", "slot_1") for _ in range(3)))
    assert e["create"].await_count == 1


# ═════════════════ capability, tools and wording per account ══════════════════

@pytest.mark.parametrize("tenant, kind", [
    ({"google_refresh_token": "x"}, "calendar"),
    ({"microsoft_refresh_token": "x"}, "calendar"),
    ({"square_appointments_enabled": True, "square_location_id": "L1"}, "square"),
    ({"square_appointments_enabled": True, "google_refresh_token": "x"}, "square"),
    ({}, ""),
])
def test_each_account_gets_its_own_kind_of_move(tenant, kind):
    assert vapi.reschedule_kind(tenant) == kind


def test_calendar_accounts_get_a_date_and_time_schema():
    t = next(x for x in vapi.build_calendar_tools("t1", supports_reschedule=True, reschedule_kind="calendar")
             if x["function"]["name"] == "reschedule_appointment")
    assert set(t["function"]["parameters"]["properties"]) == {"appointment_ref", "date", "time", "date_phrase"}
    assert "slot_ref" not in json.dumps(t)


def test_square_accounts_keep_the_two_opaque_refs():
    t = next(x for x in vapi.build_calendar_tools("t1", supports_reschedule=True)
             if x["function"]["name"] == "reschedule_appointment")
    assert set(t["function"]["parameters"]["properties"]) == {"appointment_ref", "slot_ref"}


def test_the_wording_matches_the_tool():
    cal = vapi.caller_lookup_note(supports_reschedule=True, reschedule_kind="calendar")
    sq = vapi.caller_lookup_note(supports_reschedule=True)
    none = vapi.caller_lookup_note()
    assert "earlier one" in cal and "slot_ref" not in cal and "NOT SUPPORTED" not in cal
    assert "slot_ref" in sq and "NOT SUPPORTED" not in sq
    assert "NOT SUPPORTED" in none and "reschedule_appointment" not in none
    for note in (cal, sq):
        assert "never chain them" in note or "NEVER cancel an appointment as a way of moving it" in note
    assert "Changing the service is a new booking" in cal


def test_square_single_location_availability_records_offers():
    import inspect
    src = inspect.getsource(tools._square_availability_response)
    assert "slot_offers.create_offers(" in src and "available_slots(" in src
