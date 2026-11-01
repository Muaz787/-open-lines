"""The admin billing check reports what Stripe says and changes nothing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from routers import admin, billing

KEY = "test-admin-key"
ROW = {"id": "t1", "stripe_subscription_id": "sub_1", "subscription_status": "active", "subscription_plan": "business"}


@pytest.fixture(autouse=True)
def admin_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", KEY)


async def check(row, retrieve):
    lookup = MagicMock(side_effect=retrieve) if isinstance(retrieve, Exception) else MagicMock(return_value=retrieve)
    update = AsyncMock()
    with patch.object(admin.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(admin.db, "update_tenant", update), \
            patch.object(billing.stripe.Subscription, "retrieve", lookup), \
            patch.object(billing.stripe.Subscription, "modify", MagicMock()) as modify:
        result = await admin.billing_check("t1", KEY)
    update.assert_not_called()
    modify.assert_not_called()
    return result


@pytest.mark.asyncio
async def test_a_subscription_stripe_rejects_reads_as_missing():
    result = await check(ROW, stripe.InvalidRequestError("No such subscription", "id"))
    assert (result["provider_state"], result["stripe_status"]) == ("missing", None)
    assert result["account"]["source"] == "subscription"


@pytest.mark.asyncio
async def test_a_confirmed_subscription_reports_stripes_status():
    result = await check(ROW, SimpleNamespace(status="past_due"))
    assert (result["provider_state"], result["stripe_status"]) == ("ok", "past_due")


@pytest.mark.asyncio
async def test_an_outage_is_not_reported_as_missing():
    result = await check(ROW, stripe.APIConnectionError("connection failed"))
    assert result["provider_state"] == "unavailable"


@pytest.mark.asyncio
async def test_no_subscription_needs_no_lookup():
    assert (await check({"id": "t1"}, AssertionError("should not be called")))["provider_state"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "wrong"])
async def test_the_admin_key_is_required(key):
    with patch.object(admin.db, "get_tenant_by_id", AsyncMock()) as lookup:
        with pytest.raises(HTTPException) as refused:
            await admin.billing_check("t1", key)
    assert refused.value.status_code == 403
    lookup.assert_not_called()
