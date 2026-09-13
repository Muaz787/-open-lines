"""W9I-H.0 — one operator-authorized Ireland signup, and nothing else.

THE HOLE THE CHECKPOINT REVIEW FOUND, AND WHAT CLOSES IT
The first design said a consumed grant simply keeps opening the gate, because
migration 031's unique index on tenants.onboarding_key makes a second tenant
impossible. That proof holds only while the first tenant EXISTS. Delete it -- a
legitimate purge, a GDPR erasure -- and no row owns the key: the index protects
nothing, and the consumed grant would regain the power to create a brand new
tenant. An immutable audit record would have become durable authorization.

So CREATE authority and RESUME authority are separate, and what separates them
is whether the bound tenant is still there. The tests below are grouped by that
distinction, and the ones that matter most are the purge cases.
"""
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import onboarding
from services import ireland_pilot as pilot
from services import onboarding_lifecycle as lifecycle_ob
from tests.module_identifiers import identifiers

KEY = "e1f0b077-852f-43f1-b4fe-45c0aae97787"
OTHER_KEY = "a2c3d4e5-6789-4abc-8def-0123456789ab"
TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
FUTURE = "2099-01-01T00:00:00+00:00"
PAST = "2000-01-01T00:00:00+00:00"


def _grant(**over):
    return {"onboarding_key": KEY, "iso_country": "IE", "expires_at": FUTURE,
            "created_at": "2026-01-01T00:00:00+00:00", "consumed_at": None,
            "consumed_tenant_id": None, "note": "pilot", **over}


def _world(grants=None, tenants=None):
    """The two reads decide() makes, and nothing else."""
    grants = grants if grants is not None else []
    tenants = tenants if tenants is not None else []

    class QB:
        def __init__(self, table): self.t, self.f = table, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.f[c] = v; return self
        def limit(self, *a): return self
        def is_(self, c, v): self.f[f"is_{c}"] = v; return self
        def gt(self, c, v): self.f[f"gt_{c}"] = v; return self
        def update(self, p): self.patch = p; return self
        def execute(self):
            rows = grants if self.t == pilot.TABLE else tenants
            out = [r for r in rows
                   if all(str(r.get(c)) == str(v) for c, v in self.f.items()
                          if not c.startswith(("is_", "gt_")))]
            # Honour the fence. Without this a "lost race" test silently
            # exercises a won one, which is how the fence stops being tested.
            for c, v in self.f.items():
                if c.startswith("is_") and v == "null":
                    out = [r for r in out if r.get(c[3:]) is None]
            class R: data = [dict(r) for r in out]
            return R()

    return patch.object(pilot, "get_client",
                        return_value=type("C", (), {"table": lambda s, n: QB(n)})())


