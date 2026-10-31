"""One tenant's owner must not be able to read or change another tenant's billing.

Ownership runs through the real verify_tenant_owner; only token decoding is stubbed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from routers import billing

MINE = "11111111-1111-4111-8111-111111111111"
THEIRS = "22222222-2222-4222-8222-222222222222"
AUTH = "Bearer token"
PRICE = "price_business"


@pytest.fixture(autouse=True)
def signed_in_as_mine():
    user = {"id": "u1", "email": "owner@example.com", "tenant_id": MINE}
    with patch("services.security._verified_user", AsyncMock(return_value=user)):
        yield


CROSS_TENANT_CALLS = {
    "create-checkout": lambda: billing.create_checkout({"tenant_id": THEIRS, "plan": "pro"}, AUTH),
    "create-subscription": lambda: billing.create_subscription({"tenant_id": THEIRS, "plan": "pro"}, AUTH),
    "confirm-payment": lambda: billing.confirm_payment({"tenant_id": THEIRS, "subscription_id": "sub_x"}, AUTH),
    "sync": lambda: billing.sync_subscription(THEIRS, AUTH),
    "subscription-details": lambda: billing.subscription_details(THEIRS, AUTH),
    "invoices": lambda: billing.list_invoices(THEIRS, AUTH),
    "portal": lambda: billing.customer_portal(THEIRS, AUTH),
    "cancel": lambda: billing.cancel_subscription(THEIRS, AUTH),
    "end-trial": lambda: billing.end_trial(THEIRS, AUTH),
    "reactivate": lambda: billing.reactivate_subscription(THEIRS, AUTH),
    "proration-preview": lambda: billing.proration_preview({"tenant_id": THEIRS, "plan": "pro"}, AUTH),
    "upgrade-plan": lambda: billing.upgrade_plan({"tenant_id": THEIRS, "plan": "pro"}, AUTH),
    "downgrade-plan": lambda: billing.downgrade_plan({"tenant_id": THEIRS, "plan": "pro"}, AUTH),
    "billing-address get": lambda: billing.get_billing_address(THEIRS, AUTH),
    "billing-address post": lambda: billing.save_billing_address(THEIRS, {}, AUTH),
    "setup-intent": lambda: billing.create_setup_intent(THEIRS, AUTH),
    "usage": lambda: billing.get_usage(THEIRS, AUTH),
    "update-payment-method": lambda: billing.update_payment_method({"tenant_id": THEIRS, "payment_method_id": "pm_x"}, AUTH),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CROSS_TENANT_CALLS)
async def test_another_tenants_owner_is_refused_before_anything_is_touched(name):
    with patch.object(billing, "stripe") as fake_stripe, patch.object(billing, "db") as fake_db, \
            patch.object(billing.trial, "convert_card_trial", AsyncMock()) as convert:
        with pytest.raises(HTTPException) as refused:
            await CROSS_TENANT_CALLS[name]()
    assert refused.value.status_code == 403
    assert fake_stripe.mock_calls == []
    assert fake_db.mock_calls == []
    convert.assert_not_called()


# ── /confirm-payment ─────────────────────────────────────────────────────────

class Sub(dict):
    def __init__(self, customer="cus_mine", status="active", price=PRICE):
        item = SimpleNamespace(id="si_1", price=SimpleNamespace(id=price))
        super().__init__(items={"data": [item]})
        self.customer = customer
        self.status = status


async def confirm(retrieve, tenant=None, **body):
    row = {"id": MINE, "stripe_customer_id": "cus_mine", **(tenant or {})}
    update = AsyncMock(return_value={"id": MINE})
    lookup = MagicMock(side_effect=retrieve) if isinstance(retrieve, Exception) else MagicMock(return_value=retrieve)
    with patch.object(billing.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(billing.db, "update_tenant", update), \
            patch.object(billing.stripe.Subscription, "retrieve", lookup), \
            patch.object(billing, "_plan_from_price", lambda p: "business" if p == PRICE else None):
        try:
            result = await billing.confirm_payment({"tenant_id": MINE, "subscription_id": "sub_x", **body}, AUTH)
        except HTTPException as e:
            result = e
    return result, update


@pytest.mark.asyncio
async def test_confirm_payment_records_the_tenants_own_subscription_from_stripe():
    result, update = await confirm(Sub(status="past_due"), plan="starter", status="active")
    assert result == {"status": "past_due", "plan": "business"}
    update.assert_awaited_once_with(MINE, {
        "stripe_subscription_id": "sub_x",
        "subscription_plan":      "business",
        "subscription_status":    "past_due",
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("retrieve,tenant", [
    (Sub(customer="cus_theirs"), None),
    (Sub(customer=None), None),
    (Sub(), {"stripe_customer_id": None}),
    (stripe.InvalidRequestError("No such subscription", "id"), None),
], ids=["another customer", "no customer on sub", "tenant has no customer", "not in Stripe"])
async def test_confirm_payment_gives_one_answer_for_every_subscription_it_cant_prove(retrieve, tenant):
    result, update = await confirm(retrieve, tenant)
    assert isinstance(result, HTTPException)
    assert (result.status_code, result.detail) == (404, "Subscription not found")
    update.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_payment_never_guesses_a_plan():
    result, update = await confirm(Sub(price="price_unknown"))
    assert isinstance(result, HTTPException) and result.status_code == 409
    update.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_payment_writes_nothing_during_a_stripe_outage():
    result, update = await confirm(stripe.APIConnectionError("connection failed"))
    assert isinstance(result, HTTPException) and result.status_code == 500
    update.assert_not_called()


# ── Recovery flows the owner must keep ───────────────────────────────────────

@pytest.mark.asyncio
async def test_the_owner_keeps_the_billing_portal_for_their_own_customer():
    row = {"id": MINE, "stripe_customer_id": "cus_mine"}
    with patch.object(billing.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(billing.stripe.billing_portal.Session, "create",
                         MagicMock(return_value=SimpleNamespace(url="https://portal.test"))) as portal:
        result = await billing.customer_portal(MINE, AUTH)
    assert result == {"url": "https://portal.test"}
    assert portal.call_args.kwargs["customer"] == "cus_mine"


@pytest.mark.asyncio
async def test_the_owner_can_end_their_own_trial_to_recover_a_gated_line():
    row = {"id": MINE, "subscription_status": "trialing", "subscription_plan": "pro"}
    outcome = {"converted": True, "already": False, "status": "active"}
    with patch.object(billing.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(billing.trial, "convert_card_trial", AsyncMock(return_value=outcome)) as convert:
        result = await billing.end_trial(MINE, AUTH)
    assert result["status"] == "active"
    convert.assert_awaited_once_with(row, reason="manual")


@pytest.mark.asyncio
async def test_end_trial_writes_nothing_when_there_is_no_trial():
    row = {"id": MINE, "subscription_status": "active"}
    with patch.object(billing.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(billing.trial, "convert_card_trial", AsyncMock()) as convert:
        with pytest.raises(HTTPException) as refused:
            await billing.end_trial(MINE, AUTH)
    assert refused.value.status_code == 400
    convert.assert_not_called()
