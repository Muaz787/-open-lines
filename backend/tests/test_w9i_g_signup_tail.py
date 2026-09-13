"""W9I-G Stage I — a regulated signup must not start billing or claim a number.

THE DEFECT, AS IT STOOD
/onboarding/provision returns a regulated tenant at `regulatory_required` -- an
account with an owner login, and no phone number. The tail then ran anyway and
did two wrong things:

  * started the 7-day Stripe trial, when the authoritative Ireland policy says
    the trial begins only once an approved permanent +353 is ACTIVE. The customer
    would have been billed while waiting on a regulator, for a line that does not
    exist.
  * sent the "your OpenLines number is ready" welcome email with phone_number="",
    presenting an empty number as theirs.

Not reachable while the public flag is off, which made it latent rather than
harmless: it goes live exactly when the flag is turned on, which is when nobody
is looking for it.

WHAT MUST STILL HAPPEN
The auth user. The W9I-C verification flow is authenticated and cannot start
without one, so the exit is placed AFTER account creation and before billing.
"""
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import onboarding
from services import onboarding_lifecycle as lifecycle_ob

TENANT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(onboarding.router)
    monkeypatch.setattr(onboarding.limiter, "enabled", False, raising=False)
    return TestClient(app, raise_server_exceptions=False)


def _payload(country="IE", **over):
    return {"business_name": "Acme", "industry": "realtor", "country": country,
            "owner_name": "O", "agent_name": "A", "website_url": "",
            "email": "owner@example.ie", "password": "hunter2hunter2",
            "plan": "starter", "payment_method_id": "pm_x", **over}


def _provisioned(country="IE"):
    if country == "IE":
        return {"tenant_id": TENANT, "onboarding_state": lifecycle_ob.REGULATORY_REQUIRED,
                "status": "regulatory_required", "next_step": "regulatory_information_required",
                "phone_number": "", "dashboard_url": "/d"}
    return {"tenant_id": TENANT, "onboarding_state": lifecycle_ob.ACTIVE,
            "status": "live", "phone_number": "+14165550100",
            "assistant_id": "asst_1", "next_step": "", "dashboard_url": "/d"}


def _wire(monkeypatch, *, country="IE", enable_ireland=True):
    """Everything the route touches, with the billing tail observable."""
    seen = {"trial": 0, "welcome": [], "auth_user": 0}

    async def provision(payload):
        return _provisioned(country)

    async def create_auth_user(email, password, tenant_id):
        seen["auth_user"] += 1
        return "user_1"

    async def create_trial(**kw):
        seen["trial"] += 1
        return {"ok": True, "plan": kw.get("plan"), "status": "trialing",
                "trial_ends_at": "2026-09-19T00:00:00+00:00"}

    async def welcome(**kw):
        seen["welcome"].append(kw)
        return True

    monkeypatch.setattr(onboarding.provisioning, "provision_tenant", provision)
    monkeypatch.setattr(onboarding.db, "create_auth_user", create_auth_user)
    monkeypatch.setattr(onboarding.db, "update_tenant", AsyncMock(return_value={}))
    monkeypatch.setattr(onboarding.subscriptions, "create_trial_subscription", create_trial)
    monkeypatch.setattr(onboarding.subscriptions, "read_card_setup_token",
                        lambda t: "cus_123")
    monkeypatch.setattr(onboarding, "card_required", lambda: False)
    monkeypatch.setattr("services.email.send_welcome_email", welcome)
    if enable_ireland:
        monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    else:
        monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    return seen


# ═══ the fix ═══════════════════════════════════════════════════════════════

def test_a_regulated_signup_starts_no_stripe_trial(client, monkeypatch):
    seen = _wire(monkeypatch, country="IE")
    r = client.post("/onboarding/provision",
                    json=_payload(card_setup_token="tok"))
    assert r.status_code == 200, r.text
    assert r.json()["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED
    assert seen["trial"] == 0, "a regulated signup started a trial"


def test_a_regulated_signup_sends_no_permanent_welcome_email(client, monkeypatch):
    seen = _wire(monkeypatch, country="IE")
    client.post("/onboarding/provision", json=_payload(card_setup_token="tok"))
    assert seen["welcome"] == [], "a regulated signup sent the number-ready email"


def test_no_email_can_name_an_empty_number(client, monkeypatch):
    """The specific shape of the old defect: the welcome email printed
    phone_number="" as the customer's new number."""
    seen = _wire(monkeypatch, country="IE")
    client.post("/onboarding/provision", json=_payload(card_setup_token="tok"))
    for call in seen["welcome"]:
        assert str(call.get("phone_number") or "").strip(), call


def test_the_owner_account_is_still_created(client, monkeypatch):
    """The W9I-C verification flow is authenticated. Exiting before account
    creation would leave a regulated tenant unable to start verification at all."""
    seen = _wire(monkeypatch, country="IE")
    client.post("/onboarding/provision", json=_payload(card_setup_token="tok"))
    assert seen["auth_user"] == 1


def test_the_regulated_response_still_tells_the_customer_what_to_do(client, monkeypatch):
    _wire(monkeypatch, country="IE")
    body = client.post("/onboarding/provision",
                       json=_payload(card_setup_token="tok")).json()
    assert body["next_step"] == "regulatory_information_required"
    assert body["tenant_id"] == TENANT
    # And it must not carry a trial block, which the success screen reads.
    assert "trial" not in body


# ═══ CA/US unchanged ══════════════════════════════════════════════════════

@pytest.mark.parametrize("country", ["CA", "US"])
def test_an_unregulated_signup_still_starts_its_trial(client, monkeypatch, country):
    seen = _wire(monkeypatch, country=country)
    r = client.post("/onboarding/provision",
                    json=_payload(country=country, card_setup_token="tok"))
    assert r.status_code == 200, r.text
    assert seen["trial"] == 1
    assert r.json()["trial"]["status"] == "trialing"


@pytest.mark.parametrize("country", ["CA", "US"])
def test_an_unregulated_signup_still_sends_its_welcome_email(client, monkeypatch, country):
    seen = _wire(monkeypatch, country=country)
    client.post("/onboarding/provision",
                json=_payload(country=country, card_setup_token="tok"))
    assert len(seen["welcome"]) == 1
    assert seen["welcome"][0]["phone_number"] == "+14165550100"


# ═══ the exit is placed by STATE, not by country ══════════════════════════

def test_the_exit_keys_on_the_returned_state_not_the_requested_country():
    """A country list would drift from onboarding_lifecycle. The provisioner
    already decided -- this reads its answer."""
    import inspect
    src = inspect.getsource(onboarding.provision)
    marker = 'result.get("onboarding_state") or "") == lifecycle_ob.REGULATORY_REQUIRED'
    assert marker in src
    exit_at = src.index(marker)
    trial_at = src.index("create_trial_subscription")
    welcome_at = src.index("send_welcome_email")
    auth_at = src.index("create_auth_user")
    # after the account, before billing and the email
    assert auth_at < exit_at < trial_at
    assert exit_at < welcome_at


def test_public_ireland_signup_is_still_refused_while_the_flag_is_off(client, monkeypatch):
    _wire(monkeypatch, country="IE", enable_ireland=False)
    r = client.post("/onboarding/provision", json=_payload(card_setup_token="tok"))
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "country_onboarding_not_open"
