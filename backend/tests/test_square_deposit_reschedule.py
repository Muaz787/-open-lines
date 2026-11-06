"""
Issue #179 — moving Square appointments that have a deposit, in place.

All Square behaviour here is MOCKED: the fake below models UpdateBooking as
Square documents it (booking id kept, version incremented, optimistic version
check, idempotency key replay, start_at the only field sent). The real API is
exercised separately by tests/test_square_sandbox_update.py, which
runs only against a Square sandbox seller.

  case                                         single-location   multi-location
  paid deposit, success                              x                 x
  deposit owed (pending link), success               x                 x
  paid + an unpaid link on file                      x
  payment arrives during the move                    x
  paid deposit inside the refund window              x (team)          x (team)
  same team member not free                          x
  slot taken / offer expired                         x
  Square version changed (edited meanwhile)          x
  seller can't write bookings (403)                  x
  booking changed or cancelled at Square             x
  concurrent requests                                x
  retry after success                                x
  uncertain outcome: landed / unknown + recovery     x
  read-back differs after Square says OK             x
"""
import asyncio
import contextlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import calendar_reschedule as cr, mutation_ownership, relative_dates
from services import square_booking as sb, square_inplace_reschedule as sq_in
from tests import test_w6a1_safe_cancellation as w6a1

TID, CALL, PHONE = "t-sq", "call-1", "+16475550100"


TEST_CODE = "482917"
TEST_HASH = __import__("hashlib").sha256(TEST_CODE.encode()).hexdigest()


