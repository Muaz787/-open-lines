"""
Issue #179 — a deposit's payment and a move of its appointment, together.

ALL MOCKED. No Square, Stripe or Twilio call is made: the payment webhooks, the
move, the booking webhook and the cancellation run against in-memory fakes. The
real Square booking-update contract is checked only by
tests/test_square_sandbox_update.py, which is separate and currently blocked.

  1. A payment confirmation never names a time that a move is changing. The
     confirmation owns the appointment (a payment_confirmation claim, migration
     047) while it reads the time and sends; a move needs the same ownership.
     test_every_interleaving_* pauses both processes before each read, write and
     send, runs every order, and checks each text against our record, Square's
     copy and the owner at the moment it is sent. The same runs without the claim
     find a stale text, so the check has teeth.
  2. A reschedule never reopens a refund window that had closed
     (services.refunds.refund_window_open).
  3. A booking moved directly in Square after the deposit was paid sends the
     refund decision to the team.
"""
import asyncio
import contextvars
import itertools
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from db import mutation_claims as db_mc
from routers import payments
from services import mutation_ownership as mo, refunds, square_booking as sb
from services import square_booking_reconcile as recon
from tests import test_square_deposit_reschedule as sq
from tests import test_w6a1_safe_cancellation as w6a1

NOW, SRC, TARGET = sq.NOW, sq.SRC, sq.TARGET
PROC = contextvars.ContextVar("proc", default=None)


