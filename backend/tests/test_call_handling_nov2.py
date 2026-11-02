"""
The 2 November call, and what it showed.

At 6:05 p.m. on Monday 2 November (Toronto) a returning caller asked for a demo
"the day after tomorrow". The model passed 2026-11-05 and booked it. The caller
corrected it to the 4th, and the model booked that as a second appointment. It
then told the caller it couldn't cancel, cancelled the 5th anyway, and said "you
now have only the November 4 demo" while a booking on the 3rd, from an earlier
call, was still in place. Every confirmation promised a text before anyone knew
whether one had gone.

Each test below pins one of those down:
  * the day is worked out by the server, from the call time in the tenant's zone;
  * a correction swaps the booking, new first and old second, and a retry
    changes nothing;
  * what is still booked is re-read, never assumed;
  * the wording matches what the assistant can actually do;
  * a text is mentioned only when one was sent.
"""
import asyncio
import inspect
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import calendar as calendar_router, tools
from services import mutation_ownership, relative_dates, vapi

TID, CALL, PHONE = "t-ol", "call-nov2", "+16475550100"
OTHER_CALL = "call-morning"
TZ = "America/Toronto"
NOW = datetime(2026, 11, 2, 23, 5, tzinfo=timezone.utc)      # 6:05 p.m. Monday in Toronto
MON = date(2026, 11, 2)


def appt(aid, when_utc, *, call=CALL, status="confirmed", event=None, svc="demo", **kw):
    return {"id": aid, "tenant_id": TID, "caller_phone": PHONE, "caller_name": "Sam",
            "service": svc, "appointment_datetime": when_utc, "duration_minutes": 60,
            "status": status, "vapi_call_id": call, "google_event_id": event or f"EV-{aid}", **kw}


# Toronto is UTC-5 after 1 November 2026, so 9 a.m. local is 14:00 UTC.
NOV3_EARLIER_CALL = appt("a-nov3", "2026-11-03T14:15:00+00:00", call=OTHER_CALL)
NOV5_THIS_CALL = appt("a-nov5", "2026-11-05T14:00:00+00:00")
NOV4_THIS_CALL = appt("a-nov4", "2026-11-04T14:00:00+00:00")