def open_validation(monkeypatch, *, tenant=TID, location=None, phone=PHONE, hours=6):
    """A validation window, as the web service would be configured for it."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    monkeypatch.setenv("SQUARE_INPLACE_TEST_TENANT_ID", tenant)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_LOCATION_ID", location or LOC_PID)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_CALLER_PHONE", phone)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_CODE_SHA256", TEST_HASH)
    monkeypatch.setenv("SQUARE_INPLACE_TEST_EXPIRES_AT",
                       (_dt.now(_tz.utc) + _td(hours=hours)).isoformat())


def bind_run(store, appointment_id="a-1", *, tenant=TID, disabled=False):
    store.rows[TEST_HASH] = {"code_sha256": TEST_HASH, "tenant_id": tenant, "vapi_call_id": "call-earlier",
                             "appointment_id": appointment_id, "link_claimed_at": "then",
                             "payment_id": "p-1", "disabled_at": "now" if disabled else None}


@pytest.fixture(autouse=True)
def _validation_scope(monkeypatch, inplace_runs_store):
    """These tests exercise the in-place path, which runs only for the appointment
    bound to a live validation run (services.square_inplace_scope)."""
    open_validation(monkeypatch)
    bind_run(inplace_runs_store)


LOC_PID, LOC_ID = "L-MAIN", "loc-main"
TM, OTHER_TM, VAR = "TM-AOIFE", "TM-SEAN", "VAR-CONSULT"
NOW = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)
SRC = datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)


def z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Req:
    client = type("c", (), {"host": "127.0.0.1"})()
    headers: dict = {}


class SqWorld:
    def __init__(self, *, multi=False, status="confirmed", payments=(), src=SRC, refund_hours=24):
        self.multi = multi
        self.tenant = {"id": TID, "business_name": "Studio", "square_appointments_enabled": True,
                       "square_location_id": None if multi else LOC_PID,
                       "calendar_timezone": "America/Toronto", "cancellation_refund_hours": refund_hours}
        self.appt = {"id": "a-1", "tenant_id": TID, "caller_phone": PHONE, "caller_name": "Sam",
                     "service": "Consultation", "appointment_datetime": src.isoformat(),
                     "duration_minutes": 60, "status": status, "google_event_id": "BK-1",
                     "vapi_call_id": "call-earlier",
                     "tenant_location_id": LOC_ID if multi else None,
                     "provider_location_id": LOC_PID if multi else None}
        self.payments = [dict(p) for p in payments]
        self.booking = {"id": "BK-1", "status": "ACCEPTED", "location_id": LOC_PID, "customer_id": "C-1",
                        "version": 3, "start_at": z(src),
                        "appointment_segments": [{"team_member_id": TM, "service_variation_id": VAR,
                                                  "service_variation_version": 1, "duration_minutes": 60}]}
        self.offer = {"slot_ref": "slot_1", "vapi_call_id": CALL, "tenant_id": TID,
                      "tenant_location_id": LOC_ID if multi else None, "provider_location_id": LOC_PID,
                      "service_variation_id": VAR, "service_name": "Consultation",
                      "start_at_utc": z(TARGET), "team_member_id": OTHER_TM, "duration_minutes": 60}
        self.offer_claimed = False
        self.refs = w6a1.Refs()
        self.owners: dict[str, str] = {}
        self.updates, self.idem = [], {}
        self.payment_writes = []
        self.free_for = {TM}             # team members free at TARGET
        self.update_mode = "ok"          # ok | version_mismatch | forbidden | unknown | unknown_landed
        self.get_fails = False
        self.get_fails_after_update = False
        self.attempts = 0
        self.readback = None             # how the booking reads back after an update
        self.payment_arrives = False     # the deposit webhook lands between Square and our finish
        self.delay = 0

    # our records
    async def get_appt(self, aid):
        return dict(self.appt) if aid == self.appt["id"] else None

    async def active(self, *_):
        return [dict(self.appt)] if self.appt["status"] in ("confirmed", "pending_payment") else []

    async def paid(self, aid):
        return next((dict(p) for p in self.payments if p["status"] == "succeeded"), None)

    async def write_payment(self, *a, **k):
        self.payment_writes.append(a)

    # ownership + atomic finish (migration 046's calendar_move_finish)
    async def acquire(self, aid, tid, op_id):
        if aid in self.owners:
            return mutation_ownership.BUSY, None
        self.owners[aid] = op_id
        return mutation_ownership.ACQUIRED, mutation_ownership.Claim(aid, op_id, "2026-11-03T06:00:00+00:00", "reschedule")

    async def release(self, claim):
        self.owners.pop(claim.appointment_id, None)
        return True

    async def release_raw(self, aid, token, claimed_at):
        if self.owners.get(aid) == token:
            self.owners.pop(aid)
            return True
        return False

    async def finish(self, op_id, token):
        from db import calendar_moves as db_cm
        op = await db_cm.get(op_id)
        if not op:
            return "missing"
        if op["claim_token"] != token or op["state"] != "provider_moved" or self.owners.get(op["appointment_id"]) != token:
            return "not_owner"
        if self.appt["status"] not in ("confirmed", "pending_payment"):
            return "appointment_inactive"
        self.appt["appointment_datetime"] = str(op["to_start_utc"])
        await db_cm.transition(op, ("provider_moved",), {"state": "completed"})
        self.owners.pop(op["appointment_id"])
        return "completed"

    # slot offers
    async def resolve_offer(self, *, vapi_call_id, slot_ref, tenant_id, active_location_id):
        from services import slot_offers
        if slot_ref != "slot_1":
            return slot_offers.NOT_FOUND, None
        return (slot_offers.OK, dict(self.offer))

    async def claim_offer(self, *a):
        if self.offer_claimed:
            return False
        self.offer_claimed = True
        return True

    async def release_offer(self, *a):
        self.offer_claimed = False

    # Square
    async def get_booking(self, token, bid):
        if self.get_fails or (self.get_fails_after_update and self.attempts):
            return sb.FETCH_UNKNOWN, {}
        b = json.loads(json.dumps(self.booking))
        if self.readback == "other_staff" and self.updates:
            b["appointment_segments"][0]["team_member_id"] = OTHER_TM
        return sb.FETCH_FOUND, b

    async def resolve_slot(self, token, loc, var, team_ids, start):
        if not team_ids or team_ids[0] not in self.free_for or loc != LOC_PID or var != VAR:
            return None
        return {"team_member_id": team_ids[0], "duration_minutes": 60, "start_at": z(start),
                "service_variation_version": 1}

    async def update(self, token, bid, *, version, start_at_iso, idempotency_key):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.attempts += 1
        if idempotency_key in self.idem:
            return sb.UPDATE_OK, self.idem[idempotency_key], ""
        if self.update_mode == "forbidden":
            return sb.UPDATE_FAILED, {}, "FORBIDDEN"
        if self.update_mode == "version_mismatch" or version != self.booking["version"]:
            return sb.UPDATE_FAILED, {}, "VERSION_MISMATCH"
        lands = self.update_mode in ("ok", "unknown_landed")
        if lands:
            self.booking["start_at"] = start_at_iso
            self.booking["version"] += 1
            self.updates.append((bid, version, start_at_iso, idempotency_key))
            self.idem[idempotency_key] = dict(self.booking)
            if self.payment_arrives:
                # the deposit webhook: confirm_appointment_unless_cancelled + payment row
                self.appt["status"] = "confirmed"
                self.payments.append({"id": "p-new", "status": "succeeded"})
        if self.update_mode in ("unknown", "unknown_landed"):
            return sb.UPDATE_UNKNOWN, {}, ""
        return sb.UPDATE_OK, dict(self.booking), ""

    @contextlib.contextmanager
    def env(self):
        ps = [
            patch.object(relative_dates, "_utcnow", lambda: NOW),
            patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=self.tenant)),
            patch("db.supabase.get_appointment_by_id", new=AsyncMock(side_effect=self.get_appt)),
            patch("db.supabase.get_active_appointments_by_phone", new=AsyncMock(side_effect=self.active)),
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(side_effect=self.paid)),
            patch("db.supabase.update_payment", new=AsyncMock(side_effect=self.write_payment)),
            patch("db.supabase.update_appointment", new=AsyncMock(side_effect=AssertionError("unfenced write"))),
            patch("db.supabase.insert_appointment", new=AsyncMock(side_effect=AssertionError("no new row"))),
            patch("db.appointment_refs.insert_refs", new=AsyncMock(side_effect=self.refs.insert_refs)),
            patch("db.appointment_refs.count_refs", new=AsyncMock(side_effect=self.refs.count_refs)),
            patch("db.appointment_refs.get_ref", new=AsyncMock(side_effect=self.refs.get_ref)),
            patch("db.appointment_refs.consume_ref", new=AsyncMock(side_effect=self.refs.consume_ref)),
            patch("db.appointment_refs.release_ref", new=AsyncMock(side_effect=self.refs.release_ref)),
            patch("services.call_location.is_multi_location",
                  new=AsyncMock(return_value=(self.multi, [{"id": LOC_ID, "name": "Main"}] if self.multi else []))),
            patch("services.reschedule._binding_is_live", new=AsyncMock(return_value=True)),
            patch("services.slot_offers.resolve_for_booking", new=AsyncMock(side_effect=self.resolve_offer)),
            patch("services.slot_offers.claim", new=AsyncMock(side_effect=self.claim_offer)),
            patch("services.slot_offers.release", new=AsyncMock(side_effect=self.release_offer)),
            patch("services.slot_offers.mark_consumed", new=AsyncMock()),
            patch("services.mutation_ownership.acquire_for_reschedule", new=AsyncMock(side_effect=self.acquire)),
            patch("services.mutation_ownership.release", new=AsyncMock(side_effect=self.release)),
            patch("db.mutation_claims.release_claim", new=AsyncMock(side_effect=self.release_raw)),
            patch("db.calendar_moves.finish", new=AsyncMock(side_effect=self.finish)),
            patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
            patch("services.square_booking.get_booking_detailed", new=AsyncMock(side_effect=self.get_booking)),
            patch("services.square_booking.resolve_slot", new=AsyncMock(side_effect=self.resolve_slot)),
            patch("services.square_booking.update_booking_start", new=AsyncMock(side_effect=self.update)),
            patch("services.square_booking.create_booking", new=AsyncMock(side_effect=AssertionError("no replacement"))),
            patch("services.square_booking.cancel_booking_detailed", new=AsyncMock(side_effect=AssertionError("no cancel"))),
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
        res = await tools.reschedule_appointment(Req(), TID, body)
        return res["results"][0]["result"]

    async def move(self):
        return await self.call(appointment_ref="appt_1", slot_ref="slot_1")

    def moved(self):
        return datetime.fromisoformat(self.appt["appointment_datetime"].replace("Z", "+00:00")) == TARGET


PAID = [{"id": "p-1", "status": "succeeded"}]
OWED = [{"id": "p-1", "status": "pending"}]


def assert_moved_in_place(w, said):
    assert said.startswith("Done, re-read just now"), said
    assert len(w.updates) == 1
    bid, version, start, key = w.updates[0]
    assert bid == "BK-1" and version == 3 and start == z(TARGET), "only start_at, at the version we read"
    assert w.booking["id"] == "BK-1" and w.booking["version"] == 4
    assert w.booking["appointment_segments"][0]["team_member_id"] == TM, "same team member"
    assert w.moved() and w.appt["id"] == "a-1", "same row, so the deposit stays linked"
    assert w.payment_writes == [], "no payment is touched"
    assert not w.owners


# ═════════════════════════════ successful moves ═══════════════════════════════

@pytest.mark.parametrize("multi", [False, True])
async def test_paid_deposit_moves_in_place(multi, calendar_moves_store):
    with SqWorld(multi=multi, payments=PAID).env() as w:
        await w.call()
        said = await w.move()
    assert_moved_in_place(w, said)
    assert w.appt["status"] == "confirmed"
    op = next(iter(calendar_moves_store.rows.values()))
    assert op["provider"] == "square" and op["state"] == "completed"
    assert op["team_member_id"] == TM and op["provider_version"] == 3


@pytest.mark.parametrize("multi", [False, True])
async def test_owed_deposit_moves_in_place_and_stays_owed(multi):
    with SqWorld(multi=multi, status="pending_payment", payments=OWED).env() as w:
        await w.call()
        said = await w.move()
    assert_moved_in_place(w, said)
    assert w.appt["status"] == "pending_payment", "still owed: nothing promoted it"
    assert w.payments == OWED


async def test_paid_with_an_unpaid_link_also_on_file():
    """Our deposits have no partial state; the nearest case is a paid deposit plus
    an older unpaid link. Both stay exactly as they are."""
    rows = [{"id": "p-1", "status": "succeeded"}, {"id": "p-2", "status": "pending"}]
    with SqWorld(payments=rows).env() as w:
        await w.call()
        said = await w.move()
    assert_moved_in_place(w, said)
    assert w.payments == rows


async def test_payment_arriving_during_the_move_is_kept():
    with SqWorld(status="pending_payment", payments=OWED).env() as w:
        w.payment_arrives = True
        await w.call()
        said = await w.move()
    assert_moved_in_place(w, said)
    assert w.appt["status"] == "confirmed", "the webhook's confirmation wasn't overwritten"
    assert {"id": "p-new", "status": "succeeded"} in w.payments


# ═══════════════════════ refused before anything is sent ══════════════════════

@pytest.mark.parametrize("multi", [False, True])
async def test_a_paid_deposit_inside_the_refund_window_goes_to_the_team(multi):
    soon = NOW + timedelta(hours=10)
    with SqWorld(multi=multi, payments=PAID, src=soon).env() as w:
        await w.call()
        said = await w.move()
    assert w.updates == [] and "cancellation window" in said and not w.owners


async def test_an_owed_deposit_inside_the_window_can_still_move():
    """No money has been paid, so no refund is reopened."""
    soon = NOW + timedelta(hours=10)
    with SqWorld(status="pending_payment", payments=OWED, src=soon).env() as w:
        await w.call()
        said = await w.move()
    assert said.startswith("Done")


async def test_the_same_team_member_must_be_free():
    with SqWorld(payments=PAID).env() as w:
        w.free_for = {OTHER_TM}           # only someone else is free then
        await w.call()
        said = await w.move()
    assert w.updates == [] and "same team member" in said
    assert not w.owners and not w.offer_claimed


async def test_a_taken_slot_moves_nothing():
    with SqWorld(payments=PAID).env() as w:
        w.offer_claimed = True            # another request already used this offer
        await w.call()
        said = await w.move()
    assert w.updates == [] and "just been taken" in said and not w.owners


@pytest.mark.parametrize("change", ["start", "status", "staff", "location"])
async def test_a_booking_changed_at_square_goes_to_the_team(change):
    with SqWorld(payments=PAID).env() as w:
        if change == "start":
            w.booking["start_at"] = z(SRC + timedelta(hours=1))
        elif change == "status":
            w.booking["status"] = "CANCELLED_BY_SELLER"
        elif change == "staff":
            w.booking["appointment_segments"][0]["team_member_id"] = ""
        else:
            w.booking["location_id"] = "L-ELSEWHERE"
        await w.call()
        said = await w.move()
    assert w.updates == [] and "can't move that appointment automatically" in said and not w.owners


# ═══════════════════════════ Square says no ══════════════════════════════════

@pytest.mark.parametrize("mode", ["version_mismatch", "forbidden"])
async def test_a_refused_update_keeps_the_original(mode, calendar_moves_store):
    with SqWorld(payments=PAID).env() as w:
        w.update_mode = mode
        await w.call()
        said = await w.move()
    assert not w.moved() and w.booking["start_at"] == z(SRC)
    assert "refused the change" in said and not w.owners and not w.offer_claimed
    op = next(iter(calendar_moves_store.rows.values()))
    assert op["state"] == "failed"


# ═════════════════════ concurrency, retries, uncertainty ══════════════════════

async def test_concurrent_requests_send_one_update():
    with SqWorld(payments=PAID).env() as w:
        await w.call()
        w.delay = 0.01
        a, b = await asyncio.gather(w.move(), w.move())
    assert len(w.updates) == 1 and sum(s.startswith("Done") for s in (a, b)) == 1


async def test_a_retry_after_success_moves_nothing_again():
    with SqWorld(payments=PAID).env() as w:
        await w.call()
        await w.move()
        again = await w.move()
    assert len(w.updates) == 1 and again.startswith("Already done")


async def test_an_uncertain_update_that_landed_is_recognised():
    with SqWorld(payments=PAID).env() as w:
        w.update_mode = "unknown_landed"
        await w.call()
        said = await w.move()
    assert said.startswith("Done") and w.moved() and len(w.updates) == 1


async def test_an_unknown_update_holds_and_recovery_settles_it(calendar_moves_store):
    with SqWorld(payments=PAID).env() as w:
        w.update_mode, w.get_fails_after_update = "unknown", True
        await w.call()
        first = await w.move()
        assert "couldn't confirm" in first and "a-1" in w.owners and not w.moved()
        w.get_fails_after_update = False
        op = next(iter(calendar_moves_store.rows.values()))
        op["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        settled = await cr.run_recovery()
    assert settled == {cr.FAILED: 1} and not w.owners and not w.moved()
    assert w.updates == [], "recovery never re-sends"


async def test_a_readback_that_differs_after_ok_is_not_trusted(calendar_moves_store):
    with SqWorld(payments=PAID).env() as w:
        w.readback = "other_staff"
        await w.call()
        said = await w.move()
    assert not said.startswith("Done") and not w.moved() and "a-1" in w.owners
    op = next(iter(calendar_moves_store.rows.values()))
    assert op["state"] == "provider_moved" and op["detail"] == "provider mismatch"


# ═══════════════════════════════ the request ═════════════════════════════════

def test_update_sends_only_the_version_and_start():
    import inspect
    src = inspect.getsource(sb.update_booking_start)
    assert '"booking": {"version": version, "start_at": start_at_iso}' in src
    assert "appointment_segments" not in src.split('"""')[2]