# ═══ 1. the four states ════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_an_unused_unexpired_grant_authorizes_create():
    with _world(grants=[_grant()]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.ALLOW_CREATE


@pytest.mark.asyncio
async def test_no_grant_denies():
    with _world(grants=[]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY and out["reason"] == "no_grant"


@pytest.mark.asyncio
async def test_an_expired_unused_grant_denies():
    with _world(grants=[_grant(expires_at=PAST)]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY and out["reason"] == "grant_expired"


@pytest.mark.asyncio
async def test_a_consumed_grant_with_its_tenant_authorizes_resume_only():
    with _world(grants=[_grant(consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=TENANT)],
                tenants=[{"id": TENANT, "onboarding_key": KEY}]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.ALLOW_RESUME
    assert out["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_a_consumed_grant_whose_tenant_was_purged_denies():
    """THE checkpoint correction. After a purge nothing owns the key, so 031's
    unique index protects nothing -- only this denial stops the historical grant
    from creating a brand new tenant."""
    with _world(grants=[_grant(consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=TENANT)],
                tenants=[]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY
    assert out["reason"] == "bound_tenant_missing"


@pytest.mark.asyncio
async def test_a_consumed_grant_bound_to_another_tenant_fails_closed():
    with _world(grants=[_grant(consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=OTHER_TENANT)],
                tenants=[{"id": TENANT, "onboarding_key": KEY}]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.INTEGRITY
    assert out["reason"] == "bound_tenant_mismatch"


@pytest.mark.asyncio
async def test_an_expired_but_consumed_grant_still_resumes_its_tenant():
    """Expiry means the INVITATION lapsed, not that the account is over. A
    customer part-way through onboarding must not be bricked behind them."""
    with _world(grants=[_grant(expires_at=PAST,
                               consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=TENANT)],
                tenants=[{"id": TENANT, "onboarding_key": KEY}]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.ALLOW_RESUME


@pytest.mark.asyncio
async def test_an_expired_consumed_grant_with_no_tenant_still_denies():
    """Expiry never restores create authority, and neither does its absence."""
    with _world(grants=[_grant(expires_at=PAST,
                               consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=TENANT)],
                tenants=[]):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY


# ═══ 2. scope: one key, one country ═══════════════════════════════════════

@pytest.mark.asyncio
async def test_a_grant_authorizes_only_its_own_key():
    with _world(grants=[_grant()]):
        out = await pilot.decide(onboarding_key=OTHER_KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY


@pytest.mark.parametrize("country", ["CA", "US", "GB"])
@pytest.mark.asyncio
async def test_an_ireland_grant_authorizes_no_other_country(country):
    with _world(grants=[_grant()]):
        out = await pilot.decide(onboarding_key=KEY, iso_country=country)
    assert out["outcome"] == pilot.DENY


@pytest.mark.asyncio
async def test_a_missing_key_denies():
    for key in ("", "   ", None):
        with _world(grants=[_grant()]):
            out = await pilot.decide(onboarding_key=key, iso_country="IE")
        assert out["outcome"] == pilot.DENY


@pytest.mark.asyncio
async def test_an_unreadable_database_denies():
    """Not knowing is not permission."""
    class Boom:
        def table(self, n): raise TimeoutError("postgrest down")
    with patch.object(pilot, "get_client", return_value=Boom()):
        out = await pilot.decide(onboarding_key=KEY, iso_country="IE")
    assert out["outcome"] == pilot.DENY and out["reason"] == "grant_lookup_failed"


# ═══ 3. consumption ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_consumption_is_fenced_on_being_unused_and_unexpired():
    from services import ireland_pilot as p
    seen = {}

    class Rec:
        def table(self, n): self.t = n; self.f = {}; return self
        def update(self, patch): seen["patch"] = patch; return self
        def eq(self, c, v): self.f[c] = v; seen.setdefault("eq", {})[c] = v; return self
        def is_(self, c, v): seen.setdefault("is", {})[c] = v; return self
        def gt(self, c, v): seen.setdefault("gt", {})[c] = v; return self
        def execute(self): return type("R", (), {"data": [_grant()]})()

    with patch.object(p, "get_client", return_value=Rec()):
        out = await p.consume(onboarding_key=KEY, tenant_id=TENANT)
    assert out["ok"] is True and out["created"] is True
    assert seen["eq"] == {"onboarding_key": KEY}
    assert seen["is"] == {"consumed_at": "null"}
    assert "expires_at" in seen["gt"]
    assert seen["patch"]["consumed_tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_losing_the_consumption_race_converges_on_the_same_tenant():
    """Another worker consumed the same grant for the same signup. That is the
    outcome we wanted, so it is a success -- but only after checking."""
    class Rec:
        def table(self, n): self.t = n; self.f = {}; return self
        def update(self, p): return self
        def eq(self, c, v): self.f[c] = v; return self
        def is_(self, c, v): return self
        def gt(self, c, v): return self
        def limit(self, *a): return self
        def select(self, *a): return self
        def execute(self):
            if self.t == pilot.TABLE and not self.f.get("iso_country"):
                return type("R", (), {"data": []})()      # the fenced update lost
            rows = ([_grant(consumed_at="2026-02-01T00:00:00+00:00",
                            consumed_tenant_id=TENANT)]
                    if self.t == pilot.TABLE else [{"id": TENANT, "onboarding_key": KEY}])
            return type("R", (), {"data": rows})()

    with patch.object(pilot, "get_client", return_value=Rec()):
        out = await pilot.consume(onboarding_key=KEY, tenant_id=TENANT)
    assert out["ok"] is True and out["created"] is False


@pytest.mark.asyncio
async def test_losing_the_race_to_a_different_tenant_fails_closed():
    with _world(grants=[_grant(consumed_at="2026-02-01T00:00:00+00:00",
                               consumed_tenant_id=OTHER_TENANT)],
                tenants=[{"id": OTHER_TENANT, "onboarding_key": KEY}]):
        out = await pilot.consume(onboarding_key=KEY, tenant_id=TENANT)
    assert out["ok"] is False


# ═══ 4. the gate, end to end through the real route ═══════════════════════

@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(onboarding.router)
    monkeypatch.setattr(onboarding.limiter, "enabled", False, raising=False)
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    monkeypatch.setattr(onboarding, "card_required", lambda: False)
    return TestClient(app, raise_server_exceptions=False)


def _payload(country="IE", key=KEY, **over):
    return {"business_name": "Acme", "industry": "realtor", "country": country,
            "owner_name": "O", "agent_name": "A", "website_url": "",
            "email": "owner@example.ie", "password": "hunter2hunter2",
            "onboarding_key": key, **over}


def _signup(monkeypatch, *, verdict, country="IE"):
    seen = {"provisioned": 0, "consumed": [], "trial": 0, "welcome": 0}

    async def decide(**kw):
        seen["decide"] = kw
        return verdict

    async def consume(**kw):
        seen["consumed"].append(kw)
        return {"ok": True, "created": True}

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

    async def trial(**kw):
        seen["trial"] += 1
        return {"ok": True}

    async def welcome(**kw):
        seen["welcome"] += 1
        return True

    monkeypatch.setattr(onboarding.ireland_pilot, "decide", decide)
    monkeypatch.setattr(onboarding.ireland_pilot, "consume", consume)
    monkeypatch.setattr(onboarding.provisioning, "provision_tenant", provision)
    monkeypatch.setattr(onboarding.db, "create_auth_user", AsyncMock(return_value="u1"))
    monkeypatch.setattr(onboarding.db, "update_tenant", AsyncMock(return_value={}))
    monkeypatch.setattr(onboarding.subscriptions, "create_trial_subscription", trial)
    monkeypatch.setattr(onboarding.subscriptions, "read_card_setup_token",
                        lambda t: "cus_123")
    # W9I-H.0.2: provision now resolves the Customer from the payment session
    # rather than believing the client's token. Stated explicitly -- conftest
    # stubs Supabase with a truthy MagicMock, so an unpatched lookup "finds" a
    # binding that does not exist and the mismatch guard fires.
    monkeypatch.setattr(onboarding.payment_customer, "resolve_for_tenant",
                        AsyncMock(return_value="cus_123"))
    monkeypatch.setattr("services.email.send_welcome_email", welcome)
    return seen


def test_ireland_without_a_grant_is_refused(client, monkeypatch):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY, "reason": "no_grant"})
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "country_onboarding_not_open"
    assert seen["provisioned"] == 0


def test_ireland_with_a_grant_reaches_regulatory_required(client, monkeypatch):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.ALLOW_CREATE})
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 200
    assert r.json()["onboarding_state"] == lifecycle_ob.REGULATORY_REQUIRED
    assert seen["decide"]["onboarding_key"] == KEY
    assert seen["decide"]["iso_country"] == "IE"


def test_an_integrity_failure_is_refused_like_any_closed_country(client, monkeypatch):
    """The customer must not learn that a grant exists, or that it is broken."""
    seen = _signup(monkeypatch, verdict={"outcome": pilot.INTEGRITY,
                                         "reason": "bound_tenant_mismatch"})
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "country_onboarding_not_open"
    assert "integrity" not in r.text.lower() and "grant" not in r.text.lower()
    assert seen["provisioned"] == 0


def test_a_purged_tenants_key_cannot_create_a_replacement(client, monkeypatch):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY,
                                         "reason": "bound_tenant_missing"})
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 503
    assert seen["provisioned"] == 0, "a historical grant created a tenant"


def test_the_grant_is_consumed_only_after_a_durable_tenant_exists(client, monkeypatch):
    """Consuming at the gate would let a transient provisioning failure burn the
    invitation and brick the pilot."""
    seen = _signup(monkeypatch, verdict={"outcome": pilot.ALLOW_CREATE})
    client.post("/onboarding/provision", json=_payload())
    assert seen["provisioned"] == 1
    assert seen["consumed"] == [{"onboarding_key": KEY, "tenant_id": TENANT}]


def test_a_provisioning_failure_does_not_burn_the_grant(client, monkeypatch):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.ALLOW_CREATE})

    async def boom(payload):
        raise RuntimeError("twilio down")

    monkeypatch.setattr(onboarding.provisioning, "provision_tenant", boom)
    client.post("/onboarding/provision", json=_payload())
    assert seen["consumed"] == []


def test_the_pilot_grant_starts_no_billing_and_sends_no_welcome(client, monkeypatch):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.ALLOW_CREATE})
    client.post("/onboarding/provision", json=_payload())
    assert seen["trial"] == 0 and seen["welcome"] == 0


