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
        self.after_patch = None          # how the event reads back after a PATCH succeeds
        self.patched_ids: set[str] = set()
        self.finished: list[str] = []

    # db
    def active(self, *_):
        return [dict(a) for a in self.appts.values() if a["status"] in ("confirmed", "pending_payment")]

    async def get_appt(self, aid):
        return dict(self.appts[aid]) if aid in self.appts else None

    async def update_appt(self, aid, data):
        if self.update_fails:
            raise RuntimeError("write lost")
        self.appts[aid].update(data)

    async def finish(self, op_id, token):
        """calendar_move_finish, with the same checks, in one uninterrupted step."""
        from db import calendar_moves as db_cm
        if self.update_fails:
            raise RuntimeError("write lost")
        op = await db_cm.get(op_id)
        if not op:
            return "missing"
        if op["claim_token"] != token or op["state"] != "provider_moved":
            return "not_owner"
        if self.owners.get(op["appointment_id"]) != token:
            return "not_owner"
        appt = self.appts[op["appointment_id"]]
        if appt["status"] not in ("confirmed", "pending_payment"):
            return "appointment_inactive"
        appt["appointment_datetime"] = str(op["to_start_utc"])
        await db_cm.transition(op, ("provider_moved",), {"state": "completed"})
        self.owners.pop(op["appointment_id"])
        self.finished.append(op_id)
        return "completed"

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
        self.patched_ids.add(event_id)
        return {}

    async def get_event(self, rt, event_id):
        mode = self.after_patch if event_id in self.patched_ids else None
        if self.get_fails or mode == "unreadable":
            raise RuntimeError("calendar unreachable")
        if event_id not in self.events:
            return None
        start = datetime.fromisoformat(self.events[event_id])
        end = start + timedelta(minutes=60)
        if mode == "moved_elsewhere":
            start, end = start + timedelta(minutes=30), end + timedelta(minutes=30)
        if mode == "end_changed":
            end = end + timedelta(minutes=15)

        def fmt(dt):
            if self.provider == "microsoft":
                return {"dateTime": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000"),
                        "timeZone": "UTC"}
            return {"dateTime": dt.isoformat()}
        ev = {"start": fmt(start), "end": fmt(end)}
        if mode == "cancelled":
            ev.update({"status": "cancelled", "isCancelled": True})
        elif self.provider != "microsoft":
            ev["status"] = "confirmed"
        return ev

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
            patch("db.supabase.update_payment", new=AsyncMock(side_effect=AssertionError("payment written"))),
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
            patch("db.calendar_moves.finish", new=AsyncMock(side_effect=self.finish)),
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
    assert w.payment_calls == 1, ("the deposit is read once, under ownership, to wait out one "
                                  "that has just been paid; nothing is charged or refunded")


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
async def test_square_deposit_appointments_never_use_the_replacement_engine(multi, deposit):
    """Issue #179: a deposit appointment moves in place (tests/test_square_deposit_
    reschedule.py) or goes to the team. It is never booked anew and cancelled,
    which would leave the deposit on a cancelled row."""
    status = "pending_payment" if deposit == "owed" else "confirmed"
    if multi:
        w = d3.World([d3.appt("a-cork", status=status)])
        ctx = d3.env(w)
    else:
        w = single_world(status=status)
        ctx = single_env(w)
    payment = {"id": "p1", "status": "succeeded"} if deposit == "paid" else None
    with ctx as e, patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=payment)), \
            patch("services.square_booking.update_booking_start", new=AsyncMock()) as upd:
        await d3.call()
        said = await d3.call("appt_1", "slot_1")
    assert e["create"].await_count == 0 and w.cancelled_bookings == []
    assert not said.startswith("Done") or upd.await_count == 1


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



# ═══════════ after a successful PATCH, the event must read back exactly ═══════

