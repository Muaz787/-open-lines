"""W9I-H.0.1 — availability is decided before anything is asked of the customer.

THE DEFECT, MEASURED IN PRODUCTION
W9I-H.0's live proof found card_required() enforced BEFORE the country gate. A
business in a country we do not serve was told to enter payment details and only
afterwards learned we could not sell to them. The same ordering meant an
authorized Irish pilot had to complete card setup before their grant was even
consulted.

Availability is knowable from the country and the onboarding key alone, so it is
decided first. The change is ONLY the order: every requirement below still
applies in full, and nothing is consumed by asking.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import onboarding
from services import country_access, ireland_pilot as pilot
from services import onboarding_lifecycle as lifecycle_ob
from tests.module_identifiers import identifiers

KEY = "e1f0b077-852f-43f1-b4fe-45c0aae97787"
OTHER_KEY = "a2c3d4e5-6789-4abc-8def-0123456789ab"
TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
FUTURE = "2099-01-01T00:00:00+00:00"
PAST = "2000-01-01T00:00:00+00:00"

CARD_MESSAGE = "A plan and payment method are required to start your free trial"


def _grant(**over):
    return {"onboarding_key": KEY, "iso_country": "IE", "expires_at": FUTURE,
            "created_at": "2026-01-01T00:00:00+00:00", "consumed_at": None,
            "consumed_tenant_id": None, **over}


def _pilot_world(grants=None, tenants=None):
    grants = grants or []
    tenants = tenants or []

    class QB:
        def __init__(self, t): self.t, self.f = t, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.f[c] = v; return self
        def limit(self, *a): return self
        def is_(self, c, v): self.f[f"is_{c}"] = v; return self
        def gt(self, c, v): return self
        def update(self, p): return self
        def execute(self):
            rows = grants if self.t == pilot.TABLE else tenants
            out = [r for r in rows
                   if all(str(r.get(c)) == str(v) for c, v in self.f.items()
                          if not c.startswith(("is_", "gt_")))]
            for c, v in self.f.items():
                if c.startswith("is_") and v == "null":
                    out = [r for r in out if r.get(c[3:]) is None]
            class R: data = [dict(r) for r in out]
            return R()

    return patch.object(pilot, "get_client",
                        return_value=type("C", (), {"table": lambda s, n: QB(n)})())


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(onboarding.router)
    monkeypatch.setattr(onboarding.limiter, "enabled", False, raising=False)
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    # CARD REQUIRED, as production runs it -- the condition that exposed the bug.
    monkeypatch.setattr(onboarding, "card_required", lambda: True)
    return TestClient(app, raise_server_exceptions=False)


def _payload(country="IE", key=KEY, **over):
    return {"business_name": "Acme", "industry": "realtor", "country": country,
            "owner_name": "O", "agent_name": "A", "website_url": "",
            "onboarding_key": key, **over}


def _flow(monkeypatch, *, country="IE"):
    """Everything past the gates, with the side effects observable."""
    seen = {"provisioned": 0, "consumed": [], "trial": 0, "welcome": 0}

    async def provision(payload):
        seen["provisioned"] += 1
        if country == "IE":
            return {"tenant_id": TENANT,
                    "onboarding_state": lifecycle_ob.REGULATORY_REQUIRED,
                    "status": "regulatory_required", "phone_number": "",
                    "next_step": "regulatory_information_required", "dashboard_url": "/d"}
        return {"tenant_id": TENANT, "onboarding_state": lifecycle_ob.ACTIVE,
                "status": "live", "phone_number": "+14165550100",
                "assistant_id": "a", "next_step": "", "dashboard_url": "/d"}

    async def consume(**kw):
        seen["consumed"].append(kw)
        return {"ok": True, "created": True}

    async def trial(**kw):
        seen["trial"] += 1
        return {"ok": True}

    async def welcome(**kw):
        seen["welcome"] += 1
        return True

    monkeypatch.setattr(onboarding.provisioning, "provision_tenant", provision)
    monkeypatch.setattr(onboarding.ireland_pilot, "consume", consume)
    monkeypatch.setattr(onboarding.db, "create_auth_user", AsyncMock(return_value="u1"))
    monkeypatch.setattr(onboarding.db, "update_tenant", AsyncMock(return_value={}))
    monkeypatch.setattr(onboarding.subscriptions, "create_trial_subscription", trial)
    monkeypatch.setattr(onboarding.subscriptions, "read_card_setup_token",
                        lambda t: "cus_123")
    monkeypatch.setattr("services.email.send_welcome_email", welcome)
    return seen


def _closed(r):
    return (r.status_code == 503
            and (r.json().get("detail") or {}).get("status") == "country_onboarding_not_open")


def _card_required(r):
    return r.status_code == 400 and CARD_MESSAGE in r.text


# ═══ 1. a closed country is refused BEFORE the card ═══════════════════════

@pytest.mark.parametrize("grants,tenants,case", [
    ([], [], "no grant"),
    ([_grant(expires_at=PAST)], [], "expired grant"),
    ([_grant(consumed_at="2026-02-01T00:00:00+00:00", consumed_tenant_id=TENANT)],
     [], "consumed, tenant purged"),
    ([_grant(consumed_at="2026-02-01T00:00:00+00:00", consumed_tenant_id=OTHER_TENANT)],
     [{"id": TENANT, "onboarding_key": KEY}], "consumed, tenant mismatch"),
])
def test_a_closed_ireland_signup_is_refused_for_the_country_not_the_card(
        client, monkeypatch, grants, tenants, case):
    """THE fix. Before this, every one of these returned 'a plan and payment
    method are required' -- asking a customer to pay before telling them we
    cannot serve them."""
    seen = _flow(monkeypatch)
    with _pilot_world(grants, tenants):
        r = client.post("/onboarding/provision", json=_payload())
    assert _closed(r), (case, r.status_code, r.text[:120])
    assert not _card_required(r), case
    assert seen["provisioned"] == 0, case


def test_the_refusal_is_identical_across_every_closed_reason(client, monkeypatch):
    _flow(monkeypatch)
    bodies = set()
    for grants, tenants in (
            ([], []),
            ([_grant(expires_at=PAST)], []),
            ([_grant(consumed_at="2026-02-01T00:00:00+00:00",
                     consumed_tenant_id=TENANT)], []),
            ([_grant(consumed_at="2026-02-01T00:00:00+00:00",
                     consumed_tenant_id=OTHER_TENANT)],
             [{"id": TENANT, "onboarding_key": KEY}])):
        with _pilot_world(grants, tenants):
            bodies.add(client.post("/onboarding/provision", json=_payload()).text)
    assert len(bodies) == 1, bodies


# ═══ 2. an ALLOWED country still faces every existing requirement ════════

def test_an_authorized_pilot_without_a_card_gets_the_ordinary_card_refusal(
        client, monkeypatch):
    """Ireland does not become cardless by being decided earlier."""
    seen = _flow(monkeypatch)
    with _pilot_world([_grant()], []):
        r = client.post("/onboarding/provision", json=_payload())
    assert _card_required(r), r.text[:120]
    assert seen["provisioned"] == 0


def test_a_consumed_grant_with_its_tenant_also_reaches_the_card_check(
        client, monkeypatch):
    seen = _flow(monkeypatch)
    with _pilot_world([_grant(consumed_at="2026-02-01T00:00:00+00:00",
                              consumed_tenant_id=TENANT)],
                      [{"id": TENANT, "onboarding_key": KEY}]):
        r = client.post("/onboarding/provision", json=_payload())
    assert _card_required(r)
    assert seen["provisioned"] == 0


def test_public_ireland_without_a_card_gets_the_card_refusal(client, monkeypatch):
    seen = _flow(monkeypatch)
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    with _pilot_world([], []):
        r = client.post("/onboarding/provision", json=_payload())
    assert _card_required(r)
    assert seen["provisioned"] == 0


@pytest.mark.parametrize("country", ["CA", "US"])
def test_unregulated_countries_still_require_a_card(client, monkeypatch, country):
    seen = _flow(monkeypatch, country=country)
    r = client.post("/onboarding/provision", json=_payload(country=country))
    assert _card_required(r)
    assert seen["provisioned"] == 0


@pytest.mark.parametrize("country", ["CA", "US"])
def test_unregulated_signup_with_a_card_is_unchanged(client, monkeypatch, country):
    seen = _flow(monkeypatch, country=country)
    r = client.post("/onboarding/provision",
                    json=_payload(country=country, card_setup_token="tok",
                                  payment_method_id="pm_1", plan="starter",
                                  email="o@x.com", password="hunter2hunter2"))
    assert r.status_code == 200
    assert seen["provisioned"] == 1 and seen["trial"] == 1 and seen["welcome"] == 1


# ═══ 3. the grant is NOT consumed by being asked about ═══════════════════

def test_a_card_refusal_leaves_the_grant_unconsumed(client, monkeypatch):
    """A customer who abandons at the card step must not have burned their
    invitation on a question."""
    seen = _flow(monkeypatch)
    with _pilot_world([_grant()], []):
        r = client.post("/onboarding/provision", json=_payload())
    assert _card_required(r)
    assert seen["consumed"] == []


def test_a_transient_failure_before_the_tenant_leaves_the_grant_unconsumed(
        client, monkeypatch):
    seen = _flow(monkeypatch)

    async def boom(payload):
        raise RuntimeError("twilio down")

    monkeypatch.setattr(onboarding.provisioning, "provision_tenant", boom)
    with _pilot_world([_grant()], []):
        client.post("/onboarding/provision",
                    json=_payload(card_setup_token="tok", payment_method_id="pm_1",
                                  plan="starter"))
    assert seen["consumed"] == []


def test_a_successful_pilot_signup_consumes_exactly_once(client, monkeypatch):
    seen = _flow(monkeypatch)
    with _pilot_world([_grant()], []):
        r = client.post("/onboarding/provision",
                        json=_payload(card_setup_token="tok", payment_method_id="pm_1",
                                      plan="starter", email="o@x.ie",
                                      password="hunter2hunter2"))
    assert r.status_code == 200
    assert r.json()["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED
    assert seen["consumed"] == [{"onboarding_key": KEY, "tenant_id": TENANT}]
    assert seen["trial"] == 0 and seen["welcome"] == 0


def test_the_access_decision_never_consumes():
    """Deciding is a read."""
    refs = identifiers(country_access)
    assert "consume" not in refs


# ═══ 4. scope and spoofing, still intact after the move ═════════════════

def test_a_grant_still_authorizes_only_its_own_key(client, monkeypatch):
    _flow(monkeypatch)
    with _pilot_world([_grant()], []):
        r = client.post("/onboarding/provision", json=_payload(key=OTHER_KEY))
    assert _closed(r)


@pytest.mark.parametrize("field", ["allow_ireland", "pilot", "admin_override"])
def test_no_body_field_opens_a_closed_country(client, monkeypatch, field):
    _flow(monkeypatch)
    with _pilot_world([], []):
        r = client.post("/onboarding/provision", json={**_payload(), field: True})
    assert _closed(r)


@pytest.mark.parametrize("header", ["X-Ireland-Pilot", "X-Admin-Override"])
def test_no_header_opens_a_closed_country(client, monkeypatch, header):
    _flow(monkeypatch)
    with _pilot_world([], []):
        r = client.post("/onboarding/provision", json=_payload(),
                        headers={header: "true"})
    assert _closed(r)


# ═══ 5. the ordering itself ═════════════════════════════════════════════

def test_country_access_precedes_every_card_concern():
    """The whole point of the gate, pinned so a future edit cannot quietly undo
    it. Source order, because that IS the behaviour."""
    import inspect
    src = inspect.getsource(onboarding.provision)
    access = src.index("country_access.decide")
    for later in ("read_card_setup_token", "has_card = bool(",
                  "if card_required() and not has_card",
                  "provisioning.provision_tenant(", "create_auth_user"):
        assert access < src.index(later), later


def test_consumption_still_follows_durable_tenant_creation():
    import inspect
    src = inspect.getsource(onboarding.provision)
    assert src.index("provisioning.provision_tenant(") < src.index("ireland_pilot.consume")
    assert src.index("country_access.decide") < src.index("ireland_pilot.consume")


def test_there_is_one_country_decision_and_one_onboarding_flow():
    import inspect
    src = inspect.getsource(onboarding.provision)
    assert src.count("country_access.decide") == 1
    assert src.count("provisioning.provision_tenant(") == 1
    for fork in ("create_pilot_tenant", "admin_create_irish_tenant"):
        assert fork not in src


def test_an_unregulated_country_never_reads_the_grants_table():
    """Short-circuited before any lookup, so CA and US cannot be affected by
    anything in that table."""
    import inspect
    src = inspect.getsource(country_access.decide)
    guard = src.index("needs_regulatory_clearance")
    assert guard < src.index("ireland_pilot.decide")


# ═══ 6. the access function itself ══════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["CA", "US"])
async def test_unregulated_is_allowed_without_a_grant_lookup(country):
    with patch.object(country_access.ireland_pilot, "decide", new=AsyncMock()) as look:
        out = await country_access.decide(iso_country=country, onboarding_key=KEY)
    assert out["access"] == country_access.ALLOWED
    assert out["reason"] == country_access.UNREGULATED
    assert out["pilot_grant"] is False
    look.assert_not_called()


@pytest.mark.asyncio
async def test_public_ireland_is_allowed_without_a_grant_lookup(monkeypatch):
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    with patch.object(country_access.ireland_pilot, "decide", new=AsyncMock()) as look:
        out = await country_access.decide(iso_country="IE", onboarding_key=KEY)
    assert out["access"] == country_access.ALLOWED
    assert out["reason"] == country_access.PUBLICLY_OPEN
    assert out["pilot_grant"] is False
    look.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,access,grant", [
    (pilot.ALLOW_CREATE, country_access.ALLOWED, True),
    (pilot.ALLOW_RESUME, country_access.ALLOWED, True),
    (pilot.DENY, country_access.DENIED, False),
    (pilot.INTEGRITY, country_access.DENIED, False),
])
async def test_every_pilot_outcome_maps_correctly(monkeypatch, outcome, access, grant):
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    with patch.object(country_access.ireland_pilot, "decide",
                      new=AsyncMock(return_value={"outcome": outcome, "reason": "x"})):
        out = await country_access.decide(iso_country="IE", onboarding_key=KEY)
    assert out["access"] == access
    assert out["pilot_grant"] is grant


# ═══ 7. an integrity failure is silent to the customer, loud to an operator ══
#
# Mutation testing found this unpinned: deleting the integrity branch still
# DENIES -- it falls through to the same refusal -- so behaviour looked
# identical and every test stayed green. What is lost is the alert, and an
# integrity failure nobody is told about is the one that stays broken.

@pytest.mark.asyncio
async def test_an_integrity_failure_is_logged_distinctly(monkeypatch, caplog):
    import logging
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    with patch.object(country_access.ireland_pilot, "decide",
                      new=AsyncMock(return_value={"outcome": pilot.INTEGRITY,
                                                  "reason": "bound_tenant_mismatch"})), \
         caplog.at_level(logging.ERROR, logger="services.country_access"):
        out = await country_access.decide(iso_country="IE", onboarding_key=KEY)
    assert out["access"] == country_access.DENIED
    assert out["reason"] == "integrity"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "an integrity failure produced no operator alert"
    assert "integrity" in errors[0].getMessage().lower()


@pytest.mark.asyncio
async def test_an_ordinary_refusal_is_not_an_error(monkeypatch, caplog):
    """A closed country is the normal state, not an incident. Logging every
    refusal at ERROR would bury the one that matters."""
    import logging
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    with patch.object(country_access.ireland_pilot, "decide",
                      new=AsyncMock(return_value={"outcome": pilot.DENY,
                                                  "reason": "no_grant"})), \
         caplog.at_level(logging.ERROR, logger="services.country_access"):
        out = await country_access.decide(iso_country="IE", onboarding_key=KEY)
    assert out["access"] == country_access.DENIED
    assert out["reason"] == "no_grant"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_the_integrity_reason_is_never_the_customer_facing_one():
    """The customer gets an identical refusal; only the internal reason differs,
    and it never reaches a response body."""
    with patch.object(country_access.ireland_pilot, "decide",
                      new=AsyncMock(return_value={"outcome": pilot.INTEGRITY,
                                                  "reason": "bound_tenant_mismatch"})):
        out = await country_access.decide(iso_country="IE", onboarding_key=KEY)
    assert "bound_tenant_mismatch" not in str(out["reason"])
