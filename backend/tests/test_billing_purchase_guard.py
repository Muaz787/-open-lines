"""Who may start or change a paid plan from the dashboard.

Every refusal must happen before anything is written, in Stripe or on the tenant.
The allowed cases pin the flows the guard must not touch: first purchase, resubscribe,
plan change during a trial, a past-due or canceling plan, and an unfinished payment.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from routers import billing

TENANT = "11111111-1111-4111-8111-111111111111"
NOT_FOUND = stripe.InvalidRequestError("No such subscription", "id")
OUTAGE = stripe.APIConnectionError("connection failed")


class Sub(dict):
    """Stripe objects are dicts with attribute access; billing reads both ways."""

    def __init__(self, status):
        item = SimpleNamespace(id="si_1", price=SimpleNamespace(id="price_old"))
        super().__init__(items={"data": [item]})
        self.id = "sub_1"
        self.status = status
        self.latest_invoice = None
        self.current_period_end = 1


def tenant(**row):
    return {"id": TENANT, "email": "owner@example.com", **row}


def subscribed(status="active", sub_id="sub_1"):
    return tenant(stripe_subscription_id=sub_id, stripe_customer_id="cus_1",
                  subscription_status=status, subscription_plan="pro")


class Stripe:
    """Replaces every Stripe call the routes make and records the writes."""

    def __init__(self, row, retrieve):
        self.row = row
        if isinstance(retrieve, Exception):
            self.retrieve = MagicMock(side_effect=retrieve)
        else:
            self.retrieve = MagicMock(return_value=retrieve)
        self.create = MagicMock(return_value=Sub("incomplete"))
        self.modify = MagicMock(return_value=Sub("active"))
        self.cancel = MagicMock()
        self.checkout = MagicMock(return_value=SimpleNamespace(url="https://checkout.test"))
        self.customer_create = MagicMock(return_value=SimpleNamespace(id="cus_new"))
        self.customer_modify = MagicMock()
        self.update_tenant = AsyncMock(return_value={"id": TENANT})

    @property
    def writes(self):
        return [m for m in (self.create, self.modify, self.cancel, self.checkout, self.customer_create,
                            self.customer_modify, self.update_tenant) if m.called]


@pytest.fixture
def run():
    async def call(route, row, retrieve=None, **body):
        fake = Stripe(row, retrieve if retrieve is not None else Sub("active"))
        with patch.object(billing, "verify_tenant_owner", AsyncMock()), \
                patch.object(billing, "_resolve_price", return_value="price_new"), \
                patch.object(billing.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
                patch.object(billing.db, "update_tenant", fake.update_tenant), \
                patch.object(billing, "_extract_pi_secret", return_value="pi_secret"), \
                patch.object(billing.stripe.Customer, "retrieve", MagicMock(return_value=SimpleNamespace(deleted=False))), \
                patch.object(billing.stripe.Customer, "create", fake.customer_create), \
                patch.object(billing.stripe.Customer, "modify", fake.customer_modify), \
                patch.object(billing.stripe.Subscription, "retrieve", fake.retrieve), \
                patch.object(billing.stripe.Subscription, "create", fake.create), \
                patch.object(billing.stripe.Subscription, "modify", fake.modify), \
                patch.object(billing.stripe.Subscription, "cancel", fake.cancel), \
                patch.object(billing.stripe.checkout.Session, "create", fake.checkout):
            try:
                result = await route({"tenant_id": TENANT, "plan": "business", **body})
            except HTTPException as e:
                result = e
        return fake, result
    return call


ALL_ROUTES = [billing.create_checkout, billing.create_subscription, billing.upgrade_plan, billing.downgrade_plan]
PURCHASE_ROUTES = [billing.create_checkout, billing.create_subscription]

COMPED_ROWS = [
    tenant(billing_exempt=True),
    tenant(billing_exempt=True, subscription_status="active", subscription_plan="pro"),
    {**subscribed(), "billing_exempt": True},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ALL_ROUTES)
@pytest.mark.parametrize("row", COMPED_ROWS)
async def test_complimentary_accounts_cannot_buy_or_change_a_plan(run, route, row):
    fake, result = await run(route, row)
    assert isinstance(result, HTTPException) and result.status_code == 409
    assert "complimentary" in result.detail
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ALL_ROUTES)
@pytest.mark.parametrize("status", ["active", "canceling", "past_due"])
async def test_manual_accounts_go_through_support(run, route, status):
    fake, result = await run(route, tenant(subscription_status=status, subscription_plan="pro"))
    assert isinstance(result, HTTPException) and result.status_code == 409
    assert "support@openlines.ai" in result.detail
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ALL_ROUTES)
@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "canceling"])
async def test_an_unverified_subscription_blocks_everything_and_keeps_the_stored_ids(run, route, status):
    fake, result = await run(route, subscribed(status), NOT_FOUND)
    assert isinstance(result, HTTPException) and result.status_code == 409
    assert "billed twice" in result.detail
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ALL_ROUTES)
async def test_a_stripe_outage_refuses_without_writing(run, route):
    fake, result = await run(route, subscribed(), OUTAGE)
    assert isinstance(result, HTTPException) and result.status_code == 503
    assert fake.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "incomplete", "unpaid", "paused"])
async def test_checkout_cannot_add_a_second_subscription(run, status):
    fake, result = await run(billing.create_checkout, subscribed(), Sub(status))
    assert isinstance(result, HTTPException) and result.status_code == 409
    assert "already has a subscription" in result.detail
    fake.checkout.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["unpaid", "paused"])
async def test_create_subscription_cannot_stack_on_a_stalled_subscription(run, status):
    fake, result = await run(billing.create_subscription, subscribed("past_due"), Sub(status))
    assert isinstance(result, HTTPException) and result.status_code == 409
    fake.create.assert_not_called()
    fake.customer_modify.assert_not_called()


# ── Flows that must keep working ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("route", PURCHASE_ROUTES)
@pytest.mark.parametrize("row", [
    tenant(),
    tenant(subscription_status="none", stripe_customer_id="cus_1"),
])
async def test_first_purchase_still_works(run, route, row):
    _, result = await run(route, row)
    assert not isinstance(result, HTTPException)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", PURCHASE_ROUTES)
@pytest.mark.parametrize("stripe_says", [Sub("canceled"), Sub("incomplete_expired"), NOT_FOUND])
async def test_a_canceled_account_can_resubscribe(run, route, stripe_says):
    # Includes canceled rows whose old id Stripe no longer has, such as test-mode leftovers.
    _, result = await run(route, subscribed("canceled"), stripe_says)
    assert not isinstance(result, HTTPException)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["trialing", "past_due", "canceling"])
async def test_plan_changes_on_a_live_subscription_stay_in_place(run, status):
    # The Billing page sends everything except a plain active plan through this route.
    fake, result = await run(billing.create_subscription, subscribed(status),
                             Sub("active" if status == "canceling" else status))
    assert result["needs_payment"] is False
    fake.modify.assert_called_once()
    fake.create.assert_not_called()


@pytest.mark.asyncio
async def test_an_unfinished_payment_can_be_resumed(run):
    fake, result = await run(billing.create_subscription, subscribed("incomplete"), Sub("incomplete"))
    assert result["client_secret"] == "pi_secret"
    fake.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [billing.upgrade_plan, billing.downgrade_plan])
async def test_a_paying_customer_can_still_upgrade_and_downgrade(run, route):
    fake, result = await run(route, subscribed(), Sub("active"))
    assert not isinstance(result, HTTPException)
    fake.modify.assert_called_once()