class Cal:
    """Drives the real tool endpoints against a Google calendar tenant."""

    def __init__(self, appts=(), *, now=NOW, sms_ok=True, twilio=True, create_fails=False,
                 cancel_fails=False, deposit=None, provider="google", tz=TZ):
        self.appts = {a["id"]: dict(a) for a in appts}
        self.now = now
        self.sms_ok, self.create_fails, self.cancel_fails = sms_ok, create_fails, cancel_fails
        self.deposit = deposit
        self.created, self.cancelled, self.sms, self.slot_dates = [], [], [], []
        self.events: dict[str, dict] = {}        # the calendar, by event id
        self.create_error = None                 # raised by the next create, after or before it lands
        self.create_lands = False                # whether that failing create made the event anyway
        self.get_event_fails = False
        self.update_fails_for = set()            # appointment ids whose status write fails
        self.insert_fails = 0                    # how many inserts fail before one succeeds
        self.held = set()                        # appointments held for reconciliation
        self.lookup_fails = False
        self.create_delay = 0
        token = "microsoft_refresh_token" if provider == "microsoft" else "google_refresh_token"
        self.tenant = {"id": TID, "business_name": "Open Lines", token: "rt",
                       "calendar_timezone": tz, "appointment_duration_minutes": 60,
                       "slot_capacity": 5, "square_appointments_enabled": False,
                       "business_days": [0, 1, 2, 3, 4, 5, 6],
                       "business_hours_start": 9, "business_hours_end": 21}
        if twilio:
            self.tenant.update(twilio_subaccount_sid="AC1", twilio_auth_token="x",
                               twilio_phone_number="+14385550000")

    def active(self, *_):
        if self.lookup_fails:
            raise RuntimeError("database unavailable")
        return [dict(a) for a in self.appts.values()
                if a["status"] in ("confirmed", "pending_payment") and a["caller_phone"] == PHONE]

    async def _insert(self, data):
        if self.insert_fails:
            self.insert_fails -= 1
            raise RuntimeError("insert lost")
        aid = f"new-{len(self.appts)}"
        self.appts[aid] = {"id": aid, **data}
        return {"id": aid}

    async def _update(self, aid, data):
        if aid in self.update_fails_for:
            raise RuntimeError("write lost")
        self.appts[aid] = {**self.appts[aid], **data}
        return {}

    async def _create(self, **kw):
        if self.create_delay:
            await asyncio.sleep(self.create_delay)
        if self.create_fails:
            raise RuntimeError("calendar down")
        eid = kw.get("event_id") or kw.get("transaction_id") or f"EV-NEW{len(self.created) + 1}"
        if eid in self.events:                   # Google's 409 / Graph's transactionId
            return {"id": eid}
        if self.create_error is not None:
            err, self.create_error = self.create_error, None
            if self.create_lands:
                self.events[eid] = {"status": "confirmed"}
                self.created.append(kw)
            raise err
        self.events[eid] = {"status": "confirmed"}
        self.created.append(kw)
        return {"id": eid}

    async def _get_event(self, rt, eid):
        if self.get_event_fails:
            raise RuntimeError("calendar unreachable")
        return self.events.get(eid)

    async def _acquire(self, aid, tid):
        if aid in self.held:
            return mutation_ownership.BUSY, None
        return mutation_ownership.ACQUIRED, {"appointment_id": aid}

    async def _to_reconcile(self, claim, reason):
        self.held.add(claim["appointment_id"])
        return True

    async def _cancel(self, rt, event_id):
        if self.cancel_fails:
            raise RuntimeError("calendar down")
        self.cancelled.append(event_id)
        if event_id in self.events:
            self.events[event_id]["status"] = "cancelled"

    async def _slots(self, **kw):
        self.slot_dates.append(kw["date_str"])
        return ["9:00 AM", "9:15 AM"]

    async def _sms(self, **kw):
        self.sms.append(kw["body"])
        return self.sms_ok

    def __enter__(self):
        self._p = [
            patch.object(relative_dates, "_utcnow", lambda: self.now),
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
            patch("services.call_location.is_multi_location", new=AsyncMock(return_value=(False, []))),
            patch("db.supabase.get_active_appointments_by_phone", new=AsyncMock(side_effect=self.active)),
            patch("db.supabase.get_active_appointments_between", new=AsyncMock(side_effect=self.active)),
            patch("db.supabase.get_active_staff", new=AsyncMock(return_value=[])),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=None)),
            patch("db.supabase.insert_appointment", new=AsyncMock(side_effect=self._insert)),
            patch("db.supabase.update_appointment", new=AsyncMock(side_effect=self._update)),
            patch("db.supabase.get_appointment_by_id",
                  new=AsyncMock(side_effect=lambda aid: dict(self.appts[aid]) if aid in self.appts else None)),
            patch("db.supabase.update_tenant", new=AsyncMock()),
            patch("services.calendar.create_event", new=AsyncMock(side_effect=self._create)),
            patch("services.ms_calendar.create_event", new=AsyncMock(side_effect=self._create)),
            patch("services.calendar.cancel_event", new=AsyncMock(side_effect=self._cancel)),
            patch("services.ms_calendar.cancel_event", new=AsyncMock(side_effect=self._cancel)),
            patch("services.calendar.list_free_slots", new=AsyncMock(side_effect=self._slots)),
            patch("services.telephony.send_sms", new=AsyncMock(side_effect=self._sms)),
            patch("services.analytics.capture"),
            patch("services.zapier.emit", new=AsyncMock()),
            patch("routers.payments._deposit_provider", new=lambda t: self.deposit),
            patch("routers.tools._trusted_caller_name", new=AsyncMock(return_value="Sam")),
            patch("services.mutation_ownership.acquire_for_cancel", new=AsyncMock(side_effect=self._acquire)),
            patch("services.mutation_ownership.release", new=AsyncMock(return_value=True)),
            patch("services.mutation_ownership.to_reconcile", new=AsyncMock(side_effect=self._to_reconcile)),
            patch("services.calendar.get_event", new=AsyncMock(side_effect=self._get_event)),
            patch("db.supabase.get_appointment_by_event_id", new=AsyncMock(
                side_effect=lambda tid, eid: next((dict(a) for a in self.appts.values()
                                                   if a.get("google_event_id") == eid), None))),
            patch("services.refunds.sms_caller_cancelled", new=AsyncMock()),
            patch("services.refunds.notify_business", new=AsyncMock()),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    @staticmethod
    def _body(name, args, call_id=CALL):
        return {"message": {"toolCallList": [{"id": "tc-1", "function": {
            "name": name, "arguments": json.dumps(args)}}],
            "call": {"id": call_id, "customer": {"number": PHONE}}}}

    async def availability(self, **args):
        res = await tools.check_availability(_Req(), TID, self._body("check_availability", args))
        return res["results"][0]["result"]

    async def book(self, date_str, time_str="09:00", **extra):
        args = {"caller_name": "Sam", "caller_phone": PHONE, "service": "demo",
                "date": date_str, "time": time_str, **extra}
        res = await tools.book_appointment(_Req(), TID, self._body("book_appointment", args))
        return res["results"][0]["result"]

    async def replace(self, date_str, time_str="09:00", **extra):
        res = await tools.replace_booking(
            _Req(), TID, self._body("replace_booking", {"date": date_str, "time": time_str, **extra}))
        return res["results"][0]["result"]

    def status(self, aid):
        return self.appts[aid]["status"]

    def bookings_from_this_call(self):
        return sorted(a["appointment_datetime"] for a in self.active() if a.get("vapi_call_id") == CALL)


