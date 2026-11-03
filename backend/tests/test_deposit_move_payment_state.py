"""
Issue #179 — a deposit's payment and a move of its appointment, together.

All of this is MOCKED. No Square, Stripe or Twilio call is made: the payment
webhooks, the move and the cancellation run against in-memory fakes. The real
Square booking-update contract is checked only by tests/test_square_sandbox_update.py.

  1. a payment confirmation never names a time a move is changing:
     the webhook leaves the time out when a move owns the appointment, has a live
     operation, or the time changed while it looked; a move waits for a deposit
     paid moments ago. Both interleavings are run.
  2. a reschedule never reopens a refund window that had closed
     (services.refunds.refund_window_open), at cancellation and for a later move.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from routers import payments
from services import calendar_reschedule as cr, refunds
from tests import test_square_deposit_reschedule as sq
from tests import test_w6a1_safe_cancellation as w6a1

NOW, SRC, TARGET = sq.NOW, sq.SRC, sq.TARGET
H = timedelta(hours=24)


class PayWorld(sq.SqWorld):
    """SqWorld plus the deposit webhooks: the payment row, the claim lookup they
    read, and the texts they send."""

    def __init__(self, *a, provider="stripe", **k):
        super().__init__(*a, **k)
        self.provider = provider
        self.sms, self.owner = [], []
        self.during_update = None    # a coroutine to run while Square is moving the booking
        self.during_claim_check = None

    def pending(self):
        return next(p for p in self.payments if p["status"] == "pending")

    async def write_payment(self, pid, patch_):
        self.payment_writes.append((pid, patch_))
        for p in self.payments:
            if p["id"] == pid:
                p.update(patch_)
                p["paid_at"] = sq.z(NOW)    # the webhook's clock, pinned

    async def update(self, *a, **k):
        res = await super().update(*a, **k)
        if self.during_update and self.updates:
            hook, self.during_update = self.during_update, None
            await hook()
        return res

    async def get_claim(self, aid):
        if self.during_claim_check:
            hook, self.during_claim_check = self.during_claim_check, None
            await hook()
        return {"appointment_id": aid} if aid in self.owners else None

    async def confirm(self, aid):
        if self.appt["status"] == "cancelled":
            return False
        self.appt["status"] = "confirmed"
        return True

    async def send_sms(self, **k):
        self.sms.append(k["body"])

    async def notify(self, tenant, payment, appointment=None):
        self.owner.append(appointment)

    def env(self):
        outer = super().env()
        extra = [
            patch("db.supabase.get_payment_by_checkout_session",
                  new=AsyncMock(side_effect=lambda _s: dict(self.pending()))),
            patch("db.supabase.confirm_appointment_unless_cancelled",
                  new=AsyncMock(side_effect=self.confirm)),
            patch("db.mutation_claims.get_claim", new=AsyncMock(side_effect=self.get_claim)),
            patch("services.telephony.send_sms", new=AsyncMock(side_effect=self.send_sms)),
            patch.object(payments, "_notify_payment", new=AsyncMock(side_effect=self.notify)),
            patch.object(payments, "_emit_zapier_deposit", new=AsyncMock()),
            patch("services.booking_claims._now", lambda: NOW),   # operation timestamps
        ]
        self.tenant.update({"twilio_subaccount_sid": "AC", "twilio_auth_token": "t",
                            "twilio_phone_number": "+15550000000"})

        class _Both:
            def __enter__(s):
                w = outer.__enter__()
                for p in extra:
                    p.start()
                return w

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


def names_a_time(text):
    return " at " in text and ("AM" in text or "PM" in text)


# ════════════════ 1. the confirmation never names a time being changed ═══════════

@pytest.mark.parametrize("provider", ["stripe", "square"])
async def test_with_nothing_moving_the_confirmation_names_the_time(provider):
    with PayWorld(status="pending_payment", payments=OWED, provider=provider).env() as w:
        await w.webhook()
    assert len(w.sms) == 1 and names_a_time(w.sms[0]), w.sms
    assert w.owner == [w.appt | {"status": "confirmed"}]


@pytest.mark.parametrize("provider", ["stripe", "square"])
async def test_a_payment_landing_mid_move_leaves_the_time_out(provider):
    """The move owns the appointment and Square has the new time, but our row
    still has the old one. The text must not announce the old time."""
    with PayWorld(status="pending_payment", payments=OWED, provider=provider).env() as w:
        w.during_update = w.webhook
        await w.call()
        said = await w.move()
    assert said.startswith("Done") and w.moved()
    assert len(w.sms) == 1 and not names_a_time(w.sms[0]), w.sms
    assert "is now confirmed" in w.sms[0]
    assert w.owner == [None], "the owner's note leaves the time out too"
    assert w.appt["status"] == "confirmed"


async def test_a_live_operation_without_a_claim_also_leaves_the_time_out(calendar_moves_store):
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        calendar_moves_store.rows["op-x"] = {"id": "op-x", "appointment_id": "a-1", "state": "unknown"}
        await w.webhook()
    assert len(w.sms) == 1 and not names_a_time(w.sms[0])


async def test_a_time_that_changes_while_the_webhook_looks_is_left_out():
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        async def moved_meanwhile():
            w.appt["appointment_datetime"] = TARGET.isoformat()
        w.during_claim_check = moved_meanwhile
        await w.webhook()
    assert len(w.sms) == 1 and not names_a_time(w.sms[0])


async def test_an_unreadable_claim_leaves_the_time_out():
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        with patch("db.mutation_claims.get_claim", new=AsyncMock(side_effect=RuntimeError("down"))):
            await w.webhook()
    assert len(w.sms) == 1 and not names_a_time(w.sms[0])


async def test_payment_first_then_a_move_before_the_webhook_looks():
    """The other interleaving: the payment is marked paid, then a move takes
    ownership before the webhook checks for an owner. The move must see the
    fresh payment and wait, so the time the text names stays true."""
    with PayWorld(status="pending_payment", payments=OWED).env() as w:
        await w.call()
        results = []

        async def move_now():
            results.append(await w.move())
        w.during_claim_check = move_now
        await w.webhook()
    assert w.updates == [] and not w.moved(), "nothing was moved"
    assert "just come through" in results[0] and not w.owners
    assert len(w.sms) == 1 and names_a_time(w.sms[0]), "the time it names is still the booked time"


async def test_once_the_deposit_has_settled_the_move_goes_ahead():
    paid = [dict(OWED[0], status="succeeded", paid_at=sq.z(NOW - timedelta(minutes=5)))]
    with PayWorld(payments=paid).env() as w:
        await w.call()
        said = await w.move()
    assert said.startswith("Done") and w.moved()


@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_google_and_outlook_moves_also_wait_for_a_fresh_deposit(provider):
    from tests import test_reschedule_all_providers as allp
    fresh = {"id": "p-1", "status": "succeeded", "paid_at": allp.NOW.isoformat()}
    with allp.CalWorld(provider, [allp.appointment()]).env() as w:
        with patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=fresh)):
            await w.call()
            said = await w.move()
    assert "just come through" in said and w.patches == [] and not w.owners


# ═════════════════ 2. a reschedule never reopens a closed refund window ═══════════

def move(frm, started, finished=None):
    return {"from_start_utc": frm.isoformat(), "created_at": started.isoformat(),
            "updated_at": (finished or started + timedelta(seconds=2)).isoformat()}


@pytest.mark.parametrize("case, appt_at, paid_at, moves, now, open_", [
    ("no move, outside the window", SRC, NOW, [], NOW, True),
    ("no move, inside the window", NOW + timedelta(hours=10), NOW, [], NOW, False),
    ("moved while open: refundable at the new time",
     TARGET, NOW, [move(SRC, NOW + timedelta(hours=1))], NOW + timedelta(hours=2), True),
    ("moved while open, later inside the NEW window",
     TARGET, NOW, [move(SRC, NOW + timedelta(hours=1))], TARGET - timedelta(hours=3), False),
    ("paid during a move from a time already inside its window",
     TARGET, NOW, [move(NOW + timedelta(hours=10), NOW - timedelta(seconds=1))], NOW, False),
    ("paid during a move from a time still outside its window",
     TARGET, NOW, [move(SRC, NOW - timedelta(seconds=1))], NOW, True),
    ("moved inside the window by another route after paying",
     TARGET, NOW, [move(NOW + timedelta(hours=30), NOW + timedelta(hours=8))],
     NOW + timedelta(hours=9), False),
    ("moved before the deposit was paid: not counted",
     TARGET, NOW, [move(NOW + timedelta(hours=10), NOW - timedelta(hours=1))], NOW, True),
    ("no payment time on record: every move counts",
     TARGET, None, [move(NOW + timedelta(hours=10), NOW - timedelta(hours=1))], NOW, False),
])
def test_refund_window_rule(case, appt_at, paid_at, moves, now, open_):
    assert refunds.refund_window_open(appt_at, 24, paid_at=paid_at, moves=moves, now=now) is open_, case


async def test_a_deposit_paid_mid_move_inside_its_window_stays_closed_after_the_move(calendar_moves_store):
    """Owed deposit, appointment 10 hours away: it may move (nothing is paid). The
    payment lands mid-move, while the time it moves FROM is inside the window.
    At the new, later time it must not have become refundable."""
    soon = NOW + timedelta(hours=10)
    with PayWorld(status="pending_payment", payments=OWED, src=soon).env() as w:
        w.during_update = w.webhook
        await w.call()
        assert (await w.move()).startswith("Done") and w.moved()
        paid = next(p for p in w.payments if p["status"] == "succeeded")
        refundable = await refunds.deposit_refundable("a-1", TARGET, paid, 24, now=NOW)
    assert refundable is False
    assert refunds.refund_eligible(TARGET, 24, now=NOW) is True, "the old rule would have reopened it"


async def test_a_closed_window_also_stops_a_second_move(calendar_moves_store):
    soon = NOW + timedelta(hours=10)
    with PayWorld(status="pending_payment", payments=OWED, src=soon).env() as w:
        w.during_update = w.webhook
        await w.call()
        await w.move()
        # Later, the caller asks to move it again, now that the payment has settled.
        for p in w.payments:
            p["paid_at"] = sq.z(NOW - timedelta(minutes=10))
        w.offer["start_at_utc"] = sq.z(TARGET + timedelta(days=1))
        w.offer_claimed = False
        w.booking["start_at"] = sq.z(TARGET)
        w.refs.rows.clear()                          # a later call lists it afresh
        await w.call()
        again = await w.move()
    assert "cancellation window" in again and len(w.updates) == 1


async def test_an_unreadable_move_history_is_neither_refunded_nor_forfeited(calendar_moves_store):
    calendar_moves_store.fail = True
    paid = {"id": "p-1", "status": "succeeded", "paid_at": sq.z(NOW)}
    assert await refunds.deposit_refundable("a-1", SRC, paid, 24, now=NOW) is None


class _Cancel(w6a1.Ctx):
    def __init__(self, when, payment):
        a = w6a1.appt("a-cork", when=when.isoformat())
        super().__init__(candidates=[a])
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


async def test_cancelling_after_a_window_closing_move_forfeits_the_deposit(calendar_moves_store):
    real_now = datetime.now(timezone.utc)
    later = real_now + timedelta(days=3)
    calendar_moves_store.rows["op-1"] = {
        "id": "op-1", "appointment_id": "a-cork", "state": "completed",
        **move(real_now - timedelta(hours=2), real_now - timedelta(hours=3))}
    payment = {"id": "p-1", "status": "succeeded", "amount_cents": 2000, "currency": "cad",
               "paid_at": (real_now - timedelta(days=2)).isoformat()}
    with _Cancel(later, payment) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [] and "non-refundable" in said
    assert c.forfeit and c.forfeit[0].get("deposit_forfeited") is True


async def test_cancelling_with_unreadable_history_goes_to_the_team(calendar_moves_store):
    calendar_moves_store.fail = True
    later = datetime.now(timezone.utc) + timedelta(days=3)
    payment = {"id": "p-1", "status": "succeeded", "amount_cents": 2000, "currency": "cad"}
    with _Cancel(later, payment) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [] and c.forfeit == [] and c.team, "neither refunded nor forfeited"
    assert "team will follow up" in said and "non-refundable" not in said


async def test_cancelling_after_an_ordinary_move_still_refunds(calendar_moves_store):
    real_now = datetime.now(timezone.utc)
    later = real_now + timedelta(days=3)
    calendar_moves_store.rows["op-1"] = {
        "id": "op-1", "appointment_id": "a-cork", "state": "completed",
        **move(real_now + timedelta(days=2), real_now - timedelta(hours=3))}
    payment = {"id": "p-1", "status": "succeeded", "amount_cents": 2000, "currency": "cad",
               "paid_at": (real_now - timedelta(days=2)).isoformat()}
    with _Cancel(later, payment) as c:
        await c.call()
        said = c.text(await c.call(ref="appt_1"))
    assert c.refunded == [1] and "will be refunded" in said


def test_deposit_settling_window(monkeypatch):
    from services import relative_dates
    monkeypatch.setattr(relative_dates, "_utcnow", lambda: NOW)
    assert cr.deposit_settling(None) is False
    assert cr.deposit_settling({"paid_at": None}) is False
    assert cr.deposit_settling({"paid_at": (NOW - timedelta(seconds=30)).isoformat()}) is True
    assert cr.deposit_settling({"paid_at": (NOW - timedelta(minutes=5)).isoformat()}) is False
