"""Card-required trial: the setup token, the trial subscription, and the gate
on /onboarding/provision.

The token tests are the security-relevant ones. /onboarding/provision is public —
there is no account to authenticate against at signup time — so the Stripe
customer id must never be accepted as a plain client-supplied value, or anyone
could attach a subscription to someone else's customer.
"""
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services import subscriptions
from routers import onboarding
# Registers the sub-module on its parent package so patch() can resolve the
# dotted name. The welcome email is deliberately NOT patched: provision() sends it
# through services.email, whose provider is stubbed in conftest, so nothing leaves
# the process.
import db.supabase as _supabase_mod  # noqa: F401


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", os.urandom(32).hex())


# ── Card-setup token ─────────────────────────────────────────────────────────

def test_token_round_trips_the_customer_id():
    tok = subscriptions.issue_card_setup_token("cus_abc123")
    assert subscriptions.read_card_setup_token(tok) == "cus_abc123"


def test_token_does_not_leak_the_customer_id_in_the_clear():
    assert "cus_abc123" not in subscriptions.issue_card_setup_token("cus_abc123")


def test_tampered_token_is_rejected():
    """AES-GCM is authenticated, so flipping any byte fails the tag check rather
    than decrypting to an attacker-chosen customer."""
    tok = subscriptions.issue_card_setup_token("cus_abc123")
    forged = ("A" if tok[0] != "A" else "B") + tok[1:]
    with pytest.raises(ValueError):
        subscriptions.read_card_setup_token(forged)


def test_token_from_a_different_key_is_rejected(monkeypatch):
    tok = subscriptions.issue_card_setup_token("cus_abc123")
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", os.urandom(32).hex())
    with pytest.raises(ValueError):
        subscriptions.read_card_setup_token(tok)


def test_expired_token_is_rejected():
    from services.security import encrypt
    stale = encrypt(json.dumps({"cus": "cus_abc123", "exp": int(time.time()) - 5}))
    with pytest.raises(ValueError, match="expired"):
        subscriptions.read_card_setup_token(stale)


def test_token_without_a_customer_is_rejected():
    from services.security import encrypt
    empty = encrypt(json.dumps({"exp": int(time.time()) + 999}))
    with pytest.raises(ValueError):
        subscriptions.read_card_setup_token(empty)


# ── create_trial_subscription ────────────────────────────────────────────────

def _stripe_sub(status="trialing"):
    sub = MagicMock()
    sub.id = "sub_new"
    sub.status = status
    sub.trial_end = 1_760_600_000
    sub.current_period_start = 1_760_000_000
    return sub


@pytest.fixture
def _prices(monkeypatch):
    monkeypatch.setattr(subscriptions, "PRICE_IDS", {
        "starter":  {"month": "price_starter_m", "year": "price_starter_y"},
        "pro":      {"month": "price_pro_m",     "year": "price_pro_y"},
        "business": {"month": "price_biz_m",     "year": "price_biz_y"},
    })
    monkeypatch.setattr(subscriptions, "OVERAGE_PRICE_ID", "price_overage")


@pytest.mark.asyncio
async def test_creates_a_trialing_subscription(_prices):
    with patch("stripe.Subscription.create", return_value=_stripe_sub()) as create, \
         patch("stripe.Customer.modify") as cust, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await subscriptions.create_trial_subscription(
            tenant_id="t1", plan="pro", customer_id="cus_1",
            payment_method_id="pm_1", email="a@b.com", business_name="Acme",
            address={"country": "CA", "postal_code": "M5V 1A1"},
        )

    assert res["ok"] is True and res["status"] == "trialing"

    kw = create.call_args.kwargs
    assert kw["trial_period_days"] == 7
    assert kw["default_payment_method"] == "pm_1"
    assert kw["automatic_tax"] == {"enabled": True}
    # Monthly only — an annual plan would land a four-figure charge on day 8.
    assert {"price": "price_pro_m"} in kw["items"]
    assert {"price": "price_overage"} in kw["items"]
    # A retried provision must not create a second subscription.
    assert kw["idempotency_key"] == "trial-sub-t1"
    # No card at trial end should cancel, not leave a live unpayable line.
    assert kw["trial_settings"]["end_behavior"]["missing_payment_method"] == "cancel"

    # Address must land on the customer BEFORE the subscription, or automatic_tax
    # has no jurisdiction to compute GST/HST from on the first invoice.
    assert cust.call_args.kwargs["address"] == {"country": "CA", "postal_code": "M5V 1A1"}
    assert cust.call_args.kwargs["invoice_settings"] == {"default_payment_method": "pm_1"}

    wrote = upd.call_args.args[1]
    assert wrote["subscription_status"] == "trialing"
    assert wrote["subscription_plan"] == "pro"
    assert wrote["stripe_subscription_id"] == "sub_new"
    assert wrote["stripe_trial_ends_at"]
    # Seeded now so the trial -> paid counter reset has something to compare to.
    assert wrote["billing_period_anchor"]