class _Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}
    url = type("u", (), {"path": "/tools/x"})()


# ── 1. relative dates are resolved by the server ─────────────────────────────

@pytest.mark.parametrize("phrase, expected", [
    ("today", MON),
    ("tomorrow", date(2026, 11, 3)),
    ("the day after tomorrow", date(2026, 11, 4)),
    ("Day after tomorrow, please", date(2026, 11, 4)),
    ("in two days", date(2026, 11, 4)),
    ("Thursday", date(2026, 11, 5)),
    ("this Wednesday", date(2026, 11, 4)),
    ("tomorrow morning", date(2026, 11, 3)),
])
def test_phrases_with_one_reading_resolve(phrase, expected):
    assert relative_dates.resolve_phrase(phrase, MON) == expected


@pytest.mark.parametrize("phrase", ["next Thursday", "Monday", "sometime soon", "", "the 4th"])
def test_ambiguous_or_unknown_phrases_resolve_to_nothing(phrase):
    """'Monday' said on a Monday, or 'next Thursday', can mean two dates. None
    means the tool does not second-guess the model and the prompt says ask."""
    assert relative_dates.resolve_phrase(phrase, MON) is None


@pytest.mark.parametrize("utc, local_day", [
    (datetime(2026, 11, 3, 4, 59, tzinfo=timezone.utc), date(2026, 11, 2)),   # 11:59 p.m.
    (datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc), date(2026, 11, 3)),    # midnight
])
def test_today_is_the_tenants_date_not_the_servers(utc, local_day):
    with patch.object(relative_dates, "_utcnow", lambda: utc):
        assert relative_dates.today_for({"calendar_timezone": TZ}) == local_day


def test_today_differs_by_tenant_timezone_at_the_same_instant():
    at = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
    with patch.object(relative_dates, "_utcnow", lambda: at):
        assert relative_dates.today_for({"calendar_timezone": TZ}) == date(2026, 11, 2)
        assert relative_dates.today_for({"calendar_timezone": "Europe/Dublin"}) == date(2026, 11, 3)