@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("mode", ["moved_elsewhere", "end_changed", "cancelled", "unreadable"])
async def test_cal_patch_success_is_not_trusted_until_the_event_reads_back(provider, mode,
                                                                          calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.after_patch = mode
        said = await w.move()
    assert len(w.patches) == 1
    assert not said.startswith("Done") and "couldn't confirm" in said
    assert w.sms == [], "no confirmation text without proof"
    assert at(w) == datetime.fromisoformat(SOURCE_UTC), "our record is not moved on an unproven event"
    op = next(iter(calendar_moves_store.rows.values()))
    assert op["state"] == "provider_moved", "kept live for reconciliation"
    assert "a-1" in w.owners, "the appointment stays owned"
    if mode != "unreadable":
        assert op["detail"] == f"provider {'missing' if mode == 'cancelled' else 'mismatch'}"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_unreadable_after_patch_completes_once_it_reads_back(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.after_patch = "unreadable"
        await w.move()
        w.after_patch = None
        op = next(iter(calendar_moves_store.rows.values()))
        op["updated_at"] = (NOW - timedelta(hours=1)).isoformat()
        settled = await cr.run_recovery()
    assert settled == {cr.COMPLETED: 1} and at(w) == TARGET_UTC and not w.owners
    assert len(w.patches) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_mismatched_event_never_completes_on_recovery(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        await w.call()
        w.after_patch = "moved_elsewhere"
        await w.move()
        op = next(iter(calendar_moves_store.rows.values()))
        op["updated_at"] = (NOW - timedelta(hours=1)).isoformat()
        settled = await cr.run_recovery()
    assert settled == {cr.UNKNOWN: 1} and "a-1" in w.owners
    assert at(w) == datetime.fromisoformat(SOURCE_UTC) and len(w.patches) == 1


# ═══════════════════ earlier today and clock-change targets ═══════════════════

AFTERNOON = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)      # Wed 1:00 p.m. Toronto


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_earlier_today_is_refused(provider):
    w = CalWorld(provider, [appointment(when="2026-11-04T21:00:00+00:00")])   # Wed 4 p.m.
    with w.env(), patch.object(relative_dates, "_utcnow", lambda: AFTERNOON):
        await w.call()
        said = await w.move(date="2026-11-04", time="10:00")
    assert w.patches == [] and "already passed" in said


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cal_later_today_is_allowed(provider):
    w = CalWorld(provider, [appointment(when="2026-11-04T21:00:00+00:00")], free=["3:00 PM"])
    with w.env(), patch.object(relative_dates, "_utcnow", lambda: AFTERNOON):
        await w.call()
        said = await w.move(date="2026-11-04", time="15:00")
    assert said.startswith("Done") and w.patches == [("EV-a-1", "2026-11-04T20:00:00+00:00")]


SPRING_EVE = datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)      # Sat 7 Mar, before clocks go forward
AUTUMN_EVE = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)    # Sat 31 Oct, before clocks go back


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("now, source, date, time", [
    (SPRING_EVE, "2026-03-09T13:00:00+00:00", "2026-03-08", "02:30"),   # does not exist
    (AUTUMN_EVE, "2026-11-02T14:00:00+00:00", "2026-11-01", "01:30"),   # happens twice
])
async def test_cal_clock_change_hours_are_refused(provider, now, source, date, time):
    w = CalWorld(provider, [appointment(when=source)])
    w.tenant.update(business_hours_start=0, business_hours_end=23)
    with w.env(), patch.object(relative_dates, "_utcnow", lambda: now):
        await w.call()
        said = await w.move(date=date, time=time)
    assert w.patches == [] and "clocks change" in said


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("now, source, date, utc", [
    (SPRING_EVE, "2026-03-09T13:00:00+00:00", "2026-03-08", "2026-03-08T14:00:00+00:00"),  # EDT
    (AUTUMN_EVE, "2026-11-02T14:00:00+00:00", "2026-11-01", "2026-11-01T15:00:00+00:00"),  # EST
])
async def test_cal_ordinary_hours_on_clock_change_days_use_that_days_offset(provider, now, source,
                                                                            date, utc):
    w = CalWorld(provider, [appointment(when=source)])
    with w.env(), patch.object(relative_dates, "_utcnow", lambda: now):
        await w.call()
        said = await w.move(date=date, time="10:00")
    assert said.startswith("Done") and w.patches == [("EV-a-1", utc)]


@pytest.mark.parametrize("date, time, reason", [
    ("2026-03-08", "02:30", relative_dates.NONEXISTENT),
    ("2026-11-01", "01:30", relative_dates.AMBIGUOUS),
    ("2026-11-01", "10:00", None),
    ("2026-11-01", "9am", relative_dates.BAD_FORMAT),
])
def test_local_instant_names_the_problem(date, time, reason):
    from zoneinfo import ZoneInfo
    got, why = relative_dates.local_instant(date, time, ZoneInfo("America/Toronto"))
    assert why == reason and (got is None) == (reason is not None)


# ═════════ a delayed recovery worker must never act on a newer state ══════════
#
# Codex's reproduction: a recovery worker verifies the provider and pauses.
# Another worker completes that operation and releases ownership. A later move
# changes the appointment. The delayed worker resumes and — before the fix — wrote
# its old target into the appointment before its own transition failed.

T1_UTC = "2026-11-05T15:00:00+00:00"        # Thu 10:00 a.m.
T2_UTC = "2026-11-05T16:00:00+00:00"        # Thu 11:00 a.m.


async def _first_move_left_for_recovery(w, store):
    """Move to T1; the read-back fails, so the operation is left provider_moved."""
    await w.call()
    w.after_patch = "unreadable"
    await w.move()                                   # Thursday 10:00
    w.after_patch = None
    op = next(iter(store.rows.values()))
    assert op["state"] == "provider_moved" and "a-1" in w.owners
    op["updated_at"] = (NOW - timedelta(hours=1)).isoformat()
    return dict(op)


