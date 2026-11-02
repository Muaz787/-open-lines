"""One billing period at a time, on the Stripe API version live webhooks use.

The fixture is a real customer.subscription.updated captured at a test-clock rollover
on 2026-04-22.dahlia, with ids replaced. That version has no top-level
current_period_start: the period lives on each subscription item.

A call belongs to the period containing its end time, however late it's processed.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe

from routers import billing
from services import subscriptions, usage
from tests.usage_rules import UsageRow

EVENT = json.loads((Path(__file__).parent / "fixtures/stripe_dahlia_subscription_rollover.json").read_text())
SUB = EVENT["data"]["object"]
ITEM = SUB["items"]["data"][0]


def ts(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def iso(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).isoformat()


JAN, FEB = "2026-01-01T09:00:00", "2026-02-01T09:00:00"


def tenant(**over):
    return {"id": "t1", "stripe_customer_id": SUB["customer"], "stripe_subscription_id": SUB["id"],
            "subscription_status": "active", "subscription_plan": "pro", "minutes_used_this_period": 120,
            "overage_minutes_reported": 5, "billing_period_anchor": "2026-01-01",
            "billing_period_started_at": iso(JAN), **over}


def event_at(start, status="active"):
    event = json.loads(json.dumps(EVENT))
    event["data"]["object"]["items"]["data"][0]["current_period_start"] = ts(start)
    event["data"]["object"]["status"] = status
    return event


class Request:
    headers = {"stripe-signature": "sig"}

    def __init__(self, event):
        self._body = json.dumps(event).encode()

    async def body(self):
        return self._body


async def deliver(row, event):
    async def update(_id, change):
        row.update(change)
        return row

    record, roll, reported = UsageRow(row).patches()
    with patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec"), \
            patch.object(billing.stripe.Webhook, "construct_event", MagicMock()), \
            patch.object(billing.db, "get_tenant_by_stripe_customer", AsyncMock(side_effect=lambda _c: dict(row))), \
            patch.object(billing.db, "update_tenant", AsyncMock(side_effect=update)), record, roll, reported:
        await billing.stripe_webhook(Request(event))
    return row


async def call(row, call_id, ended, secs=60, stripe_says=None, meter=None, today=None):
    """One end-of-call. stripe_says: the period start, an Exception, or None for no lookup."""
    side = {"side_effect": stripe_says} if isinstance(stripe_says, Exception) else {
        "return_value": {"current_period_start": ts(stripe_says) if stripe_says else None}}
    record, roll, reported = UsageRow(row).patches()
    lookup = patch.object(usage, "_current_period_start", AsyncMock(return_value=iso(stripe_says))) \
        if isinstance(stripe_says, str) else patch.object(usage.stripe.Subscription, "retrieve", MagicMock(**side))
    with patch.object(usage.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _i: dict(row))), record, roll, reported, \
            patch.object(usage, "_stripe_key", "sk"), patch.object(usage, "_overage_price_id", "price" if meter else ""), \
            lookup, patch.object(usage.stripe.billing.MeterEvent, "create", meter or MagicMock()):
        await usage.record_call_minutes("t1", secs, call_id=call_id, ended_at=iso(ended))
    return row


def test_the_fixture_is_the_live_shape():
    assert EVENT["api_version"] == "2026-04-22.dahlia"
    assert SUB.get("current_period_start") is None
    assert subscriptions.period_start(SUB) == ITEM["current_period_start"]


@pytest.mark.asyncio
async def test_a_real_dahlia_rollover_resets_once():
    row = await deliver(tenant(), EVENT)
    assert row["minutes_used_this_period"] == 0
    assert row["overage_minutes_reported"] == 0
    await call(row, "c1", "2099-01-01T00:00:00")
    await deliver(row, EVENT)
    assert row["minutes_used_this_period"] == 1


@pytest.mark.asyncio
async def test_a_late_redelivery_of_an_old_period_changes_nothing():
    row = await deliver(tenant(), event_at(FEB))
    await call(row, "c1", "2026-02-02T00:00:00")
    await deliver(row, event_at(JAN))
    assert row["minutes_used_this_period"] == 1
    assert row["billing_period_anchor"] == "2026-02-01"


@pytest.mark.asyncio
async def test_a_missing_anchor_is_recorded_without_wiping_usage():
    row = await deliver(tenant(billing_period_anchor=None, billing_period_started_at=None), event_at(FEB))
    assert row["minutes_used_this_period"] == 120
    assert row["billing_period_anchor"] == "2026-02-01"


@pytest.mark.asyncio
async def test_a_legacy_date_anchor_does_not_reset_on_its_own_day():
    # A stored date has no time of day, so 09:00 on that date isn't a new period.
    row = await deliver(tenant(billing_period_started_at=None), event_at(JAN))
    assert row["minutes_used_this_period"] == 120
    assert row["billing_period_started_at"] is None or row["minutes_used_this_period"] == 120


@pytest.mark.asyncio
async def test_another_subscription_on_the_customer_changes_nothing():
    row = await deliver(tenant(stripe_subscription_id="sub_other"), event_at(FEB))
    assert row["minutes_used_this_period"] == 120


@pytest.mark.asyncio
async def test_a_trial_that_converts_on_its_own_starts_clean():
    row = await deliver(tenant(subscription_status="trialing", minutes_used_this_period=60), event_at(FEB))
    assert row["minutes_used_this_period"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("old,new", [
    ("2026-01-31T09:00:00", "2026-02-28T09:00:00"),
    ("2026-02-28T09:00:00", "2026-03-31T09:00:00"),
    ("2026-12-31T09:00:00", "2027-01-31T09:00:00"),
    ("2028-02-29T09:00:00", "2028-03-29T09:00:00"),
], ids=["short month", "month end", "year end", "leap day"])
async def test_monthly_boundaries_reset_once(old, new):
    row = tenant(billing_period_anchor=old[:10], billing_period_started_at=iso(old))
    await deliver(row, event_at(new))
    assert row["minutes_used_this_period"] == 0
    assert row["billing_period_anchor"] == new[:10]


@pytest.mark.asyncio
async def test_an_annual_plan_resets_on_renewal_and_not_during_the_year():
    row = tenant()
    await deliver(row, event_at(JAN))
    await call(row, "c1", "2026-06-01T00:00:00", stripe_says=JAN)
    assert row["minutes_used_this_period"] == 121
    await deliver(row, event_at("2027-01-01T09:00:00"))
    assert row["minutes_used_this_period"] == 0


@pytest.mark.asyncio
async def test_a_call_that_sees_the_new_period_survives_the_webhook():
    row = await call(tenant(), "c1", "2026-02-01T10:00:00", secs=300, stripe_says=FEB)
    assert row["minutes_used_this_period"] == 5
    await deliver(row, event_at(FEB))
    assert row["minutes_used_this_period"] == 5


@pytest.mark.asyncio
async def test_a_call_recorded_during_a_stripe_outage_survives_the_rollover():
    # It ended in the new period, and only the webhook can say so.
    row = tenant(billing_period_anchor="2026-01-01")
    await call(row, "c1", "2026-02-01T10:00:00", secs=300, stripe_says=stripe.APIConnectionError("down"))
    assert row["minutes_used_this_period"] == 125
    await deliver(row, event_at(FEB))
    assert row["minutes_used_this_period"] == 5


@pytest.mark.asyncio
async def test_a_call_from_before_a_rollover_is_cleared_with_its_period():
    row = await call(tenant(), "c1", "2026-01-31T10:00:00")
    await deliver(row, event_at(FEB))
    assert row["minutes_used_this_period"] == 0


@pytest.mark.asyncio
async def test_a_delayed_call_from_the_old_period_does_not_use_the_new_allowance():
    row = await deliver(tenant(), event_at(FEB))
    await call(row, "late", "2026-01-31T23:50:00", secs=600)
    assert row["minutes_used_this_period"] == 0
    assert row["_events"]["late"]["counted"] is False


@pytest.mark.asyncio
async def test_a_retried_call_counts_once():
    row = tenant()
    await call(row, "c1", "2026-01-15T00:00:00")
    await call(row, "c1", "2026-01-15T00:00:00")
    assert row["minutes_used_this_period"] == 121


@pytest.mark.asyncio
async def test_overage_is_reported_once_with_a_stable_identifier():
    row, meter = tenant(minutes_used_this_period=400, overage_minutes_reported=0), MagicMock()
    await call(row, "c1", "2026-01-15T00:00:00", secs=300, meter=meter)
    await call(row, "c1", "2026-01-15T00:00:00", secs=300, meter=meter)
    meter.assert_called_once()
    assert meter.call_args.kwargs["payload"]["value"] == "5"
    assert meter.call_args.kwargs["identifier"] == usage._meter_identifier("t1", "c1")
    assert row["overage_minutes_reported"] == 5


@pytest.mark.asyncio
async def test_a_failed_meter_call_stays_pending_and_is_retried_with_the_same_identifier():
    row = tenant(minutes_used_this_period=400, overage_minutes_reported=0)
    await call(row, "c1", "2026-01-15T00:00:00", secs=300, meter=MagicMock(side_effect=stripe.APIConnectionError("down")))
    assert row["_events"]["c1"]["state"] == "pending"
    assert row["overage_minutes_reported"] == 0

    pending = [{"tenant_id": "t1", "call_id": "c1", "overage_minutes": 5, "ended_at": iso("2026-01-15T00:00:00"),
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()}]
    meter = MagicMock()
    _, _, reported = UsageRow(row).patches()
    with patch.object(usage.db, "usage_pending_overage", AsyncMock(return_value=pending)), \
            patch.object(usage.db, "get_tenant_by_id", AsyncMock(return_value=row)), reported, \
            patch.object(usage.stripe.billing.MeterEvent, "create", meter):
        result = await usage.retry_pending_overage()
    assert result["reported"] == 1
    assert meter.call_args.kwargs["identifier"] == usage._meter_identifier("t1", "c1")
    assert row["overage_minutes_reported"] == 5


async def retry_once(row, meter):
    pending = [{"tenant_id": "t1", "call_id": "c1", "overage_minutes": 5, "ended_at": iso("2026-01-15T00:00:00"),
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()}]
    _, _, reported = UsageRow(row).patches()
    with patch.object(usage.db, "usage_pending_overage", AsyncMock(return_value=pending)), \
            patch.object(usage.db, "get_tenant_by_id", AsyncMock(return_value=row)), reported, \
            patch.object(usage.stripe.billing.MeterEvent, "create", meter), patch.object(usage, "_stripe_key", "sk"):
        return await usage.retry_pending_overage()


@pytest.mark.asyncio
async def test_a_retry_stripe_already_has_settles_without_billing_again():
    # Stripe's real answer in test mode: HTTP 400, no error code.
    row = tenant(minutes_used_this_period=400, overage_minutes_reported=0)
    await call(row, "c1", "2026-01-15T00:00:00", secs=300, meter=MagicMock(side_effect=stripe.APIConnectionError("down")))
    duplicate = stripe.InvalidRequestError("An event already exists with identifier ol-usage-x.", "identifier")
    result = await retry_once(row, MagicMock(side_effect=duplicate))
    assert result["reported"] == 1
    assert row["_events"]["c1"]["state"] == "reported"


@pytest.mark.asyncio
async def test_any_other_stripe_refusal_stays_pending():
    row = tenant(minutes_used_this_period=400, overage_minutes_reported=0)
    await call(row, "c1", "2026-01-15T00:00:00", secs=300, meter=MagicMock(side_effect=stripe.APIConnectionError("down")))
    result = await retry_once(row, MagicMock(side_effect=stripe.InvalidRequestError("No such customer", "customer")))
    assert result["failed"] == 1
    assert row["_events"]["c1"]["state"] == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("age,expected", [(timedelta(minutes=1), "skipped"), (timedelta(hours=30), "review")])
async def test_overage_too_new_or_too_old_is_not_sent(age, expected):
    pending = [{"tenant_id": "t1", "call_id": "c1", "overage_minutes": 5, "ended_at": iso(JAN),
                "created_at": (datetime.now(timezone.utc) - age).isoformat()}]
    meter, flag = MagicMock(), AsyncMock()
    with patch.object(usage.db, "usage_pending_overage", AsyncMock(return_value=pending)), \
            patch.object(usage.db, "usage_overage_needs_review", flag), \
            patch.object(usage.stripe.billing.MeterEvent, "create", meter):
        await usage.retry_pending_overage()
    meter.assert_not_called()
    assert flag.await_count == (1 if expected == "review" else 0)


@pytest.mark.asyncio
async def test_a_trial_conversion_keeps_only_calls_after_it():
    row = tenant(minutes_used_this_period=60, billing_period_anchor="2026-02-01", billing_period_started_at=None)
    _, roll, _ = UsageRow(row).patches()
    with roll:
        from db import supabase as db
        result = await db.usage_roll_period("t1", iso(FEB), start_paid=True)
    assert result["rolled"] is True
    assert row["minutes_used_this_period"] == 0