def test_day_after_tomorrow_across_the_autumn_clock_change():
    """Saturday 31 October, 7 p.m. EDT. Clocks go back on Sunday 1 November."""
    at = datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)
    with patch.object(relative_dates, "_utcnow", lambda: at):
        today = relative_dates.today_for({"calendar_timezone": TZ})
    assert today == date(2026, 10, 31)
    assert relative_dates.resolve_phrase("the day after tomorrow", today) == date(2026, 11, 2)


def test_tomorrow_across_the_spring_clock_change():
    """Saturday 7 March 2026, 10 p.m. EST. Clocks go forward overnight."""
    at = datetime(2026, 3, 8, 3, 0, tzinfo=timezone.utc)
    with patch.object(relative_dates, "_utcnow", lambda: at):
        today = relative_dates.today_for({"calendar_timezone": TZ})
    assert today == date(2026, 3, 7)
    assert relative_dates.resolve_phrase("tomorrow", today) == date(2026, 3, 8)


def test_the_prompt_lists_the_resolved_dates_instead_of_asking_the_model_to_count():
    with patch.object(relative_dates, "_utcnow", lambda: NOW):
        block = relative_dates.prompt_block({"calendar_timezone": TZ})
    assert "Today: Monday, November 2, 2026 (2026-11-02)" in block
    assert "Tomorrow: Tuesday, November 3, 2026 (2026-11-03)" in block
    assert "Day after tomorrow: Wednesday, November 4, 2026 (2026-11-04)" in block
    assert "never count days yourself" in block
    assert "America/Toronto" in block
    assert "count forward from today" not in block


def test_the_live_prompt_uses_the_resolved_block():
    from routers import webhooks
    assert "date_note = relative_dates.prompt_block(tenant)" in inspect.getsource(webhooks)


# ── 2. the tools check the date they are given ───────────────────────────────

async def test_availability_refuses_a_date_that_contradicts_the_callers_words():
    """The exact 2 November mistake."""
    with Cal() as c:
        said = await c.availability(date="2026-11-05", date_phrase="the day after tomorrow")
    assert c.slot_dates == [], "no calendar was read for the wrong day"
    assert "2026-11-04" in said and "Nothing has been checked or booked" in said


async def test_availability_for_the_right_day_says_which_day_it_is():
    with Cal() as c:
        said = await c.availability(date="2026-11-04", date_phrase="the day after tomorrow")
    assert c.slot_dates == ["2026-11-04"]
    assert "Wednesday, November 4, 2026 (the day after tomorrow)" in said


async def test_booking_refuses_a_date_that_contradicts_the_callers_words():
    with Cal() as c:
        said = await c.book("2026-11-05", date_phrase="the day after tomorrow")
    assert c.created == [] and c.bookings_from_this_call() == []
    assert "2026-11-04" in said


async def test_booking_refuses_a_date_in_the_past():
    with Cal() as c:
        said = await c.book("2026-11-01")
    assert c.created == []
    assert "in the past" in said


@pytest.mark.parametrize("day, offset_hours", [("2026-11-01", -5), ("2026-03-08", -4)])
async def test_a_booking_on_a_clock_change_day_gets_that_days_offset(day, offset_hours):
    """9 a.m. on the day the clocks change is 9 a.m. local, at that day's offset."""
    at = datetime.fromisoformat(day + "T05:00:00+00:00") - timedelta(days=1)
    with Cal(now=at) as c:
        await c.book(day)
    start = c.created[0]["start_dt"]
    assert (start.hour, start.minute) == (9, 0)
    assert start.utcoffset() == timedelta(hours=offset_hours)


# ── 3. a second booking in the same call is never silent ─────────────────────

async def test_a_correction_does_not_quietly_add_a_second_booking():
    with Cal([NOV5_THIS_CALL]) as c:
        said = await c.book("2026-11-04")
    assert c.created == [], "nothing was booked"
    assert c.bookings_from_this_call() == ["2026-11-05T14:00:00+00:00"]
    assert "replace_booking" in said and "Nothing has been booked" in said


async def test_an_extra_booking_needs_the_callers_explicit_yes():
    with Cal([NOV5_THIS_CALL]) as c:
        await c.book("2026-11-04", also_keep_earlier_booking=True)
    assert len(c.created) == 1
    assert len(c.bookings_from_this_call()) == 2