@pytest.mark.parametrize("case", ["validation off", "other tenant configured", "run bound elsewhere",
                                  "run disabled", "window expired", "window over 24h", "other code configured"])
async def test_outside_the_validation_scope_deposits_go_to_the_team_as_before(
        case, monkeypatch, inplace_runs_store, calendar_moves_store):
    if case == "validation off":
        monkeypatch.delenv("SQUARE_INPLACE_TEST_TENANT_ID")
    elif case == "other tenant configured":
        open_validation(monkeypatch, tenant="t-other")
    elif case == "run bound elsewhere":
        bind_run(inplace_runs_store, "a-other")
    elif case == "run disabled":
        bind_run(inplace_runs_store, disabled=True)
    elif case == "window expired":
        open_validation(monkeypatch, hours=-1)
    elif case == "window over 24h":
        open_validation(monkeypatch, hours=30)
    else:
        monkeypatch.setenv("SQUARE_INPLACE_TEST_CODE_SHA256", "0" * 64)
    from services import reschedule_intent as ri
    with SqWorld(payments=PAID).env() as w:
        await w.call()
        said = await w.move()
    assert said == ri.message_for(ri.PAYMENT_ON_FILE), "today's team handoff, word for word"
    assert w.updates == [] and not w.owners and not w.moved()
    assert calendar_moves_store.rows == {}, "no move operation recorded"


async def test_the_in_place_move_refuses_an_appointment_outside_the_scope(inplace_runs_store):
    bind_run(inplace_runs_store, "a-other")
    with SqWorld(payments=PAID).env() as w:
        await w.call()
        outcome, _ = await sq_in.move(tenant=w.tenant, tenant_id=TID, vapi_call_id=CALL,
                                      caller_phone=PHONE, appointment_ref="appt_1", slot_ref="slot_1")
    assert outcome == sq_in.HANDOFF and w.updates == [] and not w.owners


def test_no_payment_is_written_by_the_in_place_move():
    import inspect
    src = inspect.getsource(sq_in)
    for forbidden in ("update_payment", "issue_provider_refund", "_create_and_send_deposit", "insert_appointment"):
        assert forbidden not in src