def _when(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def friendly(dt):
    """The day and time exactly as the confirmation text writes them."""
    d = dt.astimezone(ZoneInfo("America/Toronto"))
    return f"{d.strftime('%A, %B')} {d.day} at {d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def named_time(text):
    return next((t for t in (SRC, TARGET) if friendly(t) in text), None)


def utcnow_iso(seconds_ago=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class Sched:
    """Releases two processes at their pause points in a given order. A finished
    process's remaining turns are skipped; past the end of the order, both run."""

    def __init__(self, order=""):
        self.order, self.i, self.done = list(order), 0, set()
        self.cv = asyncio.Condition()
        self.counts = {"W": 0, "M": 0}

    async def gate(self):
        me = PROC.get()
        if me is None:
            return
        self.counts[me] += 1
        async with self.cv:
            while True:
                while self.i < len(self.order) and self.order[self.i] in self.done:
                    self.i += 1
                if self.i >= len(self.order) or self.order[self.i] == me:
                    self.i += 1
                    self.cv.notify_all()
                    return
                await self.cv.wait()

    async def finish(self, me):
        async with self.cv:
            self.done.add(me)
            self.cv.notify_all()


class PayWorld(sq.SqWorld):
    """SqWorld plus the deposit webhooks, one fenced claim table shared by moves
    and confirmations, and a pause point before every read, write and send."""

    def __init__(self, *a, provider="stripe", lock=True, **k):
        super().__init__(*a, **k)
        self.provider, self.lock = provider, lock
        self.sched = Sched()
        self.claims: dict[str, dict] = {}          # appointment id -> {token, type}
        self.sent = []                             # (text, our time, Square's, owner) when sent
        self.owner_notes = []
        self.claim_age = 0                         # how old a new confirmation claim looks (s)

    # the claim table (021 + 047): one owner; only its own token releases it
    async def acquire(self, aid, tid, op_id):
        await self.sched.gate()
        if aid in self.claims:
            return mo.BUSY, None
        self.claims[aid] = {"token": op_id, "type": "reschedule"}
        return mo.ACQUIRED, mo.Claim(aid, op_id, utcnow_iso(), "reschedule")

    async def acquire_confirmation(self, aid, tid):
        await self.sched.gate()
        at = utcnow_iso(self.claim_age)
        if not self.lock:                          # the control: owns nothing
            return mo.ACQUIRED, mo.Claim(aid, "unlocked", at, db_mc.OP_PAYMENT_CONFIRMATION)
        if aid in self.claims:
            return mo.BUSY, None
        self.claims[aid] = {"token": "conf", "type": db_mc.OP_PAYMENT_CONFIRMATION}
        return mo.ACQUIRED, mo.Claim(aid, "conf", at, db_mc.OP_PAYMENT_CONFIRMATION)

    async def release(self, claim):
        await self.sched.gate()
        return await self.release_raw(claim.appointment_id, claim.token, claim.claimed_at)

    async def release_raw(self, aid, token, claimed_at):
        c = self.claims.get(aid)
        if c and c["token"] == token:
            del self.claims[aid]
            return True
        return False

    async def finish(self, op_id, token):
        await self.sched.gate()
        from db import calendar_moves as db_cm
        op = await db_cm.get(op_id)
        if not op:
            return "missing"
        c = self.claims.get(op["appointment_id"])
        if op["claim_token"] != token or op["state"] != "provider_moved" or not c or c["token"] != token:
            return "not_owner"
        if self.appt["status"] not in ("confirmed", "pending_payment"):
            return "appointment_inactive"
        self.appt["appointment_datetime"] = str(op["to_start_utc"])
        await db_cm.transition(op, ("provider_moved",), {"state": "completed"})
        del self.claims[op["appointment_id"]]
        return "completed"

    async def get_claim(self, aid):
        c = self.claims.get(aid)
        return {"appointment_id": aid, "operation_type": c["type"]} if c else None

    # reads and writes, each with a pause point first
    async def get_appt(self, aid):
        # The webhook's read of the time is a pause point. The move's reads of our
        # row are not: nothing but its own finish moves that row, and the status
        # the webhook writes doesn't change what the move does.
        if PROC.get() == "W":
            await self.sched.gate()
        return await super().get_appt(aid)

    async def paid(self, aid):
        await self.sched.gate()
        return await super().paid(aid)

    async def get_booking(self, token, bid):
        await self.sched.gate()
        return await super().get_booking(token, bid)

    async def update(self, *a, **k):
        await self.sched.gate()
        return await super().update(*a, **k)

    async def write_payment(self, pid, patch_):
        await self.sched.gate()
        self.payment_writes.append((pid, patch_))
        for p in self.payments:
            if p["id"] == pid:
                p.update(patch_)

    async def confirm(self, aid):
        await self.sched.gate()
        if self.appt["status"] == "cancelled":
            return False
        self.appt["status"] = "confirmed"
        return True

    async def send_sms(self, **k):
        await self.sched.gate()
        c = self.claims.get(self.appt["id"])
        self.sent.append((k["body"], _when(self.appt["appointment_datetime"]),
                          _when(self.booking["start_at"]), c and c["type"]))

    async def notify(self, tenant, payment, appointment=None):
        self.owner_notes.append(appointment)

    def pending(self):
        return next(p for p in self.payments if p["status"] == "pending")

    def env(self):
        outer = super().env()
        extra = [
            patch("db.supabase.get_payment_by_checkout_session",
                  new=AsyncMock(side_effect=lambda _s: dict(self.pending()))),
            patch("db.supabase.confirm_appointment_unless_cancelled", new=AsyncMock(side_effect=self.confirm)),
            patch("db.mutation_claims.get_claim", new=AsyncMock(side_effect=self.get_claim)),
            patch("services.mutation_ownership.acquire_for_confirmation",
                  new=AsyncMock(side_effect=self.acquire_confirmation)),
            patch("services.telephony.send_sms", new=AsyncMock(side_effect=self.send_sms)),
            patch.object(payments, "_notify_payment", new=AsyncMock(side_effect=self.notify)),
            patch.object(payments, "_emit_zapier_deposit", new=AsyncMock()),
            patch("services.booking_claims._now", lambda: NOW),   # move-operation timestamps
        ]
        self.tenant.update({"twilio_subaccount_sid": "AC", "twilio_auth_token": "t",
                            "twilio_phone_number": "+15550000000"})
        world = self

        class _Both:
            def __enter__(s):
                outer.__enter__()
                for p in extra:
                    p.start()
                return world

            def __exit__(s, *exc):
                for p in extra:
                    p.stop()
                return outer.__exit__(*exc)
        return _Both()

    async def webhook(self):
        p = self.pending()
        if self.provider == "square":
            await payments._handle_square_payment_completed({"data": {"object": {"payment": {
                "id": "sqpay", "order_id": "order-1", "status": "COMPLETED"}}}})
        else:
            await payments._handle_checkout_completed(
                {"id": "cs_1", "payment_intent": "pi_1",
                 "metadata": {"payment_id": p["id"], "tenant_id": sq.TID}})


OWED = [{"id": "p-1", "status": "pending", "appointment_id": "a-1", "caller_phone": sq.PHONE,
         "caller_name": "Sam", "service": "Consultation", "tenant_id": sq.TID,
         "amount_cents": 2000, "currency": "cad", "provider": "stripe"}]


def _paying_mid_move(w, then=None):
    """Square's update, followed by the deposit webhook: Square has the new time,
    our row still has the old one, and the move owns the appointment."""
    orig = w.update

    async def update_then_pay(*a, **k):
        res = await orig(*a, **k)
        await w.webhook()
        if then:
            then()
        return res
    return patch("services.square_booking.update_booking_start", new=AsyncMock(side_effect=update_then_pay))


# ════════════ 1. the confirmation never names a time being changed ═════════════

async def _race(order, *, lock=True):
    """The payment webhook (W) and a move (M) of the same appointment, released
    at their pause points in `order`."""
    w = PayWorld(status="pending_payment", payments=OWED, lock=lock)
    with w.env():
        await w.call()                              # the listing, outside the race
        w.sched = Sched(order)

        async def proc(name, fn):
            PROC.set(name)
            try:
                return await fn()
            finally:
                await w.sched.finish(name)
        _, said = await asyncio.wait_for(asyncio.gather(proc("W", w.webhook), proc("M", w.move)), 5)
    return w, said, dict(w.sched.counts)


async def _orders():
    """Every interleaving of the two processes' pause points."""
    _, _, w_first = await _race("W" * 99)
    _, _, m_first = await _race("M" * 99)
    nw, nm = max(w_first["W"], m_first["W"]), max(w_first["M"], m_first["M"])
    for ws in itertools.combinations(range(nw + nm), nw):
        yield "".join("W" if i in ws else "M" for i in range(nw + nm))


async def test_every_interleaving_names_only_a_settled_time():
    """At the moment the text is sent: if it names a time, our record and Square's
    copy are both at that time and the confirmation itself owns the appointment,
    so no move can be under way."""
    seen = {"names old time": 0, "names new time": 0, "no time": 0, "moved": 0, "move refused": 0}
    runs = 0
    async for order in _orders():
        w, said, _ = await _race(order)
        assert len(w.sent) == 1, order
        text, ours, squares, owner = w.sent[0]
        t = named_time(text)
        if t is not None:
            assert t == ours == squares, f"{order}: named {t}, record {ours}, Square {squares}"
            assert owner == db_mc.OP_PAYMENT_CONFIRMATION, f"{order}: sent while owned by {owner}"
        assert said.startswith("Done") or "being changed right now" in said, (order, said)
        assert not w.claims, f"{order}: every claim released"
        runs += 1
        seen["names old time" if t == SRC else "names new time" if t == TARGET else "no time"] += 1
        seen["moved" if w.moved() else "move refused"] += 1
    assert runs > 1000, runs
    assert all(seen.values()), f"every outcome is exercised: {seen}"


async def test_without_the_claim_some_interleaving_sends_a_stale_time():
    """The control: the same runs, with the confirmation owning nothing."""
    async for order in _orders():
        w, _, _ = await _race(order, lock=False)
        text, ours, squares, _owner = w.sent[0]
        t = named_time(text)
        if t is not None and not (t == ours == squares):
            return                                   # found one: the check has teeth
    pytest.fail("no interleaving produced a stale text without the claim")


@pytest.mark.parametrize("provider", ["stripe", "square"])
async def test_with_nothing_moving_the_confirmation_names_the_time(provider):
    with PayWorld(status="pending_payment", payments=OWED, provider=provider).env() as w:
        await w.webhook()
    assert named_time(w.sent[0][0]) == SRC and w.owner_notes[0]["id"] == "a-1"
    assert not w.claims


@pytest.mark.parametrize("provider", ["stripe", "square"])
async def test_a_payment_landing_mid_move_leaves_the_time_out(provider):
    with PayWorld(status="pending_payment", payments=OWED, provider=provider).env() as w:
        with _paying_mid_move(w):
            await w.call()
            said = await w.move()
    assert said.startswith("Done") and w.moved()
    assert named_time(w.sent[0][0]) is None and "is now confirmed" in w.sent[0][0]
    assert w.owner_notes == [None], "the owner's note leaves the time out too"
    assert w.appt["status"] == "confirmed" and not w.claims


async def test_a_confirmation_past_its_send_budget_leaves_the_time_out():
    """A webhook stalled close to its lease could be overtaken once the lease
    expires, so it stops naming the time."""
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        w.claim_age = db_mc.CONFIRMATION_LEASE_SECONDS - payments.CONFIRMATION_SEND_BUDGET_SECONDS + 1
        await w.webhook()
    assert named_time(w.sent[0][0]) is None and not w.claims


async def test_a_move_meeting_a_confirmation_moves_nothing():
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        await w.call()
        w.claims["a-1"] = {"token": "conf", "type": db_mc.OP_PAYMENT_CONFIRMATION}
        said = await w.move()
    assert "being changed right now" in said and w.updates == []


# ── the lease: a stopped webhook can't hold an appointment for ever ────────────

class _ClaimTable:
    def __init__(self, held_type, age):
        self.row = {"operation_type": held_type, "claimed_at": utcnow_iso(age)} if held_type else None

    async def insert(self, *a, **k):
        if self.row:
            return None
        self.row = {"claim_token": "new", "claimed_at": utcnow_iso(), "operation_type": "reschedule"}
        return self.row

    async def expire(self, appointment_id=None, limit=20):
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=db_mc.CONFIRMATION_LEASE_SECONDS)
        if (self.row and self.row["operation_type"] == db_mc.OP_PAYMENT_CONFIRMATION
                and _when(self.row["claimed_at"]) < cutoff):
            self.row = None
            return 1
        return 0


@pytest.mark.parametrize("held, age, expect", [
    (db_mc.OP_PAYMENT_CONFIRMATION, db_mc.CONFIRMATION_LEASE_SECONDS + 5, mo.ACQUIRED),
    (db_mc.OP_PAYMENT_CONFIRMATION, 10, mo.BUSY),
    ("cancel", 10_000, mo.BUSY),                    # other types never expire this way
])
async def test_only_an_expired_confirmation_gives_way(held, age, expect):
    t = _ClaimTable(held, age)
    with patch.object(db_mc, "acquire_reschedule_claim", new=AsyncMock(side_effect=t.insert)), \
         patch.object(db_mc, "expire_stale_confirmations", new=AsyncMock(side_effect=t.expire)):
        status, _ = await mo.acquire_for_reschedule("a-1", "t", "op-1")
    assert status == expect


async def test_recovery_sweeps_expired_confirmations():
    from services import calendar_reschedule as cr
    with patch.object(db_mc, "expire_stale_confirmations", new=AsyncMock(return_value=2)):
        out = await cr.run_recovery()
    assert out.get("confirmation_claims_expired") == 2


# ════════════ 2. a reschedule never reopens a closed refund window ══════════════

def move(frm, started, finished=None):
    return {"from_start_utc": frm.isoformat(), "created_at": started.isoformat(),
            "updated_at": (finished or started + timedelta(seconds=2)).isoformat()}


@pytest.mark.parametrize("case, appt_at, paid_at, moves, now, open_", [
    ("no move, outside the window", SRC, NOW, [], NOW, True),
    ("no move, inside the window", NOW + timedelta(hours=10), NOW, [], NOW, False),
    ("moved before the cutoff: refundable at the new time",
     TARGET, NOW, [move(SRC, NOW + timedelta(hours=1))], NOW + timedelta(hours=2), True),
    ("moved before the cutoff, later inside the NEW window",
     TARGET, NOW, [move(SRC, NOW + timedelta(hours=1))], TARGET - timedelta(hours=3), False),
    ("moved after the cutoff (Google/Outlook allow it; Square on the phone doesn't)",
     TARGET, NOW, [move(NOW + timedelta(hours=30), NOW + timedelta(hours=8))],
     NOW + timedelta(hours=9), False),
    ("paid during a move from a time already inside its window",
     TARGET, NOW, [move(NOW + timedelta(hours=10), NOW - timedelta(seconds=1))], NOW, False),
    ("paid during a move from a time still outside its window",
     TARGET, NOW, [move(SRC, NOW - timedelta(seconds=1))], NOW, True),
    ("repeated moves, each before its cutoff",
     TARGET + timedelta(days=7), NOW,
     [move(SRC, NOW + timedelta(hours=1)), move(TARGET, NOW + timedelta(days=2))],
     NOW + timedelta(days=3), True),
    ("repeated moves, the second after the first move's new cutoff",
     TARGET + timedelta(days=7), NOW,
     [move(SRC, NOW + timedelta(hours=1)), move(TARGET, TARGET - timedelta(hours=2))],
     TARGET, False),
    ("moved before the deposit was paid: not counted",
     TARGET, NOW, [move(NOW + timedelta(hours=10), NOW - timedelta(hours=1))], NOW, True),
    ("no payment time on record: every move counts",
     TARGET, None, [move(NOW + timedelta(hours=10), NOW - timedelta(hours=1))], NOW, False),
])
def test_refund_window_rule(case, appt_at, paid_at, moves, now, open_):
    assert refunds.refund_window_open(appt_at, 24, paid_at=paid_at, moves=moves, now=now) is open_, case


def _stamp_paid(w):
    def go():
        for p in w.payments:
            p["paid_at"] = sq.z(NOW)
    return go


async def test_a_deposit_paid_mid_move_inside_its_window_stays_closed_after_the_move():
    soon = NOW + timedelta(hours=10)
    with PayWorld(status="pending_payment", payments=OWED, src=soon).env() as w:
        with _paying_mid_move(w, then=_stamp_paid(w)):
            await w.call()
            assert (await w.move()).startswith("Done") and w.moved()
        paid = next(p for p in w.payments if p["status"] == "succeeded")
        refundable = await refunds.deposit_refundable(w.tenant, dict(w.appt), paid, 24, now=NOW)
    assert refundable is False
    assert refunds.refund_eligible(TARGET, 24, now=NOW) is True, "the old rule would have reopened it"


async def test_a_closed_window_also_stops_a_second_move():
    soon = NOW + timedelta(hours=10)
    with PayWorld(status="pending_payment", payments=OWED, src=soon).env() as w:
        with _paying_mid_move(w, then=_stamp_paid(w)):
            await w.call()
            await w.move()
        w.offer["start_at_utc"] = sq.z(TARGET + timedelta(days=1))
        w.offer_claimed = False
        w.refs.rows.clear()                          # a later call lists it afresh
        await w.call()
        again = await w.move()
    assert "cancellation window" in again and len(w.updates) == 1


async def test_an_unreadable_move_history_is_neither_refunded_nor_forfeited(calendar_moves_store):
    calendar_moves_store.fail = True
    appt = {"id": "a-1", "appointment_datetime": SRC.isoformat()}
    assert await refunds.deposit_refundable({}, appt, {"paid_at": sq.z(NOW)}, 24, now=NOW) is None


# ════════════ 3. a booking moved directly in Square ═════════════════════════════

SQ_TENANT = {"square_appointments_enabled": True}


def _appt(**k):
    return {"id": "a-1", "appointment_datetime": TARGET.isoformat(), "google_event_id": "BK-1", **k}


@pytest.mark.parametrize("case, appt, square_start, expect", [
    ("no change in Square", _appt(), TARGET, True),
    ("changed in Square after the deposit was paid",
     _appt(provider_time_changed_at=(NOW + timedelta(hours=1)).isoformat()), TARGET, None),
    ("changed in Square before the deposit was paid",
     _appt(provider_time_changed_at=(NOW - timedelta(hours=1)).isoformat()), TARGET, True),
    ("moved in Square, its webhook not processed yet", _appt(), TARGET + timedelta(hours=2), None),
    ("Square's copy unreadable", _appt(), None, None),
])
async def test_square_side_moves_go_to_the_team(case, appt, square_start, expect):
    fetch = (sb.FETCH_FOUND, {"start_at": sq.z(square_start)}) if square_start else (sb.FETCH_UNKNOWN, {})
    with patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")), \
         patch("services.square_booking.get_booking_detailed", new=AsyncMock(return_value=fetch)):
        got = await refunds.deposit_refundable(SQ_TENANT, appt, {"paid_at": sq.z(NOW)}, 24, now=NOW)
    assert got is expect, case


@pytest.mark.parametrize("stored, incoming, stamped", [
    ("2026-11-06T14:00:00+00:00", "2026-11-06T16:00:00Z", True),     # moved
    ("2026-11-06T14:00:00+00:00", "2026-11-06T14:00:00Z", False),    # same instant, other format
])
async def test_the_booking_webhook_stamps_a_time_change(stored, incoming, stamped):
    existing = {"id": "a-1", "appointment_datetime": stored, "tenant_location_id": "l",
                "provider_location_id": "L"}
    written = []
    with patch("db.supabase.reconcile_appointment_if_newer",
               new=AsyncMock(side_effect=lambda aid, v, p: written.append(p) or True)):
        await recon._update_existing(existing, {"start_at": incoming}, {"provider_location_id": "L"},
                                     "t", "l", 5, "2026-11-03T12:00:00Z", False)
    assert ("provider_time_changed_at" in written[0]) is stamped
    if stamped:
        assert written[0]["provider_time_changed_at"] == "2026-11-03T12:00:00Z"


def test_a_booking_event_meeting_a_confirmation_is_retried():
    assert recon.Outcome(recon.DEFERRED_CONFIRMING).should_retry
    assert not recon.Outcome(recon.DEFERRED_OWNED).should_retry


# ── the cancel tool, end to end ──────────────────────────────────────────────

class _Cancel(w6a1.Ctx):
    def __init__(self, when, payment, square_start=None):
        a = w6a1.appt("a-cork", when=when.isoformat())
        booking = {"id": "BK-CORK", "status": "ACCEPTED", "location_id": w6a1.CORK_PID, "version": 0,
                   "start_at": (square_start or when).isoformat()}
        super().__init__(candidates=[a], booking=booking)
        self.payment = payment
        self.refunded, self.forfeit, self.team = [], [], []

    def __enter__(self):
        super().__enter__()
        self._q = [
            patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=self.payment)),
            patch("services.refunds.issue_provider_refund",
                  new=AsyncMock(side_effect=lambda *a: self.refunded.append(1) or True)),
            patch("services.refunds.sms_caller_refund", new=AsyncMock()),
            patch("services.refunds.sms_caller_cancelled",
                  new=AsyncMock(side_effect=lambda *a, **k: self.forfeit.append(k))),
            patch("services.refunds.notify_business",
                  new=AsyncMock(side_effect=lambda *a, **k: self.team.append(k))),
            patch("db.supabase.update_payment", new=AsyncMock()),
        ]
        for p in self._q:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._q:
            p.stop()
        return super().__exit__(*a)