async def test_a_retried_booking_is_not_booked_twice():
    with Cal([NOV4_THIS_CALL]) as c:
        said = await c.book("2026-11-04", "09:00", also_keep_earlier_booking=True)
    assert c.created == []
    assert said.startswith("Already booked")


async def test_appointments_from_earlier_calls_do_not_trigger_the_guard():
    with Cal([NOV3_EARLIER_CALL]) as c:
        await c.book("2026-11-04")
    assert len(c.created) == 1


async def test_without_replace_the_guard_offers_no_tool_it_does_not_have():
    with Cal([NOV5_THIS_CALL]) as c:
        c.tenant["square_appointments_enabled"] = True
        said = await tools._same_call_booking_guard(
            CALL, c.tenant, TID, PHONE, "2026-11-04", "09:00", {})
    assert "replace_booking" not in said and "can't swap it" in said


# ── 4. replace_booking: new first, old second, retries change nothing ────────

async def test_replace_books_the_correction_then_cancels_the_earlier_booking():
    with Cal([NOV3_EARLIER_CALL, NOV5_THIS_CALL]) as c:
        said = await c.replace("2026-11-04", date_phrase="the day after tomorrow")
    assert len(c.created) == 1 and c.created[0]["start_dt"].day == 4
    assert c.cancelled == ["EV-a-nov5"]
    assert c.status("a-nov5") == "cancelled"
    new = next(a for a in c.appts.values() if a["id"].startswith("new-"))
    assert new["rescheduled_from_appointment_id"] == "a-nov5"
    assert c.status("a-nov3") == "confirmed", "the earlier call's booking is untouched"
    assert len(c.sms) == 1 and "changed to Wednesday, November 4" in c.sms[0]
    # what remains is re-read: the 3rd AND the 4th, never "only one"
    assert "Tuesday, November 3 at 9:15 AM" in said and "Wednesday, November 4 at 9:00 AM" in said
    assert "(2 in total)" in said


async def test_when_the_new_booking_fails_the_original_stays():
    with Cal([NOV5_THIS_CALL], create_fails=True) as c:
        said = await c.replace("2026-11-04")
    assert c.cancelled == []
    assert c.status("a-nov5") == "confirmed"
    assert "still in place" in said and "nothing has changed" in said
    assert c.sms == []


async def test_when_the_cancel_fails_both_stand_and_the_caller_is_told():
    with Cal([NOV5_THIS_CALL], cancel_fails=True) as c:
        said = await c.replace("2026-11-04")
    assert len(c.created) == 1
    assert c.status("a-nov5") == "confirmed"
    assert "both are booked right now" in said
    assert "don't promise one" in said and c.sms == []
    assert "(2 in total)" in said


async def test_a_retried_replace_changes_nothing():
    with Cal([NOV5_THIS_CALL]) as c:
        await c.replace("2026-11-04")
        said = await c.replace("2026-11-04")
    assert len(c.created) == 1 and c.cancelled == ["EV-a-nov5"]
    assert said.startswith("Already done")


async def test_replace_never_touches_an_appointment_from_an_earlier_call():
    with Cal([NOV3_EARLIER_CALL]) as c:
        said = await c.replace("2026-11-04")
    assert c.created == [] and c.cancelled == []
    assert c.status("a-nov3") == "confirmed"
    assert "no booking from earlier in this call" in said


async def test_replace_refuses_when_two_bookings_were_made_in_the_call():
    with Cal([NOV4_THIS_CALL, NOV5_THIS_CALL]) as c:
        said = await c.replace("2026-11-06")
    assert c.created == [] and c.cancelled == []
    assert "can't tell which to replace" in said


async def test_replace_checks_the_corrected_date_too():
    with Cal([NOV5_THIS_CALL]) as c:
        said = await c.replace("2026-11-05", "10:00", date_phrase="the day after tomorrow")
    assert c.created == [] and c.cancelled == []
    assert "2026-11-04" in said