@pytest.mark.asyncio
async def test_unconfigured_price_does_not_call_stripe(_prices, monkeypatch):
    monkeypatch.setattr(subscriptions, "PRICE_IDS", {"starter": {"month": "", "year": ""}})
    with patch("stripe.Subscription.create") as create:
        res = await subscriptions.create_trial_subscription(
            tenant_id="t2", plan="starter", customer_id="cus_2", payment_method_id="pm_2",
        )
    assert res["ok"] is False and res["error"] == "price_not_configured"
    create.assert_not_called()


@pytest.mark.asyncio
async def test_stripe_failure_degrades_instead_of_raising(_prices):
    """The tenant already has a working phone line by this point — a Stripe outage
    must not fail the signup, just drop them onto the card-free fallback trial."""
    with patch("stripe.Customer.modify"), \
         patch("stripe.Subscription.create", side_effect=RuntimeError("stripe down")), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await subscriptions.create_trial_subscription(
            tenant_id="t3", plan="pro", customer_id="cus_3", payment_method_id="pm_3",
        )
    assert res["ok"] is False and res["error"] == "stripe_error"
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_db_failure_surfaces_the_orphaned_subscription(_prices):
    """Stripe has the subscription but we lost our copy — the id must come back so
    the failure is reconcilable rather than silent."""
    with patch("stripe.Customer.modify"), \
         patch("stripe.Subscription.create", return_value=_stripe_sub()), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=RuntimeError("db down"))):
        res = await subscriptions.create_trial_subscription(
            tenant_id="t4", plan="pro", customer_id="cus_4", payment_method_id="pm_4",
        )
    assert res["ok"] is False and res["error"] == "db_error"
    assert res["subscription_id"] == "sub_new"


@pytest.mark.asyncio
async def test_a_failed_customer_update_still_creates_the_subscription(_prices):
    """Wrong tax on a recoverable first invoice beats a failed signup."""
    with patch("stripe.Customer.modify", side_effect=RuntimeError("nope")), \
         patch("stripe.Subscription.create", return_value=_stripe_sub()), \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        res = await subscriptions.create_trial_subscription(
            tenant_id="t5", plan="pro", customer_id="cus_5", payment_method_id="pm_5",
        )
    assert res["ok"] is True


# ── /onboarding/provision gate ───────────────────────────────────────────────

def _provision_body(**over):
    return onboarding.ProvisionRequest(
        business_name="Acme", industry="beauty", email="a@b.com", password="12345678", **over
    )


@pytest.mark.asyncio
async def test_provision_rejects_a_forged_token_before_spending_money():
    """Provisioning buys a phone number and creates a Vapi assistant. A bad
    payment session has to fail before any of that, not after."""
    body = _provision_body(card_setup_token="not-a-real-token",
                           payment_method_id="pm_x", plan="pro")
    with patch("services.provisioning.provision_tenant", new=AsyncMock()) as prov:
        with pytest.raises(HTTPException) as exc:
            await onboarding.provision(None, body)
    assert exc.value.status_code == 400
    prov.assert_not_called()


@pytest.mark.asyncio
async def test_provision_requires_a_card_when_the_flag_is_on(monkeypatch):
    monkeypatch.setenv("TRIAL_REQUIRE_CARD", "true")
    with patch("services.provisioning.provision_tenant", new=AsyncMock()) as prov:
        with pytest.raises(HTTPException) as exc:
            await onboarding.provision(None, _provision_body())
    assert exc.value.status_code == 400
    prov.assert_not_called()


@pytest.mark.asyncio
async def test_provision_still_works_card_free_while_the_flag_is_off(monkeypatch):
    """PR 3 ships ahead of the onboarding UI, so with the flag off a signup that
    sends no card must behave exactly as it does today."""
    monkeypatch.delenv("TRIAL_REQUIRE_CARD", raising=False)
    prov_result = {"tenant_id": "t9", "phone_number": "+14165550100"}
    with patch("services.provisioning.provision_tenant", new=AsyncMock(return_value=prov_result)), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription", new=AsyncMock()) as sub:
        out = await onboarding.provision(None, _provision_body())

    assert out["tenant_id"] == "t9"
    assert "trial" not in out          # no card -> no Stripe subscription
    sub.assert_not_called()


