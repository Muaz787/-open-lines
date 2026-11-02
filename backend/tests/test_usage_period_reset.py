"""Usage resets once per billing period, on the Stripe API version live webhooks use.

The fixture is a real customer.subscription.updated captured at a test-clock rollover
on 2026-04-22.dahlia, with ids replaced. That version has no top-level
current_period_start: the period lives on each subscription item.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routers import billing
from services import usage

EVENT = json.loads((Path(__file__).parent / "fixtures/stripe_dahlia_subscription_rollover.json").read_text())
SUB = EVENT["data"]["object"]
ITEM = SUB["items"]["data"][0]


def day(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


NEW = day(ITEM["current_period_start"])
OLD = day(EVENT["data"]["previous_attributes"]["items"]["data"][0]["current_period_start"])


def tenant(**over):
    return {"id": "t1", "stripe_customer_id": SUB["customer"], "stripe_subscription_id": SUB["id"],
            "subscription_status": "active", "subscription_plan": "pro", "minutes_used_this_period": 120,
            "overage_minutes_reported": 5, "billing_period_anchor": OLD, **over}


class Request:
    headers = {"stripe-signature": "sig"}

    def __init__(self, event):
        self._body = json.dumps(event).encode()

    async def body(self):
        return self._body


async def deliver(row, event=EVENT):
    async def update(_id, change):
        row.update(change)
        return row

    with patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec"), \
            patch.object(billing.stripe.Webhook, "construct_event", MagicMock()), \
            patch.object(billing.db, "get_tenant_by_stripe_customer", AsyncMock(side_effect=lambda _c: dict(row))), \
            patch.object(billing.db, "update_tenant", AsyncMock(side_effect=update)):
        await billing.stripe_webhook(Request(event))
    return row


def test_the_fixture_is_the_live_shape():
    assert EVENT["api_version"] == "2026-04-22.dahlia"
    assert "current_period_start" not in SUB or SUB["current_period_start"] is None
    assert ITEM["current_period_start"]
    assert OLD != NEW


@pytest.mark.asyncio
async def test_a_rollover_resets_usage():
    row = await deliver(tenant())
    assert row["minutes_used_this_period"] == 0
    assert row["overage_minutes_reported"] == 0
    assert row["billing_period_anchor"] == NEW


@pytest.mark.asyncio
async def test_a_duplicate_event_does_not_reset_twice():
    row = await deliver(tenant())
    row["minutes_used_this_period"] = 7
    await deliver(row)
    assert row["minutes_used_this_period"] == 7


@pytest.mark.asyncio
async def test_a_late_redelivery_of_an_old_period_does_not_reset():
    row = tenant(billing_period_anchor="2099-01-01", minutes_used_this_period=7)
    await deliver(row)
    assert row["minutes_used_this_period"] == 7
    assert row["billing_period_anchor"] == "2099-01-01"


@pytest.mark.asyncio
async def test_a_missing_anchor_is_recorded_without_wiping_usage():
    row = await deliver(tenant(billing_period_anchor=None))
    assert row["minutes_used_this_period"] == 120
    assert row["billing_period_anchor"] == NEW


@pytest.mark.asyncio
async def test_another_subscription_on_the_customer_changes_nothing():
    row = await deliver(tenant(stripe_subscription_id="sub_other"))
    assert row["minutes_used_this_period"] == 120


@pytest.mark.asyncio
async def test_a_trial_that_converts_on_its_own_starts_paid_usage_clean():
    # Stripe ends the trial with no call through convert_card_trial, so this event is
    # the only thing that gives the paid period its full allowance.
    row = await deliver(tenant(subscription_status="trialing", minutes_used_this_period=60))
    assert row["minutes_used_this_period"] == 0


async def record_call(row, stripe_start):
    async def update(_id, change):
        row.update(change)
        return row

    live = SimpleNamespace(current_period_start=stripe_start)
    with patch.object(usage.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _i: dict(row))), \
            patch.object(usage.db, "update_tenant", AsyncMock(side_effect=update)), \
            patch.object(usage, "_stripe_key", "sk"), patch.object(usage, "_overage_price_id", ""), \
            patch.object(usage.stripe.Subscription, "retrieve", MagicMock(return_value=live)):
        await usage.record_call_minutes("t1", 60)
    return row


@pytest.mark.asyncio
async def test_the_next_call_resets_if_the_webhook_never_arrived():
    row = await record_call(tenant(billing_period_anchor="2026-01-01"), ITEM["current_period_start"])
    assert row["minutes_used_this_period"] == 1
    assert row["billing_period_anchor"] == NEW


@pytest.mark.asyncio
async def test_a_call_records_a_missing_anchor_so_the_period_can_ever_reset():
    # Subscriptions from /create-subscription start with no anchor.
    row = await record_call(tenant(billing_period_anchor=None), ITEM["current_period_start"])
    assert row["billing_period_anchor"] == NEW
    assert row["minutes_used_this_period"] == 121