async def test_replace_is_refused_when_deposits_are_on():
    with Cal([NOV5_THIS_CALL], deposit="stripe") as c:
        said = await c.replace("2026-11-04")
    assert c.created == [] and c.cancelled == []
    assert "Nothing has changed" in said


@pytest.mark.parametrize("tenant, expected", [
    ({"google_refresh_token": "rt"}, True),
    ({"microsoft_refresh_token": "rt"}, True),
    ({"google_refresh_token": "rt", "square_appointments_enabled": True}, False),
    ({}, False),
])
def test_replace_is_offered_only_where_it_can_run(tenant, expected):
    assert vapi.supports_same_call_replace(tenant) is expected


def test_replace_tool_and_its_prompt_come_together():
    off = [t["function"]["name"] for t in vapi.build_calendar_tools("t1")]
    on = [t["function"]["name"] for t in vapi.build_calendar_tools("t1", supports_same_call_replace=True)]
    assert "replace_booking" not in off and "replace_booking" in on
    assert "replace_booking" not in vapi.caller_lookup_note()
    assert "replace_booking" in vapi.caller_lookup_note(supports_same_call_replace=True)


def test_booking_itself_still_never_cancels():
    """The W6A2 rule holds: the swap lives in replace_booking, not in booking."""
    src = inspect.getsource(tools.book_appointment) + inspect.getsource(tools._calendar_book)
    assert "cancel_event" not in src


# ── 5. what remains is re-read after a cancellation ──────────────────────────

async def test_a_cancellation_reports_what_is_really_left():
    with Cal([NOV3_EARLIER_CALL, NOV4_THIS_CALL, NOV5_THIS_CALL]) as c, \
            patch("services.appointment_refs.resolve_for_cancel",
                  new=AsyncMock(return_value=("ok", {"appointment_id": "a-nov5"}))), \
            patch("services.appointment_refs.claim", new=AsyncMock(return_value=True)):
        res = await tools.cancel_appointment(
            _Req(), TID, Cal._body("cancel_appointment", {"appointment_ref": "appt_3"}))
    said = res["results"][0]["result"]
    assert c.status("a-nov5") == "cancelled"
    assert "Tuesday, November 3 at 9:15 AM" in said and "Wednesday, November 4" in said
    assert "Thursday, November 5" not in said.split("Re-read just now")[1]
    assert "(2 in total)" in said


async def test_if_the_re_read_fails_the_model_is_told_not_to_guess():
    with patch("db.supabase.get_active_appointments_by_phone", new=AsyncMock(side_effect=RuntimeError)):
        said = await tools._remaining_clause({"calendar_timezone": TZ}, TID, PHONE)
    assert "don't say what else is or isn't booked" in said


# ── 6. a text is promised only when one was sent ─────────────────────────────

async def test_a_sent_text_is_reported_as_sent():
    with Cal() as c:
        said = await c.book("2026-11-04")
    assert len(c.sms) == 1
    assert "A confirmation text has been sent" in said


@pytest.mark.parametrize("kw", [{"sms_ok": False}, {"twilio": False}])
async def test_no_text_means_no_promise(kw):
    with Cal(**kw) as c:
        said = await c.book("2026-11-04")
    assert len(c.created) == 1
    assert "do NOT promise one" in said
    assert "text has been sent" not in said and "shortly" not in said


def test_no_prompt_promises_a_text_unconditionally():
    assert "they'll get a text shortly" not in calendar_router._CALENDAR_NOTE
    assert "only if the tool result says one was sent" in calendar_router._CALENDAR_NOTE


# ── 7. the words match what the assistant can do ─────────────────────────────

def test_the_calendar_note_has_one_cancellation_procedure():
    """It had two: 'confirm, then cancel immediately' and the list-then-choose
    procedure. The first is gone."""
    assert "When cancelling:" not in calendar_router._CALENDAR_NOTE
    assert "call cancel_appointment immediately" not in calendar_router._CALENDAR_NOTE


def test_saying_moves_are_unsupported_no_longer_reads_as_no_cancelling():
    note = vapi.caller_lookup_note()
    assert "You CAN cancel an appointment the caller asks to cancel" in note
    assert "Never tell a caller you can't cancel" in note


