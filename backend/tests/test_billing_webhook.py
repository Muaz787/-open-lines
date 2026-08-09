"""The Stripe billing webhook — the path a natural trial conversion takes.

Every customer who does NOT hit the 60-minute cap converts here: Stripe ends the
trial on day 7 and fires customer.subscription.updated. services/trial's
convert_card_trial() is not involved, so none of its tests cover this, and until
now nothing did.

The load-bearing assertion is the minute-counter reset. If it doesn't fire, the
tenant carries their trial minutes into the month they are now paying for and
gets billed for them.
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers import billing
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())

# 2026-08-09 and 2026-08-16 — a week apart, so the derived %Y-%m-%d anchors differ.
TRIAL_START = 1_786_000_000
TRIAL_END   = TRIAL_START + 7 * 86_400


def _anchor(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


class _Request:
    """Minimal stand-in for a FastAPI Request. The handler only needs raw bytes
    and the signature header."""
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode()
        self.headers = {"stripe-signature": "t=1,v1=fake"}

    async def body(self) -> bytes:
        return self._raw


def _tenant(**over):
    return {
        "id": "t1", "business_name": "Acme", "email": "a@b.com",
        "stripe_subscription_id": "sub_1", "stripe_customer_id": "cus_1",
        "subscription_status": "trialing", "subscription_plan": "pro",
        "billing_period_anchor": _anchor(TRIAL_START),
        "minutes_used_this_period": 25,
        "stripe_trial_ends_at": "2026-08-16T00:00:00+00:00",
        **over,
    }


async def _fire(event: dict, tenant: dict | None):
    """Run the webhook and return the dict written to update_tenant (or None)."""
    with patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": "whsec_test"}), \
         patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec_test"), \
         patch("stripe.Webhook.construct_event", MagicMock()), \
         patch("services.analytics.capture", MagicMock()), \
         patch("services.email.send_card_trial_email", new=AsyncMock(return_value=True)), \
         patch("db.supabase.get_tenant_by_stripe_customer", new=AsyncMock(return_value=tenant)), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await billing.stripe_webhook(_Request(event))

    assert res == {"status": "ok"}
    return [c.args[1] for c in upd.call_args_list]


def _sub_updated(status="active", period_start=TRIAL_END, trial_end=None):
    return {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "status": status,
            "current_period_start": period_start,
            "trial_end": trial_end,
        }},
    }


# ── The reset that matters ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_natural_conversion_resets_the_minute_counter():
    """Day 7: Stripe ends the trial and moves current_period_start forward. The
    tenant's 25 trial minutes must NOT be carried into the month they now pay for."""
    writes = await _fire(_sub_updated(), _tenant())
    merged = {k: v for w in writes for k, v in w.items()}

    assert merged["minutes_used_this_period"] == 0
    assert merged["overage_minutes_reported"] == 0
    assert merged["billing_period_anchor"] == _anchor(TRIAL_END)
    assert merged["subscription_status"] == "active"


@pytest.mark.asyncio
async def test_a_same_day_conversion_does_not_reset():
    """Documents a real artifact rather than asserting desired behaviour: the reset
    compares %Y-%m-%d anchors, so ending a trial on the day it started leaves them
    equal and skips the reset. Harmless in production (a 7-day trial always spans
    dates) but it makes a same-day smoke test look like a failure."""
    writes = await _fire(_sub_updated(period_start=TRIAL_START), _tenant())
    merged = {k: v for w in writes for k, v in w.items()}

    assert "minutes_used_this_period" not in merged


@pytest.mark.asyncio
async def test_conversion_is_recorded_for_the_reclaim_and_dunning_logic():
    writes = await _fire(_sub_updated(), _tenant())
    merged = {k: v for w in writes for k, v in w.items()}

    # Gates a bounced FIRST charge without touching customers in normal dunning.
    assert merged["trial_conversion_unpaid"] is True
    # Stripe ended this one itself, so the reason is time rather than the cap.
    assert merged["trial_converted_reason"] == "time"
    # A stale date would keep making a paid tenant look like a trial.
    assert merged["stripe_trial_ends_at"] is None