def _paid(days_ago=2):
    return {"id": "p-1", "status": "succeeded", "amount_cents": 2000, "currency": "cad",
            "paid_at": utcnow_iso(days_ago * 86400)}


async def test_cancel_after_a_window_closing_move_forfeits(calendar_moves_store):
    real_now = datetime.now(timezone.utc)
    calendar_moves_store.rows["op-1"] = {"id": "op-1", "appointment_id": "a-cork", "state": "completed",
                                         **move(real_now - timedelta(hours=2), real_now - timedelta(hours=3))}
    with _Cancel(real_now + timedelta(days=3), _paid()) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [] and "non-refundable" in said
    assert c.forfeit and c.forfeit[0].get("deposit_forfeited") is True


async def test_cancel_after_an_ordinary_move_still_refunds(calendar_moves_store):
    real_now = datetime.now(timezone.utc)
    calendar_moves_store.rows["op-1"] = {"id": "op-1", "appointment_id": "a-cork", "state": "completed",
                                         **move(real_now + timedelta(days=2), real_now - timedelta(hours=3))}
    with _Cancel(real_now + timedelta(days=3), _paid()) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [1] and "will be refunded" in said


@pytest.mark.parametrize("why", ["history unreadable", "moved in Square"])
async def test_cancel_the_team_decides(why, calendar_moves_store):
    later = datetime.now(timezone.utc) + timedelta(days=3)
    square_start = later + timedelta(hours=2) if why == "moved in Square" else None
    calendar_moves_store.fail = why == "history unreadable"
    with _Cancel(later, _paid(), square_start=square_start) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [] and c.forfeit == [] and c.team, "neither refunded nor forfeited"
    assert "team will follow up" in said and "non-refundable" not in said