def test_a_keep_only_request_is_confirmed_appointment_by_appointment():
    note = vapi.caller_lookup_note()
    assert "which appointments they want to KEEP" in note
    assert 'Never say "you now have only one"' in note


def test_date_phrase_is_on_the_date_taking_tools():
    tools_ = {t["function"]["name"]: t for t in
              vapi.build_calendar_tools("t1", supports_same_call_replace=True)}
    for name in ("check_availability", "book_appointment", "replace_booking"):
        assert "date_phrase" in tools_[name]["function"]["parameters"]["properties"], name


# ── 8. speech ─────────────────────────────────────────────────────────────────

def test_times_and_dates_are_spoken_naturally():
    style = vapi.RECEPTIONIST_STYLE
    assert '"nine fifteen a.m."' in style
    assert 'Never "nine and fifteen"' in style
    assert "Wednesday, November fourth" in style


def test_no_doubled_holding_lines_or_repeated_openers():
    style = vapi.RECEPTIONIST_STYLE
    assert "Don't add your own" in style
    assert "bridge the pause" not in style
    assert "especially \"Perfect\"" in style
    book = next(t for t in vapi.build_calendar_tools("t1")
                if t["function"]["name"] == "book_appointment")
    assert not book["messages"][0]["content"].startswith("Perfect")


# ── 9. the caller context no longer counts a cancelled appointment ────────────

def test_upcoming_appointment_for_the_prompt_ignores_cancelled_ones():
    from db import supabase
    src = inspect.getsource(supabase.get_upcoming_appointment_by_phone)
    assert '.in_("status", ["confirmed", "pending_payment"])' in src


# ── 10. retries of replace_booking report what is really true ─────────────────

async def test_a_failed_cancel_then_a_retry_is_never_reported_as_already_done():
    with Cal([NOV5_THIS_CALL], cancel_fails=True) as c:
        first = await c.replace("2026-11-04")
        again = await c.replace("2026-11-04")
    assert "both are booked right now" in first
    assert not again.startswith("Already done")
    assert "both are booked right now" in again
    assert c.status("a-nov5") == "confirmed" and len(c.created) == 1


async def test_a_retry_after_a_failed_cancel_finishes_the_cancel():
    with Cal([NOV5_THIS_CALL], cancel_fails=True) as c:
        await c.replace("2026-11-04")
        c.cancel_fails = False
        said = await c.replace("2026-11-04")
    assert len(c.created) == 1, "the replacement is not booked twice"
    assert c.cancelled == ["EV-a-nov5"] and c.status("a-nov5") == "cancelled"
    assert said.startswith("Done") and "(1 in total)" in said


async def test_provider_cancel_succeeds_but_our_record_does_not():
    with Cal([NOV5_THIS_CALL]) as c:
        c.update_fails_for.add("a-nov5")
        first = await c.replace("2026-11-04")
        again = await c.replace("2026-11-04")
    assert c.cancelled == ["EV-a-nov5"], "the calendar cancel happened once"
    assert "a-nov5" in c.held, "ownership kept for reconciliation"
    assert "our own record of it couldn't be updated" in first
    assert "don't promise one" in first and c.sms == []
    assert not again.startswith("Already done")
    assert "isn't confirmed yet" in again and "don't try again" in again
    assert c.cancelled == ["EV-a-nov5"], "the retry did not cancel again"


async def test_already_done_only_after_re_reading_both_bookings():
    with Cal([NOV5_THIS_CALL]) as c:
        await c.replace("2026-11-04")
        said = await c.replace("2026-11-04")
    assert said.startswith("Already done, re-read just now")
    assert "earlier one on Thursday, November 5 at 9:00 AM is cancelled" in said


# ── 11. duplicate protection holds under concurrency, failure and crashes ─────