# ═══ 5. spoofing ══════════════════════════════════════════════════════════

@pytest.mark.parametrize("field", ["allow_ireland", "pilot", "admin_override",
                                   "bypass", "ireland_pilot", "force_country"])
def test_no_request_body_field_can_open_ireland(client, monkeypatch, field):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY, "reason": "no_grant"})
    r = client.post("/onboarding/provision", json={**_payload(), field: True})
    assert r.status_code == 503
    assert seen["provisioned"] == 0


@pytest.mark.parametrize("header", ["X-Ireland-Pilot", "X-Admin-Override",
                                    "X-Allow-Ireland", "Authorization"])
def test_no_header_can_open_ireland(client, monkeypatch, header):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY, "reason": "no_grant"})
    r = client.post("/onboarding/provision", json=_payload(),
                    headers={header: "true"})
    assert r.status_code == 503
    assert seen["provisioned"] == 0


def test_a_spoofed_attempt_is_indistinguishable_from_an_ordinary_refusal(client, monkeypatch):
    _signup(monkeypatch, verdict={"outcome": pilot.DENY, "reason": "no_grant"})
    plain = client.post("/onboarding/provision", json=_payload())
    spoof = client.post("/onboarding/provision",
                        json={**_payload(), "pilot": True, "admin_override": True},
                        headers={"X-Ireland-Pilot": "yes"})
    assert plain.status_code == spoof.status_code == 503
    assert plain.json() == spoof.json()