@pytest.mark.asyncio
async def test_an_existing_reason_is_not_overwritten():
    """A tenant auto-converted at the minute cap already carries 'minutes'."""
    writes = await _fire(_sub_updated(), _tenant(trial_converted_reason="minutes"))
    merged = {k: v for w in writes for k, v in w.items()}
    assert "trial_converted_reason" not in merged


@pytest.mark.asyncio
async def test_a_trialing_update_keeps_the_trial_end_date_fresh():
    writes = await _fire(
        _sub_updated(status="trialing", period_start=TRIAL_START, trial_end=TRIAL_END),
        _tenant(),
    )
    merged = {k: v for w in writes for k, v in w.items()}
    assert merged["subscription_status"] == "trialing"
    assert merged["stripe_trial_ends_at"].startswith("2026-")
    assert "trial_conversion_unpaid" not in merged   # still trialing, not converted


@pytest.mark.asyncio
async def test_a_stale_subscription_id_is_ignored():
    """A cancelled-then-resubscribed tenant must not be rewritten by events from
    the old subscription."""
    writes = await _fire(_sub_updated(), _tenant(stripe_subscription_id="sub_OTHER"))
    assert writes == []


@pytest.mark.asyncio
async def test_cancellation_stamps_the_reclaim_anchor():
    """subscription_canceled_at is what the number-reclaim sweep counts 60 days
    from; without it a former customer is left alone forever."""
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_1", "customer": "cus_1"}},
    }
    writes = await _fire(event, _tenant(subscription_status="active"))
    merged = {k: v for w in writes for k, v in w.items()}

    assert merged["subscription_status"] == "canceled"
    assert merged["subscription_plan"] is None
    assert merged["subscription_canceled_at"]


# ── Invoice events ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_payment_clears_the_gate_and_marks_them_a_customer():
    event = {
        "type": "invoice.payment_succeeded",
        "data": {"object": {"customer": "cus_1", "amount_paid": 22487, "currency": "cad"}},
    }
    writes = await _fire(event, _tenant(subscription_status="active", trial_conversion_unpaid=True))
    merged = {k: v for w in writes for k, v in w.items()}

    # Unblocks the line: they have now actually paid.
    assert merged["trial_conversion_unpaid"] is False
    # Earns the 60-day reclaim grace instead of 30 — this is the only thing that
    # distinguishes a departed customer from a trial that never converted.
    assert merged["first_paid_at"]


@pytest.mark.asyncio
async def test_first_paid_at_is_written_once_not_on_every_invoice():
    event = {
        "type": "invoice.payment_succeeded",
        "data": {"object": {"customer": "cus_1", "amount_paid": 22487, "currency": "cad"}},
    }
    writes = await _fire(event, _tenant(subscription_status="active", first_paid_at="2026-01-01T00:00:00+00:00"))
    merged = {k: v for w in writes for k, v in w.items()}
    assert "first_paid_at" not in merged


@pytest.mark.asyncio
async def test_a_failed_invoice_does_not_change_status_here():
    """Status is owned by customer.subscription.updated; this handler exists for
    the invoice context and the notice."""
    event = {
        "type": "invoice.payment_failed",
        "data": {"object": {"customer": "cus_1", "amount_due": 22487, "attempt_count": 1}},
    }
    writes = await _fire(event, _tenant(subscription_status="past_due", trial_conversion_unpaid=True))
    merged = {k: v for w in writes for k, v in w.items()}
    assert "subscription_status" not in merged


@pytest.mark.asyncio
async def test_an_unknown_event_type_is_a_no_op():
    writes = await _fire({"type": "customer.updated", "data": {"object": {}}}, _tenant())
    assert writes == []
