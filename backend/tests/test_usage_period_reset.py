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
from tests.usage_rules import UsageRow

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

    add, roll, overage = UsageRow(row).patches()
    with patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec"), \
            patch.object(billing.stripe.Webhook, "construct_event", MagicMock()), \
            patch.object(billing.db, "get_tenant_by_stripe_customer", AsyncMock(side_effect=lambda _c: dict(row))), \
            patch.object(billing.db, "update_tenant", AsyncMock(side_effect=update)), add, roll, overage:
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


async def record_call(row, stripe_start, secs=60, today=None):
    live = {"current_period_start": stripe_start}
    add, roll, overage = UsageRow(row).patches()
    with patch.object(usage.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _i: dict(row))), add, roll, overage, \
            patch.object(usage, "_stripe_key", "sk"), patch.object(usage, "_overage_price_id", ""), \
            patch.object(usage.stripe.Subscription, "retrieve", MagicMock(return_value=live)):
        await usage.record_call_minutes("t1", secs)
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


def event_at(period_start, status="active"):
    """The real fixture, moved to another period."""
    event = json.loads(json.dumps(EVENT))
    event["data"]["object"]["items"]["data"][0]["current_period_start"] = period_start
    event["data"]["object"]["status"] = status
    return event


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


@pytest.mark.asyncio
@pytest.mark.parametrize("old,new", [
    ("2026-01-31", "2026-02-28"),  # a shorter month
    ("2026-02-28", "2026-03-31"),
    ("2026-12-31", "2027-01-31"),  # a new year
    ("2028-02-29", "2028-03-29"),  # a leap day
], ids=["short month", "month end", "year end", "leap day"])
async def test_monthly_boundaries_reset_once(old, new):
    row = await deliver(tenant(billing_period_anchor=old), event_at(ts(new)))
    assert (row["minutes_used_this_period"], row["billing_period_anchor"]) == (0, new)
    row["minutes_used_this_period"] = 9
    await deliver(row, event_at(ts(new)))
    assert row["minutes_used_this_period"] == 9


@pytest.mark.asyncio
async def test_an_annual_renewal_resets_once():
    row = await deliver(tenant(billing_period_anchor="2026-03-01"), event_at(ts("2027-03-01")))
    assert (row["minutes_used_this_period"], row["billing_period_anchor"]) == (0, "2027-03-01")


@pytest.mark.asyncio
async def test_an_annual_plan_does_not_reset_on_a_mid_year_update():
    # An annual subscription gets updates all year with the same period start.
    row = await deliver(tenant(billing_period_anchor="2026-03-01"), event_at(ts("2026-03-01")))
    assert row["minutes_used_this_period"] == 120


@pytest.mark.asyncio
async def test_calls_after_28_days_do_not_reset_inside_an_annual_period():
    start = ts("2026-01-01")
    row = await record_call(tenant(billing_period_anchor="2026-01-01"), start)
    assert row["minutes_used_this_period"] == 121
    assert row["billing_period_anchor"] == "2026-01-01"


@pytest.mark.asyncio
async def test_a_call_that_sees_the_new_period_first_survives_the_webhook():
    # The race that erased usage: the call lands in the new period before the event.
    row = await record_call(tenant(billing_period_anchor="2026-01-01"), ts("2026-02-01"), secs=300)
    assert row["minutes_used_this_period"] == 5
    await deliver(row, event_at(ts("2026-02-01")))
    assert row["minutes_used_this_period"] == 5


@pytest.mark.asyncio
async def test_a_call_after_the_webhook_counts_in_the_new_period():
    row = await deliver(tenant(billing_period_anchor="2026-01-01"), event_at(ts("2026-02-01")))
    await record_call(row, ts("2026-02-01"), secs=120)
    assert row["minutes_used_this_period"] == 2


@pytest.mark.asyncio
async def test_a_stripe_outage_during_a_call_still_records_it():
    row = tenant(billing_period_anchor="2026-01-01")
    add, roll, overage = UsageRow(row).patches()
    with patch.object(usage.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _i: dict(row))), add, roll, overage, \
            patch.object(usage, "_stripe_key", "sk"), patch.object(usage, "_overage_price_id", ""), \
            patch.object(usage.stripe.Subscription, "retrieve", MagicMock(side_effect=RuntimeError("down"))):
        await usage.record_call_minutes("t1", 60)
    assert row["minutes_used_this_period"] == 121


@pytest.mark.asyncio
async def test_overage_reported_in_an_old_period_does_not_leak_into_the_new_one():
    row = tenant(billing_period_anchor="2026-02-01", overage_minutes_reported=0)
    await UsageRow(row).add_overage("t1", 5, "2026-01-01")
    assert row["overage_minutes_reported"] == 0