@contextlib.contextmanager
def pause_after_verification(op_id):
    """Hold the FIRST worker that verifies op_id until released."""
    real = cr.verify_provider
    paused, resume = asyncio.Event(), asyncio.Event()

    async def slow(tenant, op):
        result = await real(tenant, op)
        if op["id"] == op_id and not paused.is_set():
            paused.set()
            await resume.wait()
        return result
    with patch.object(cr, "verify_provider", slow):
        yield paused, resume


async def _second_move(w, time="11:00"):
    listed = await w.call()
    ref = listed.split("[")[1].split("]")[0]
    return await w.move(ref=ref, time=time)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_delayed_recovery_after_a_newer_completed_move_writes_nothing(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        op1 = await _first_move_left_for_recovery(w, calendar_moves_store)
        with pause_after_verification(op1["id"]) as (paused, resume):
            delayed = asyncio.create_task(cr.settle(w.tenant, op1, known_stale=True))
            await paused.wait()
            assert await cr.run_recovery() == {cr.COMPLETED: 1}       # another worker finishes op1
            moved = await _second_move(w)                            # and a later move happens
            assert moved.startswith("Done") and w.appts["a-1"]["appointment_datetime"] == T2_UTC
            sms_before = list(w.sms)
            resume.set()
            outcome = await delayed
    assert outcome == cr.STALE
    assert w.appts["a-1"]["appointment_datetime"] == T2_UTC, "the old target was not written"
    assert w.sms == sms_before, "no stale confirmation"
    assert not w.owners
    assert w.finished.count(op1["id"]) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_delayed_recovery_never_releases_a_newer_claim(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        op1 = await _first_move_left_for_recovery(w, calendar_moves_store)
        with pause_after_verification(op1["id"]) as (paused, resume):
            delayed = asyncio.create_task(cr.settle(w.tenant, op1, known_stale=True))
            await paused.wait()
            await cr.run_recovery()                                  # op1 completed and released
            w.after_patch = "unreadable"
            await _second_move(w)                                    # op2 holds the appointment
            op2 = next(o for o in calendar_moves_store.rows.values() if o["id"] != op1["id"])
            assert op2["state"] == "provider_moved" and w.owners["a-1"] == op2["claim_token"]
            resume.set()
            outcome = await delayed
    assert outcome == cr.STALE
    assert w.owners["a-1"] == op2["claim_token"], "op2 still owns the appointment"
    assert w.appts["a-1"]["appointment_datetime"] == T1_UTC, "op1's finish didn't run twice"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_delayed_recovery_after_a_cancellation_writes_nothing(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        op1 = await _first_move_left_for_recovery(w, calendar_moves_store)
        with pause_after_verification(op1["id"]) as (paused, resume):
            delayed = asyncio.create_task(cr.settle(w.tenant, op1, known_stale=True))
            await paused.wait()
            await cr.run_recovery()
            w.appts["a-1"]["status"] = "cancelled"                    # then the caller cancels
            resume.set()
            outcome = await delayed
    assert outcome == cr.STALE
    assert w.appts["a-1"]["status"] == "cancelled"
    assert w.appts["a-1"]["appointment_datetime"] == T1_UTC


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_cancelled_while_owned_is_not_written(provider, calendar_moves_store):
    """The atomic finish also refuses an appointment that stopped being active."""
    with CalWorld(provider).env() as w:
        op1 = await _first_move_left_for_recovery(w, calendar_moves_store)
        w.appts["a-1"]["status"] = "cancelled"
        result = await cr.settle(w.tenant, op1, known_stale=True)
    assert result == cr.UNKNOWN
    assert w.appts["a-1"]["appointment_datetime"] == SOURCE_UTC and "a-1" in w.owners


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_two_recovery_passes_at_once_settle_an_operation_once(provider, calendar_moves_store):
    with CalWorld(provider).env() as w:
        op1 = await _first_move_left_for_recovery(w, calendar_moves_store)
        with pause_after_verification(op1["id"]) as (paused, resume):
            first = asyncio.create_task(cr.run_recovery())
            await paused.wait()
            second = await cr.run_recovery()        # the lease refreshed updated_at: not listed
            resume.set()
            first = await first
    assert first == {cr.COMPLETED: 1} and second == {}
    assert w.finished == [op1["id"]]


def test_the_appointment_write_lives_only_in_the_atomic_finish():
    import inspect
    src = inspect.getsource(cr)
    assert "update_appointment" not in src, "no unfenced appointment writes in the move service"
    assert "db_cm.finish(" in inspect.getsource(cr._finish_local)