def test_the_decision_reads_only_the_key_and_country():
    """Nothing a customer sends beyond the already-validated uuid4 participates."""
    import inspect
    src = inspect.getsource(pilot.decide)
    for smell in ("request", "header", "body", "payload"):
        assert smell not in src, smell


# ═══ 6. no downstream privilege ═══════════════════════════════════════════

def test_the_grant_confers_nothing_beyond_the_country_gate():
    """Regulatory filing, number purchase, billing and launch each have their own
    gate, and none of them may read this one."""
    from services import (permanent_activation, permanent_numbers,
                          regulatory_engine, regulatory_filing, temporary_numbers)
    from routers import regulatory, regulatory_verification
    for module in (permanent_activation, permanent_numbers, regulatory_engine,
                   regulatory_filing, temporary_numbers, regulatory,
                   regulatory_verification):
        refs = identifiers(module)
        for forbidden in ("ireland_pilot", "ALLOW_CREATE", "ALLOW_RESUME",
                          "ireland_pilot_onboarding_grants"):
            assert forbidden not in refs, (module.__name__, forbidden)


def test_the_pilot_module_cannot_reach_anything_but_its_own_table():
    refs = identifiers(pilot)
    for forbidden in ("provision_tenant", "create_trial_subscription",
                      "purchase_number", "purchase_regulated_number",
                      "record_authorization", "prepare_profile", "send_welcome_email",
                      "mark_active", "ensure_temporary_number"):
        assert forbidden not in refs, forbidden