async def test_simultaneous_requests_for_the_same_slot_create_one_event(booking_claims_store):
    with Cal() as c:
        c.create_delay = 0.01
        results = await asyncio.gather(*(c.book("2026-11-04") for _ in range(5)))
    assert len(c.created) == 1
    assert len(c.bookings_from_this_call()) == 1
    assert sum(r.startswith("Done!") for r in results) == 1
    assert all("Nothing new has been booked" in r or r.startswith("Done!") for r in results)


async def test_simultaneous_requests_for_different_slots_book_one(booking_claims_store):
    """The correction racing the original: only one may be in flight per call."""
    with Cal() as c:
        c.create_delay = 0.01
        a, b = await asyncio.gather(c.book("2026-11-04"), c.book("2026-11-05"))
    assert len(c.created) == 1 and len(c.bookings_from_this_call()) == 1
    assert "Another booking for this caller is being made" in (a + b)


async def test_a_failed_lookup_books_nothing():
    with Cal() as c:
        c.lookup_fails = True
        said = await c.book("2026-11-04")
    assert c.created == []
    assert "couldn't check what's already booked" in said


async def test_a_failed_claim_store_books_nothing(booking_claims_store):
    booking_claims_store.fail = True
    with Cal() as c:
        said = await c.book("2026-11-04")
    assert c.created == []
    assert "nothing has been booked" in said


async def test_an_uncertain_create_holds_the_slot_and_books_nothing_twice():
    import httpx
    with Cal() as c:
        c.create_error, c.create_lands = httpx.ReadTimeout("timed out"), True
        c.get_event_fails = True
        first = await c.book("2026-11-04")
        again = await c.book("2026-11-04")
    assert "Do NOT book it again" in first
    assert "already being made" in again
    assert len(c.created) == 1, "the event that may exist is not made again"
    assert c.bookings_from_this_call() == []


async def test_an_uncertain_create_that_landed_is_recognised():
    import httpx
    with Cal() as c:
        c.create_error, c.create_lands = httpx.ReadTimeout("timed out"), True
        said = await c.book("2026-11-04")
    assert said.startswith("Done!")
    assert len(c.created) == 1 and len(c.bookings_from_this_call()) == 1


async def test_a_crash_after_creating_the_event_is_recovered_without_a_second_event(
        booking_claims_store):
    from services import booking_claims
    with Cal() as c:
        c.insert_fails = 1                         # the process "dies" before the row lands
        await c.book("2026-11-04")
        assert c.bookings_from_this_call() == [] and len(c.created) == 1
        soon = await c.book("2026-11-04")
        assert "already being made" in soon       # inside the window: hands off
        later = booking_claims._now() + timedelta(seconds=booking_claims.STALE_SECONDS + 5)
        with patch.object(booking_claims, "_now", lambda: later):
            recovered = await c.book("2026-11-04")
        third = await c.book("2026-11-04")
    assert len(c.created) == 1, "recovery re-sent the same event id"
    assert len(c.bookings_from_this_call()) == 1, "exactly one appointment row"
    assert recovered.startswith("Done!")
    assert third.startswith("Already booked")


async def test_a_definite_failure_frees_the_slot_for_a_new_attempt(booking_claims_store):
    import httpx
    req = httpx.Request("POST", "https://example.test")
    with Cal() as c:
        c.create_error = httpx.HTTPStatusError("bad", request=req,
                                               response=httpx.Response(400, request=req))
        first = await c.book("2026-11-04")
        second = await c.book("2026-11-04")
    assert "Done!" not in first and second.startswith("Done!")
    claim = next(iter(booking_claims_store.rows.values()))
    assert claim["attempt"] == 2 and claim["state"] == "booked"


def test_event_ids_are_deterministic_and_valid_for_google():
    from services import booking_claims
    claim = {"tenant_id": TID, "vapi_call_id": CALL, "slot_start": "2026-11-04T14:00:00+00:00",
             "attempt": 1}
    a, b = booking_claims.event_id(claim), booking_claims.event_id(dict(claim))
    assert a == b and 5 <= len(a) <= 1024
    assert set(a) <= set("0123456789abcdefghijklmnopqrstuv")
    assert booking_claims.event_id({**claim, "attempt": 2}) != a
