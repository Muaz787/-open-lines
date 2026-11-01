"""Moving a complimentary or manual account onto a paid plan.

The promise under test: nothing about the tenant's access changes until Stripe says
the subscription is paid, and then it changes in one write.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from routers import admin, billing
from services import usage
from services.account_state import account_state, paid_transition_open

TENANT = "11111111-1111-4111-8111-111111111111"
KEY = "test-admin-key"
PRICE = "price_business"
OPEN = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
CLOSED = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

COMPED = {"id": TENANT, "email": "o@example.com", "billing_exempt": True, "subscription_plan": "pro",
          "subscription_status": "active", "stripe_customer_id": "cus_1", "paid_transition_expires_at": OPEN}
MANUAL = {**COMPED, "billing_exempt": False}
ACCESS_FIELDS = ("billing_exempt", "subscription_plan", "subscription_status", "stripe_subscription_id")


class Sub(dict):
    def __init__(self, status="incomplete", plan="business", interval_price=PRICE, customer="cus_1"):
        item = SimpleNamespace(id="si_1", price=SimpleNamespace(id=interval_price))
        super().__init__(items={"data": [item]}, metadata={"plan": plan})
        self.id = "sub_new"
        self.status = status
        self.customer = customer
        self.latest_invoice = None
        self.current_period_start = 1_790_000_000


class World:
    def __init__(self, row, created=None, retrieved=None):
        self.row = dict(row)
        self.update = AsyncMock(side_effect=lambda _id, patch_: self.row.update(patch_) or self.row)
        self.create = MagicMock(return_value=created or Sub())
        self.retrieve = MagicMock(side_effect=retrieved) if isinstance(retrieved, Exception) \
            else MagicMock(return_value=retrieved)
        self.cancel = MagicMock()

    def access(self):
        return tuple(self.row.get(f) for f in ACCESS_FIELDS)

    def __enter__(self):
        self.patches = [
            patch.object(billing, "verify_tenant_owner", AsyncMock()),
            patch.object(billing, "_resolve_price", return_value=PRICE),
            patch.object(billing, "_plan_from_price", lambda p: "business" if p == PRICE else None),
            patch.object(billing, "_sub_interval", return_value="month"),
            patch.object(billing, "_extract_pi_secret", return_value="pi_secret"),
            patch.object(billing.db, "get_tenant_by_id", AsyncMock(side_effect=lambda _id: dict(self.row))),
            patch.object(billing.db, "get_tenant_by_stripe_customer", AsyncMock(side_effect=lambda _c: dict(self.row))),
            patch.object(billing.db, "update_tenant", self.update),
            patch.object(billing.stripe.Customer, "retrieve", MagicMock(return_value=SimpleNamespace(deleted=False))),
            patch.object(billing.stripe.Customer, "modify", MagicMock()),
            patch.object(billing.stripe.Customer, "create", MagicMock(return_value=SimpleNamespace(id="cus_new"))),
            patch.object(billing.stripe.Subscription, "create", self.create),
            patch.object(billing.stripe.Subscription, "retrieve", self.retrieve),
            patch.object(billing.stripe.Subscription, "cancel", self.cancel),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *_):
        for p in self.patches:
            p.stop()


BODY = {"tenant_id": TENANT, "plan": "business", "interval": "month"}


@pytest.mark.parametrize("row", [COMPED, MANUAL])
def test_the_window_is_reported_on_the_account(row):
    assert account_state(row)["paid_transition_open"] is True


@pytest.mark.parametrize("change", [
    {"paid_transition_expires_at": None},
    {"paid_transition_expires_at": CLOSED},
    {"paid_transition_expires_at": "not a date"},
    {"stripe_subscription_id": "sub_old"},
])
def test_the_window_fails_closed(change):
    assert paid_transition_open({**COMPED, **change}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"paid_transition_expires_at": None}, {"paid_transition_expires_at": CLOSED}])
async def test_nothing_starts_without_an_open_window(change):
    with World({**COMPED, **change}) as w:
        with pytest.raises(HTTPException) as refused:
            await billing.start_paid_transition(BODY, "Bearer t")
    assert refused.value.status_code == 409
    w.create.assert_not_called()
    w.update.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [COMPED, MANUAL])
async def test_starting_checkout_leaves_access_exactly_as_it_was(row):
    with World(row) as w:
        before = w.access()
        result = await billing.start_paid_transition(BODY, "Bearer t")
    assert result["client_secret"] == "pi_secret"
    assert w.access() == before
    assert w.row["paid_transition_subscription_id"] == "sub_new"


@pytest.mark.asyncio
async def test_the_ordinary_routes_stay_closed_during_the_window():
    with World(COMPED) as w:
        for route in (billing.create_subscription, billing.create_checkout, billing.upgrade_plan):
            with pytest.raises(HTTPException) as refused:
                await route(BODY, "Bearer t")
            assert refused.value.status_code == 409
    w.create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "past_due", "incomplete_expired", "canceled"])
async def test_an_unpaid_subscription_changes_nothing_through_confirm_payment(status):
    row = {**COMPED, "paid_transition_subscription_id": "sub_new"}
    with World(row, retrieved=Sub(status)) as w:
        before = w.access()
        result = await billing.confirm_payment({"tenant_id": TENANT, "subscription_id": "sub_new"}, "Bearer t")
    assert result["status"] == "pending"
    assert w.access() == before
    w.update.assert_not_called()


@pytest.mark.asyncio
async def test_payment_ends_comp_in_one_write():
    row = {**COMPED, "paid_transition_subscription_id": "sub_new", "minutes_used_this_period": 36}
    with World(row, retrieved=Sub("active")) as w:
        await billing.confirm_payment({"tenant_id": TENANT, "subscription_id": "sub_new"}, "Bearer t")
    w.update.assert_awaited_once()
    assert w.access() == (False, "business", "active", "sub_new")
    assert w.row["minutes_used_this_period"] == 0
    assert w.row["paid_transition_subscription_id"] is None
    assert w.row["paid_transition_expires_at"] is None


@pytest.mark.asyncio
async def test_a_payment_that_lands_after_the_window_closed_still_completes():
    row = {**MANUAL, "paid_transition_subscription_id": "sub_new", "paid_transition_expires_at": CLOSED}
    with World(row, retrieved=Sub("active")) as w:
        await billing.confirm_payment({"tenant_id": TENANT, "subscription_id": "sub_new"}, "Bearer t")
    assert w.access()[2:] == ("active", "sub_new")


@pytest.mark.asyncio
async def test_a_second_attempt_resumes_the_first():
    row = {**COMPED, "paid_transition_subscription_id": "sub_new"}
    with World(row, retrieved=Sub("incomplete")) as w:
        result = await billing.start_paid_transition(BODY, "Bearer t")
    assert result["client_secret"] == "pi_secret"
    w.create.assert_not_called()


@pytest.mark.asyncio
async def test_choosing_another_plan_replaces_the_unpaid_attempt():
    row = {**COMPED, "paid_transition_subscription_id": "sub_old"}
    with World(row, retrieved=Sub("incomplete", plan="starter")) as w:
        await billing.start_paid_transition(BODY, "Bearer t")
    w.cancel.assert_called_once_with("sub_old")
    w.create.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stripe_says", [Sub("incomplete_expired"), stripe.InvalidRequestError("gone", "id")])
async def test_an_abandoned_attempt_can_start_over(stripe_says):
    row = {**COMPED, "paid_transition_subscription_id": "sub_old"}
    with World(row, retrieved=stripe_says) as w:
        await billing.start_paid_transition(BODY, "Bearer t")
    w.create.assert_called_once()


@pytest.mark.asyncio
async def test_a_stripe_outage_while_resuming_changes_nothing():
    row = {**COMPED, "paid_transition_subscription_id": "sub_old"}
    with World(row, retrieved=stripe.APIConnectionError("down")) as w:
        with pytest.raises(HTTPException) as refused:
            await billing.start_paid_transition(BODY, "Bearer t")
    assert refused.value.status_code == 503
    w.create.assert_not_called()
    w.update.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_start_leaves_the_account_alone():
    with World(COMPED) as w:
        w.create.side_effect = stripe.CardError("declined", None, "card_declined")
        before = w.access()
        with pytest.raises(HTTPException) as refused:
            await billing.start_paid_transition(BODY, "Bearer t")
    assert refused.value.status_code == 502
    assert w.access() == before
    assert "paid_transition_subscription_id" not in w.row


class Request:
    def __init__(self, event):
        self.headers = {"stripe-signature": "sig"}
        self._body = json.dumps(event).encode()

    async def body(self):
        return self._body


async def webhook(event_type, status):
    event = {"type": event_type, "data": {"object": {"id": "sub_new", "customer": "cus_1", "status": status}}}
    with patch.object(billing, "STRIPE_WEBHOOK_SECRET", "whsec"), \
            patch.object(billing.stripe.Webhook, "construct_event", MagicMock()):
        return await billing.stripe_webhook(Request(event))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["incomplete", "incomplete_expired", "past_due"])
async def test_webhooks_ignore_an_unpaid_transition(status):
    with World({**MANUAL, "paid_transition_subscription_id": "sub_new"}) as w:
        before = w.access()
        await webhook("customer.subscription.updated", status)
    assert w.access() == before
    w.update.assert_not_called()


@pytest.mark.asyncio
async def test_the_webhook_finishes_a_paid_transition():
    with World({**COMPED, "paid_transition_subscription_id": "sub_new"}, retrieved=Sub("active")) as w:
        await webhook("customer.subscription.updated", "active")
    assert w.access() == (False, "business", "active", "sub_new")


@pytest.mark.asyncio
async def test_a_failed_write_after_payment_asks_stripe_to_retry():
    with World({**COMPED, "paid_transition_subscription_id": "sub_new"}, retrieved=Sub("active")) as w:
        w.update.side_effect = RuntimeError("database down")
        with pytest.raises(HTTPException) as failed:
            await webhook("customer.subscription.updated", "active")
    assert failed.value.status_code == 500


@pytest.mark.asyncio
async def test_sync_does_not_copy_an_unpaid_transition_onto_the_tenant():
    row = {**MANUAL, "paid_transition_subscription_id": "sub_new"}
    listed = SimpleNamespace(data=[Sub("incomplete")])
    with World(row) as w, patch.object(billing, "STRIPE_SECRET_KEY", "sk"), \
            patch.object(billing.stripe.Subscription, "list", MagicMock(return_value=listed)):
        before = w.access()
        await billing.sync_subscription(TENANT, "Bearer t")
    assert w.access() == before


@pytest.mark.asyncio
async def test_customer_with_no_subscription_is_not_metered():
    row = {"id": TENANT, "stripe_customer_id": "cus_1", "subscription_plan": "pro", "minutes_used_this_period": 500}
    with patch.object(usage.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(usage.db, "update_tenant", AsyncMock()), \
            patch.object(usage, "_stripe_key", "sk"), patch.object(usage, "_overage_price_id", "price"), \
            patch.object(usage.stripe.billing.MeterEvent, "create", MagicMock()) as meter:
        await usage.record_call_minutes(TENANT, 120)
    meter.assert_not_called()


# ── The admin step ───────────────────────────────────────────────────────────

@pytest.fixture
def admin_key(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", KEY)
    monkeypatch.setenv("BILLING_EXEMPT_TENANT_IDS", "")


async def set_window(row, body, key=KEY):
    update = AsyncMock()
    with patch.object(admin.db, "get_tenant_by_id", AsyncMock(return_value=row)), \
            patch.object(admin.db, "update_tenant", update):
        try:
            return await admin.set_paid_transition(TENANT, body, key), update
        except HTTPException as e:
            return e, update


@pytest.mark.asyncio
async def test_allowing_a_transition_only_sets_the_window(admin_key):
    row = {k: v for k, v in COMPED.items() if k != "paid_transition_expires_at"}
    result, update = await set_window(row, {"allow": True})
    assert result["paid_transition_expires_at"]
    assert list(update.await_args.args[1]) == ["paid_transition_expires_at"]


@pytest.mark.asyncio
async def test_closing_the_window_works(admin_key):
    _, update = await set_window(COMPED, {"allow": False})
    assert update.await_args.args[1] == {"paid_transition_expires_at": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    {"id": TENANT, "subscription_status": "active", "stripe_subscription_id": "sub_1"},
    {"id": TENANT, "billing_exempt": True, "stripe_subscription_id": "sub_1", "subscription_status": "canceled"},
    {"id": TENANT},
], ids=["subscriber", "comped with old sub", "no plan"])
async def test_only_eligible_accounts_can_be_allowed(admin_key, row):
    result, update = await set_window(row, {"allow": True})
    assert isinstance(result, HTTPException) and result.status_code == 409
    update.assert_not_called()


@pytest.mark.asyncio
async def test_an_env_comped_tenant_is_refused(admin_key, monkeypatch):
    monkeypatch.setenv("BILLING_EXEMPT_TENANT_IDS", TENANT)
    result, update = await set_window({**COMPED}, {"allow": True})
    assert isinstance(result, HTTPException) and result.status_code == 409
    update.assert_not_called()


@pytest.mark.asyncio
async def test_the_admin_key_is_required(admin_key):
    result, update = await set_window(COMPED, {"allow": True}, key="wrong")
    assert isinstance(result, HTTPException) and result.status_code == 403
    update.assert_not_called()