def test_the_pilot_flow_is_not_a_fork():
    """One Ireland product flow. No create_pilot_tenant, no admin shortcut."""
    import inspect
    src = inspect.getsource(onboarding.provision)
    for fork in ("create_pilot_tenant", "admin_create_irish_tenant",
                 "special_dani_signup", "pilot_provision"):
        assert fork not in src, fork
    # the ONE normal provisioner, called once
    assert src.count("provisioning.provision_tenant(") == 1


# ═══ 7. nothing else changed ══════════════════════════════════════════════

@pytest.mark.parametrize("country", ["CA", "US"])
def test_unregulated_signup_never_consults_the_grant(client, monkeypatch, country):
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY}, country=country)
    r = client.post("/onboarding/provision",
                    json=_payload(country=country, card_setup_token="tok",
                                  payment_method_id="pm_1", plan="starter"))
    assert r.status_code == 200
    assert "decide" not in seen, "a CA/US signup read the Ireland grant table"
    # ...and still bills and welcomes exactly as before.
    assert seen["trial"] == 1 and seen["welcome"] == 1


def test_the_public_flag_is_untouched(monkeypatch):
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    assert lifecycle_ob.ireland_onboarding_enabled() is False


def test_a_public_flag_ON_does_not_consult_the_grant(client, monkeypatch):
    """The grant is a way past a CLOSED gate, not an extra check on an open one."""
    seen = _signup(monkeypatch, verdict={"outcome": pilot.DENY})
    monkeypatch.setenv("IRELAND_ONBOARDING_ENABLED", "true")
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 200
    assert "decide" not in seen


# ═══ 8. the refusal says nothing ══════════════════════════════════════════
#
# Mutation testing found this unpinned: adding the internal reason to the 503
# body left every other test green. A customer must not be able to tell a
# missing grant from an expired one from an integrity failure -- and must not
# learn that a grant mechanism exists at all.

REFUSAL_KEYS = {"status", "country", "message"}


@pytest.mark.parametrize("verdict", [
    {"outcome": pilot.DENY, "reason": "no_grant"},
    {"outcome": pilot.DENY, "reason": "grant_expired"},
    {"outcome": pilot.DENY, "reason": "bound_tenant_missing"},
    {"outcome": pilot.DENY, "reason": "grant_lookup_failed"},
    {"outcome": pilot.INTEGRITY, "reason": "bound_tenant_mismatch"},
])
def test_every_refusal_is_byte_identical(client, monkeypatch, verdict):
    _signup(monkeypatch, verdict=verdict)
    r = client.post("/onboarding/provision", json=_payload())
    assert r.status_code == 503
    detail = r.json()["detail"]
    # EXACTLY these keys. An extra one is a channel.
    assert set(detail) == REFUSAL_KEYS, sorted(detail)
    assert detail["status"] == "country_onboarding_not_open"
    assert detail["country"] == "IE"
    blob = r.text.lower()
    for leak in ("grant", "pilot", "integrity", "expired", "consumed", "allowlist",
                 "override", "bypass", "tenant_missing", "mismatch"):
        assert leak not in blob, leak


def test_all_refusals_are_identical_to_each_other(client, monkeypatch):
    bodies = set()
    for verdict in ({"outcome": pilot.DENY, "reason": "no_grant"},
                    {"outcome": pilot.DENY, "reason": "bound_tenant_missing"},
                    {"outcome": pilot.INTEGRITY, "reason": "bound_tenant_mismatch"}):
        _signup(monkeypatch, verdict=verdict)
        r = client.post("/onboarding/provision", json=_payload())
        bodies.add(r.text)
    assert len(bodies) == 1, bodies