@pytest.mark.asyncio
async def test_provision_starts_the_trial_after_the_tenant_exists():
    calls = []
    prov_result = {"tenant_id": "t10", "phone_number": "+14165550101"}

    async def _prov(payload):
        calls.append("provision")
        # Billing inputs are consumed by the router and must never reach the
        # provisioner (they would end up on the tenant row).
        for leaked in ("plan", "card_setup_token", "payment_method_id", "address", "billing_name"):
            assert leaked not in payload, leaked
        return prov_result

    async def _sub(**kw):
        calls.append("subscribe")
        assert kw["tenant_id"] == "t10"
        assert kw["customer_id"] == "cus_ok"
        return {"ok": True, "plan": "pro", "status": "trialing", "trial_ends_at": "2026-08-16T00:00:00+00:00"}

    body = _provision_body(
        card_setup_token=subscriptions.issue_card_setup_token("cus_ok"),
        payment_method_id="pm_ok", plan="pro",
    )
    with patch("services.provisioning.provision_tenant", new=_prov), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription", new=_sub):
        out = await onboarding.provision(None, body)

    # Never charge for a line that failed to come up.
    assert calls == ["provision", "subscribe"]
    assert out["trial"]["trial_ends_at"] == "2026-08-16T00:00:00+00:00"


@pytest.mark.asyncio
async def test_signup_survives_a_failed_trial_subscription():
    """They have a working receptionist; losing the signup over a Stripe blip
    would be the worse outcome. They fall back to the card-free trial."""
    prov_result = {"tenant_id": "t11", "phone_number": "+14165550102"}
    body = _provision_body(
        card_setup_token=subscriptions.issue_card_setup_token("cus_bad"),
        payment_method_id="pm_bad", plan="pro",
    )
    with patch("services.provisioning.provision_tenant", new=AsyncMock(return_value=prov_result)), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription",
               new=AsyncMock(return_value={"ok": False, "error": "stripe_error"})):
        out = await onboarding.provision(None, body)

    assert out["tenant_id"] == "t11"
    assert "trial" not in out


@pytest.mark.asyncio
async def test_welcome_email_carries_the_trial_billing_summary():
    """Someone who just handed over a card is owed the plan, date and amount in
    writing at that moment. Stripe raises a $0.00 trial invoice but never emails
    it, so the welcome email is the only confirmation they get before day 3."""
    prov_result = {"tenant_id": "t12", "phone_number": "+14165550103"}
    body = _provision_body(
        card_setup_token=subscriptions.issue_card_setup_token("cus_w"),
        payment_method_id="pm_w", plan="pro",
    )
    sub_result = {"ok": True, "plan": "pro", "status": "trialing",
                  "trial_ends_at": "2026-08-16T12:00:00+00:00"}

    with patch("services.provisioning.provision_tenant", new=AsyncMock(return_value=prov_result)), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription", new=AsyncMock(return_value=sub_result)), \
         patch("services.email.send_welcome_email", new=AsyncMock(return_value=True)) as mail:
        await onboarding.provision(None, body)

    kw = mail.call_args.kwargs
    assert kw["plan_name"] == "Pro"
    assert kw["trial_ends_at"] == "August 16, 2026"
    assert kw["amount_text"] == "$199 + tax"


@pytest.mark.asyncio
async def test_welcome_email_omits_billing_when_there_is_no_trial():
    """No card, no subscription — the email must not claim a charge date."""
    prov_result = {"tenant_id": "t13", "phone_number": "+14165550104"}
    with patch("services.provisioning.provision_tenant", new=AsyncMock(return_value=prov_result)), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.email.send_welcome_email", new=AsyncMock(return_value=True)) as mail:
        await onboarding.provision(None, _provision_body())

    assert mail.call_args.kwargs["trial_ends_at"] == ""


def test_invalid_plan_is_rejected_at_the_schema():
    with pytest.raises(Exception):
        onboarding.ProvisionRequest(business_name="A", industry="beauty", plan="enterprise")
    # Empty is allowed — that is the card-free path while the flag is off.
    assert onboarding.ProvisionRequest(business_name="A", industry="beauty", plan="").plan == ""
