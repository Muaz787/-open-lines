"""W9I-C — the customer-facing Ireland verification flow.

WHAT THIS SUITE IS DEFENDING
Three things, in order of how badly they fail.

1. GATE 1. The collection flow must not be able to create a provider IDENTITY --
   an EndUser, a SupportingDocument, a Bundle. Those carry a real person's name to
   Twilio and are what W9I-D exists to do deliberately. Address validation is the
   one permitted provider write.

2. WHAT THE CUSTOMER AUTHORISED. The review must be built from persisted rows, and
   the authorisation must apply to the exact facts that were read -- not to
   whatever is in the database at the instant of the click, and never to a digest
   the client supplied.

3. WHAT THE CUSTOMER IS TOLD. No provider error text, SID or code reaches a
   response body, and a provider outage is never described as bad customer data.
"""
import re
import time
from typing import Annotated
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from routers import regulatory_verification as rv
from services import regulatory_authorization as auth
from services import regulatory_customer_errors as cx
from services import regulatory_engine as engine
from services import regulatory_review as review
from tests.module_identifiers import identifiers as _identifiers

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
ADDR = "33333333-3333-3333-3333-333333333333"
ADDR2 = "44444444-4444-4444-4444-444444444444"
EMAIL = "owner@example.ie"

DETAILS = {
    "business_name": "Example Trading Limited",
    "business_website": "https://example.ie",
    "business_registration_number": "123456",
    "authorized_rep_first_name": "Aoife",
    "authorized_rep_last_name": "Ni Bhriain",
    "authorized_rep_email": "aoife@example.ie",
}
ADDRESS = {
    "id": ADDR, "tenant_id": TENANT, "iso_country": "IE",
    "street": "20 Thomas Street", "street_secondary": "", "city": "Limerick",
    "region": "Limerick", "postal_code": "V94 HT0X", "validated": True,
    "address_sid": "ADqa_secret_sid", "provider_account_sid": "ACqa_secret",
    "tenant_location_id": None,
}


class _Fields:
    """A minimal stand-in for a discovered RegulationRequirementSet."""
    iso_country, number_type, end_user_type = "IE", "local", "business"
    regulation_sid, friendly_name = "RNqa_secret", "Ireland: Local/Business"
    documents: list = []

    def fingerprint(self):
        return "f" * 64


@pytest.fixture
def client(monkeypatch):
    """The REAL router, with only the auth dependencies stood in for.

    Ownership is enforced by the same contract production uses -- the bearer token
    must equal the path tenant -- so every ownership test below exercises the real
    routing, not a bypass.
    """
    from services.security import authenticated_tenant_user, require_tenant_owner

    state = {
        "tenant": {"id": TENANT, "business_name": "Example Trading",
                   "business_country_code": "IE",
                   "onboarding_state": "regulatory_required"},
        "details": dict(DETAILS),
        "addresses": [dict(ADDRESS)],
        "authorizations": [],
        "requirements_ok": True,
        "prepare_profile_calls": [],
    }

    async def fake_owner(request: Request,
                         authorization: Annotated[str | None, Header()] = None):
        token = (authorization or "").removeprefix("Bearer ").strip()
        tid = request.path_params.get("tenant_id")
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        if token != tid:
            raise HTTPException(status_code=403, detail="Access denied")

    async def fake_identity(request: Request,
                            authorization: Annotated[str | None, Header()] = None):
        await fake_owner(request, authorization)
        return {"user_id": "u1", "email": state.get("auth_email", EMAIL),
                "tenant_id": request.path_params.get("tenant_id")}

    app = FastAPI()
    app.include_router(rv.router)
    app.dependency_overrides[require_tenant_owner] = fake_owner
    app.dependency_overrides[authenticated_tenant_user] = fake_identity

    # ── repository ───────────────────────────────────────────────────────
    async def get_details(tid, country, end_user_type="business"):
        return dict(state["details"]) if state["details"] else None

    async def upsert_details(tid, country, *, end_user_type="business", values):
        patch_ = {k: v for k, v in values.items()
                  if str(v if v is not None else "").strip() != ""}
        state["details"].update(patch_)
        return dict(state["details"])

    async def get_address(tid, aid):
        for a in state["addresses"]:
            if a["id"] == aid and a["tenant_id"] == tid:
                return dict(a)
        return None

    monkeypatch.setattr(rv.db_reg, "get_business_details", get_details)
    monkeypatch.setattr(rv.db_reg, "upsert_business_details", upsert_details)
    monkeypatch.setattr(rv.db_reg, "get_address", get_address)

    class FakeQB:
        def __init__(self, table, st): self.table, self.st, self.f = table, st, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.f[c] = v; return self
        def limit(self, *a, **k): return self
        def order(self, *a, **k): return self
        def execute(self):
            rows = ([self.st["tenant"]] if self.table == "tenants"
                    else self.st["addresses"] if self.table == "tenant_regulatory_addresses"
                    else [])
            for c, v in self.f.items():
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            class R: data = [dict(r) for r in rows]
            return R()

    monkeypatch.setattr(rv, "get_client",
                        lambda: type("C", (), {"table": lambda s, n: FakeQB(n, state)})())

    # ── engine ───────────────────────────────────────────────────────────
    async def requirements_for(tenant, **kw):
        if not state["requirements_ok"]:
            return {"ok": False, "status": engine.PROVIDER_UNAVAILABLE,
                    "detail": "twilio 503 ProviderError RNqa_secret"}
        return {"ok": True, "status": engine.OK, "requirements": _Fields(),
                "fingerprint": "f" * 64,
                "fields": [
                    {"name": "business_name", "label": "Registered business name",
                     "source": "customer", "required": True, "options": [],
                     "help": "As registered", "resolved": True},
                    {"name": "business_identity", "label": "Business identity",
                     "source": "operator", "required": True, "options": [],
                     "help": "set by us", "resolved": False},
                ]}
    monkeypatch.setattr(rv.engine, "requirements_for", requirements_for)

    async def check_authorization(tid, *, iso_country, end_user_type, address_row, details):
        fp = auth.fingerprint_for(details, address_row)
        for a in state["authorizations"]:
            if (a["tenant_regulatory_address_id"] == address_row["id"]
                    and a["authorized_details_fingerprint"] == fp
                    and a.get("authorization_revoked_at") is None):
                return {"ok": True, "status": engine.OK, "authorization": a}
        return {"ok": False, "status": engine.AUTHORIZATION_NOT_RECORDED}
    monkeypatch.setattr(rv.engine, "check_authorization", check_authorization)

    async def record_authorization(tid, *, iso_country, end_user_type, address_row,
                                   details, authorized_by, authorization_method):
        fp = auth.fingerprint_for(details, address_row)
        for a in state["authorizations"]:
            if (a["tenant_regulatory_address_id"] == address_row["id"]
                    and a["authorized_details_fingerprint"] == fp
                    and a.get("authorization_revoked_at") is None):
                return {"ok": True, "status": engine.OK, "authorization": a,
                        "created": False}
        row = {"id": f"auth{len(state['authorizations'])}", "tenant_id": tid,
               "iso_country": iso_country, "end_user_type": end_user_type,
               "tenant_regulatory_address_id": address_row["id"],
               "authorized_details_fingerprint": fp,
               "authorized_by": authorized_by,
               "authorization_method": authorization_method,
               # server clock, as the engine does
               "authorized_at": engine._now_iso(),
               "authorization_revoked_at": None}
        state["authorizations"].append(row)
        return {"ok": True, "status": engine.OK, "authorization": row, "created": True}
    monkeypatch.setattr(rv.engine, "record_authorization", record_authorization)

    async def ensure_address(tenant, *, submitted, tenant_location_id=None, **kw):
        if state.get("address_outage"):
            return {"ok": False, "status": engine.PROVIDER_UNAVAILABLE,
                    "detail": "HTTP 503 from https://api.twilio.com AD_secret"}
        if state.get("address_invalid"):
            return {"ok": False, "status": engine.ADDRESS_VALIDATION_FAILED,
                    "detail": "twilio_code 21628 ProviderError AddressSid ADbad"}
        row = {**ADDRESS, **submitted, "id": ADDR, "tenant_id": TENANT,
               "validated": True, "tenant_location_id": tenant_location_id}
        state["addresses"] = [row] + [a for a in state["addresses"] if a["id"] != ADDR]
        return {"ok": True, "status": engine.OK, "address": row, "reused": False}
    monkeypatch.setattr(rv.engine, "ensure_address", ensure_address)

    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "ab" * 32)
    return TestClient(app, raise_server_exceptions=False), state


def hdr(tid=TENANT):
    return {"Authorization": f"Bearer {tid}"}


def _review(c, state, addr=ADDR):
    r = c.get(f"/regulatory/{TENANT}/verification/review",
              params={"regulatory_address_id": addr}, headers=hdr())
    assert r.status_code == 200, r.text
    return r.json()


# ═══ 1. ownership: every route, no exceptions ═══════════════════════════════

ROUTES = [
    ("GET", "/requirements", None),
    ("GET", "/state", None),
    ("POST", "/details", {"business_name": "X"}),
    ("POST", "/address", {"address": {"street": "1 Main St", "city": "Cork"}}),
    ("GET", "/review", None),
    ("POST", "/authorize", {"consent": True, "regulatory_address_id": ADDR}),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_no_token_is_refused(client, method, path, body):
    c, _ = client
    r = c.request(method, f"/regulatory/{TENANT}/verification{path}", json=body)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_another_tenants_token_is_refused(client, method, path, body):
    """The path tenant_id is never authority on its own."""
    c, _ = client
    r = c.request(method, f"/regulatory/{TENANT}/verification{path}",
                  json=body, headers=hdr(OTHER))
    assert r.status_code == 403


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_an_onboarding_key_is_not_authentication(client, method, path, body):
    """W9I-B's onboarding_key resumes a signup. It is a claim ticket, not a
    credential, and must open no regulatory door."""
    c, _ = client
    key = "e1f0b077-852f-43f1-b4fe-45c0aae97787"
    for attempt in ({"Authorization": f"Bearer {key}"},
                    {"X-Onboarding-Key": key},
                    {}):
        r = c.request(method, f"/regulatory/{TENANT}/verification{path}",
                      json=body, headers=attempt)
        assert r.status_code in (401, 403), (path, attempt, r.status_code)


def test_every_route_is_scoped_to_a_path_tenant_id():
    for route in rv.router.routes:
        assert "{tenant_id}" in route.path, route.path


def test_the_router_carries_the_ownership_dependency():
    assert len(rv.router.dependencies) == 1
    assert rv.router.dependencies[0].dependency.__name__ == "require_tenant_owner"


# ═══ 2. Gate 1 — no provider identity is reachable from here ════════════════

FORBIDDEN_IDENTITY_CALLS = (
    "prepare_profile", "resolve_end_user", "ensure_supporting_document",
    "ensure_bundle", "ensure_item_assignments", "submit_bundle",
    "claim_provider_resource", "insert_profile",
    # W9I-D: this router may READ where a filing stands (customer_status is a
    # pure translation of a stored state) but must not DRIVE one. advance()
    # reaches every resource above, so importing regulatory_filing for the status
    # view must not quietly reopen the door the rest of this list closes.
    "advance", "submit_profile", "evaluate_profile",
)


def test_the_verification_router_cannot_create_a_provider_identity():
    """Structural, not behavioural. The collection flow has no code path to a
    provider identity, so no future edit can reach one without deleting this
    test first."""
    referenced = _identifiers(rv)
    for forbidden in FORBIDDEN_IDENTITY_CALLS:
        assert forbidden not in referenced, forbidden


def test_the_gate_1_names_are_real_functions_that_exist_to_be_avoided():
    """Guards the guard. If prepare_profile were renamed, the test above would
    pass vacuously against a name nothing has, while the router happily called
    the new one."""
    assert hasattr(engine, "prepare_profile")
    assert hasattr(engine, "resolve_end_user")
    assert hasattr(engine, "ensure_supporting_document")
    assert hasattr(engine, "ensure_bundle")
    assert hasattr(engine, "ensure_item_assignments")


def test_authorization_does_not_trigger_filing(client):
    """The click authorises facts, not a filing. Anything downstream would cross
    Gate 1 on a consent that never covered it."""
    c, state = client
    snap = _review(c, state)
    with patch.object(engine, "prepare_profile", new=AsyncMock()) as prep:
        r = c.post(f"/regulatory/{TENANT}/verification/authorize",
                   json={"consent": True, "regulatory_address_id": ADDR,
                         "review_token": snap["review_token"]}, headers=hdr())
    assert r.status_code == 200, r.text
    prep.assert_not_called()
    assert r.json()["filing_submitted"] is False
    assert r.json()["next_state"] == "ready_for_regulatory_filing"


# ═══ 3. system-owned values are refused, never filtered ════════════════════

@pytest.mark.parametrize("field,value", [
    ("business_identity", "INDEPENDENT_SOFTWARE_VENDOR"),
    ("is_subassigned", "YES"),
    ("requirements_fingerprint", "a" * 64),
    ("authorized_at", "2020-01-01T00:00:00+00:00"),
    ("authorized_details_fingerprint", "b" * 64),
    ("authorization_fingerprint", "c" * 64),
])
def test_a_customer_cannot_supply_a_system_owned_value(client, field, value):
    """Refused rather than dropped: silently ignoring an attempt hides it, and a
    field that is quietly stripped today is a field someone wires up tomorrow."""
    c, state = client
    r = c.post(f"/regulatory/{TENANT}/verification/details",
               json={**DETAILS, field: value}, headers=hdr())
    assert r.status_code == 422
    assert r.json()["detail"]["status"] == "system_owned_field"
    assert field in r.json()["detail"]["fields"]
    assert state["details"].get(field) != value


def test_the_declaration_is_never_taken_from_the_customer(client):
    c, state = client
    r = c.get(f"/regulatory/{TENANT}/verification/requirements", headers=hdr())
    names = [f["name"] for f in r.json()["fields"]]
    assert "business_identity" not in names and "is_subassigned" not in names
    assert "business_name" in names


def test_the_authorize_route_refuses_system_owned_values(client):
    c, state = client
    snap = _review(c, state)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap["review_token"],
                     "authorized_at": "1999-01-01T00:00:00+00:00"}, headers=hdr())
    assert r.status_code == 422
    assert r.json()["detail"]["status"] == "system_owned_field"
    assert state["authorizations"] == []


def test_the_authorization_timestamp_is_server_owned(client):
    c, state = client
    snap = _review(c, state)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap["review_token"]}, headers=hdr())
    row = state["authorizations"][0]
    assert row["authorized_at"]
    assert row["authorized_by"] == EMAIL          # from the verified token
    assert row["authorization_method"] == "dashboard"
    assert row["authorization_method"] in auth.METHODS


def test_the_customer_cannot_name_who_authorized(client):
    """A frontend string is worth nothing: whoever can call the route can type
    any name. The identity comes from the bearer token that granted access."""
    c, state = client
    snap = _review(c, state)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap["review_token"],
                 "authorized_by": "ceo@somebodyelse.example"}, headers=hdr())
    assert state["authorizations"][0]["authorized_by"] == EMAIL


# ═══ 4. the review comes from storage ══════════════════════════════════════

def test_the_review_is_built_from_persisted_facts(client):
    c, state = client
    snap = _review(c, state)
    shown = {f["name"]: f["value"] for f in snap["facts"]}
    assert [f["name"] for f in snap["facts"]] == list(auth.FIELDS)
    assert shown["business_name"] == DETAILS["business_name"]
    assert shown["address_postal_code"] == "V94 HT0X"
    assert shown["address_iso_country"] == "IE"


def test_a_modified_request_cannot_change_what_is_reviewed(client):
    """The review takes no body. Query or header tampering changes nothing,
    because every fact is read from the database."""
    c, state = client
    r = c.get(f"/regulatory/{TENANT}/verification/review",
              params={"regulatory_address_id": ADDR,
                      "business_name": "Somebody Else Ltd",
                      "facts": '{"business_name":"Somebody Else Ltd"}'},
              headers=hdr())
    shown = {f["name"]: f["value"] for f in r.json()["facts"]}
    assert shown["business_name"] == DETAILS["business_name"]


def test_the_review_does_not_hand_over_an_editable_digest(client):
    c, state = client
    snap = _review(c, state)
    fp = auth.fingerprint_for(state["details"], state["addresses"][0])
    body = str(snap)
    assert fp not in body          # the raw digest is never exposed
    assert snap["review_token"]    # only the opaque, signed proof is


def test_an_unvalidated_address_cannot_be_reviewed(client):
    c, state = client
    state["addresses"][0]["validated"] = False
    r = c.get(f"/regulatory/{TENANT}/verification/review",
              params={"regulatory_address_id": ADDR}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "verification_incomplete"


def test_incomplete_details_cannot_be_reviewed(client):
    c, state = client
    state["details"].pop("business_registration_number")
    r = c.get(f"/regulatory/{TENANT}/verification/review",
              params={"regulatory_address_id": ADDR}, headers=hdr())
    assert r.status_code == 422
    assert "business_registration_number" in r.json()["detail"]["missing"]


# ═══ 5. review → consent, the TOCTOU boundary ══════════════════════════════

def test_a_stale_review_cannot_authorize_changed_facts(client):
    """THE race: review loads, facts change, click authorises what was never read."""
    c, state = client
    snap = _review(c, state)
    state["details"]["business_website"] = "https://changed.example.ie"
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap["review_token"]}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "review_out_of_date"
    assert r.json()["detail"]["revisit_step"] == "review"
    assert state["authorizations"] == []


def test_an_expired_review_cannot_authorize(client):
    c, state = client
    fp = auth.fingerprint_for(state["details"], state["addresses"][0])
    stale = review.issue(tenant_id=TENANT, iso_country="IE", end_user_type="business",
                         address_id=ADDR, authorization_fingerprint=fp,
                         requirements_fingerprint="f" * 64,
                         now=time.time() - review.TTL_SECONDS - 10)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": stale}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "review_expired"
    assert state["authorizations"] == []


def test_a_review_for_another_tenant_cannot_authorize_this_one(client):
    c, state = client
    fp = auth.fingerprint_for(state["details"], state["addresses"][0])
    foreign = review.issue(tenant_id=OTHER, iso_country="IE", end_user_type="business",
                           address_id=ADDR, authorization_fingerprint=fp,
                           requirements_fingerprint="f" * 64)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": foreign}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "review_wrong_scope"
    assert state["authorizations"] == []


def test_a_review_for_another_address_cannot_authorize_this_one(client):
    c, state = client
    second = {**ADDRESS, "id": ADDR2, "city": "Cork", "postal_code": "T12 ABCD"}
    state["addresses"].append(second)
    snap2 = _review(c, state, addr=ADDR2)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap2["review_token"]}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] in ("review_wrong_scope", "review_out_of_date")
    assert state["authorizations"] == []


def test_a_forged_review_token_is_refused(client):
    c, state = client
    snap = _review(c, state)
    body, sig = snap["review_token"].rsplit(".", 1)
    for bad in (f"{body}.{'A' * len(sig)}", "garbage", f"{body}x.{sig}", ""):
        r = c.post(f"/regulatory/{TENANT}/verification/authorize",
                   json={"consent": True, "regulatory_address_id": ADDR,
                         "review_token": bad}, headers=hdr())
        assert r.status_code in (400, 409), bad
        assert r.json()["detail"]["status"].startswith("review_")
    assert state["authorizations"] == []


def test_consent_must_be_affirmative(client):
    c, state = client
    snap = _review(c, state)
    for consent in (False, None, "yes", 1):
        r = c.post(f"/regulatory/{TENANT}/verification/authorize",
                   json={"consent": consent, "regulatory_address_id": ADDR,
                         "review_token": snap["review_token"]}, headers=hdr())
        assert r.status_code == 422
        assert r.json()["detail"]["status"] == "consent_required"
    assert state["authorizations"] == []


def test_the_consent_wording_is_server_owned(client):
    c, state = client
    snap = _review(c, state)
    assert "authorise OpenLines to submit" in snap["consent_statement"]
    # No legal advice, and no claim it has already been filed.
    assert "submitted to the regulator" not in snap["consent_statement"].lower()


# ═══ 6. idempotency, history, re-authorisation ═════════════════════════════

def test_a_duplicate_authorization_is_idempotent(client):
    c, state = client
    snap = _review(c, state)
    payload = {"consent": True, "regulatory_address_id": ADDR,
               "review_token": snap["review_token"]}
    first = c.post(f"/regulatory/{TENANT}/verification/authorize", json=payload, headers=hdr())
    second = c.post(f"/regulatory/{TENANT}/verification/authorize", json=payload, headers=hdr())
    assert first.status_code == second.status_code == 200
    assert first.json()["created"] is True and second.json()["created"] is False
    assert len(state["authorizations"]) == 1


def test_editing_a_fact_requires_a_fresh_authorization(client):
    """Stage L, through the API: authorise, edit, and the old consent no longer
    covers the new facts. The history row is never rewritten."""
    c, state = client
    snap = _review(c, state)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap["review_token"]}, headers=hdr())
    original = dict(state["authorizations"][0])

    c.post(f"/regulatory/{TENANT}/verification/details",
           json={"business_website": "https://new.example.ie"}, headers=hdr())
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert st["authorizations"][0]["authorized"] is False
    assert st["next_step"] == "review"
    # immutable history
    assert state["authorizations"][0] == original

    # re-review and re-authorise covers the new facts
    snap2 = _review(c, state)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap2["review_token"]}, headers=hdr())
    assert r.json()["created"] is True
    assert len(state["authorizations"]) == 2
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert st["authorizations"][0]["authorized"] is True


def test_restoring_an_edited_fact_revives_the_original_authorization(client):
    """The fingerprint is over the facts, not over time: restoring the exact value
    makes the original consent apply again. Pinned because it is a real property
    of the model that a future 'improvement' could silently remove."""
    c, state = client
    snap = _review(c, state)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap["review_token"]}, headers=hdr())
    c.post(f"/regulatory/{TENANT}/verification/details",
           json={"business_website": "https://new.example.ie"}, headers=hdr())
    assert c.get(f"/regulatory/{TENANT}/verification/state",
                 headers=hdr()).json()["authorizations"][0]["authorized"] is False

    c.post(f"/regulatory/{TENANT}/verification/details",
           json={"business_website": DETAILS["business_website"]}, headers=hdr())
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert st["authorizations"][0]["authorized"] is True
    assert len(state["authorizations"]) == 1


def test_a_revoked_authorization_is_not_silently_reused(client):
    c, state = client
    snap = _review(c, state)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap["review_token"]}, headers=hdr())
    state["authorizations"][0]["authorization_revoked_at"] = "2026-09-12T00:00:00+00:00"
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert st["authorizations"][0]["authorized"] is False


# ═══ 7. multi-location ═════════════════════════════════════════════════════

def test_two_premises_are_authorized_independently(client):
    """DANI has several. A tenant-level shortcut would make that impossible, and
    would also mean authorising Limerick silently authorised Cork."""
    c, state = client
    state["addresses"].append({**ADDRESS, "id": ADDR2, "city": "Cork",
                               "postal_code": "T12 ABCD"})
    snap1 = _review(c, state, addr=ADDR)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR,
                 "review_token": snap1["review_token"]}, headers=hdr())

    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    by_addr = {a["regulatory_address_id"]: a["authorized"] for a in st["authorizations"]}
    assert by_addr[ADDR] is True
    assert by_addr[ADDR2] is False        # Limerick is not Cork

    snap2 = _review(c, state, addr=ADDR2)
    c.post(f"/regulatory/{TENANT}/verification/authorize",
           json={"consent": True, "regulatory_address_id": ADDR2,
                 "review_token": snap2["review_token"]}, headers=hdr())
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert all(a["authorized"] for a in st["authorizations"])
    assert len(state["authorizations"]) == 2


def test_another_tenants_address_is_not_reviewable(client):
    c, state = client
    state["addresses"].append({**ADDRESS, "id": ADDR2, "tenant_id": OTHER})
    r = c.get(f"/regulatory/{TENANT}/verification/review",
              params={"regulatory_address_id": ADDR2}, headers=hdr())
    assert r.status_code == 404
    assert r.json()["detail"]["status"] == "address_not_found"


# ═══ 8. the customer error contract ════════════════════════════════════════

def test_an_invalid_address_asks_for_a_correction(client):
    c, state = client
    state["address_invalid"] = True
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "Nowhere", "city": "Nowhere"}}, headers=hdr())
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["status"] == "address_not_accepted"
    assert d["action_required"] is True and d["revisit_step"] == "address"


def test_a_provider_outage_is_not_called_an_invalid_address(client):
    """Told their real address is invalid, a customer 'fixes' a correct address
    into a wrong one, and the filing then fails for a reason nobody can see."""
    c, state = client
    state["address_outage"] = True
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "20 Thomas Street", "city": "Limerick"}},
               headers=hdr())
    assert r.status_code == 503
    d = r.json()["detail"]
    assert d["status"] == "verification_temporarily_unavailable"
    assert d["action_required"] is False
    assert "invalid" not in d["message"].lower()
    assert "saved" in d["message"].lower()


#: Provider detail that must never reach a customer. The SID patterns are
#: anchored on a word boundary and require the real 32-hex shape -- an earlier
#: draft matched "AD" plus any six characters, which fires on the word "address"
#: and would have made every one of these assertions pass for the wrong reason.
LEAKS = re.compile(
    r"ProviderError|\btwilio\b|twilio_code|AddressSid|BundleSid|EndUserSid|"
    r"\b(?:AC|AD|RN|PN|BU|IT)[0-9a-f]{32}\b|\bAC[0-9a-z_]*secret|"
    r"HTTP \d{3}|\btraceback\b|Exception|_sid\b",
    re.I)


def test_the_leak_detector_actually_detects_leaks():
    """A leak test is only worth what its detector catches."""
    for leaky in ("ProviderError: bad request", "twilio_code 21628",
                  "AddressSid AD" + "a" * 32, "HTTP 503 from the provider",
                  "ACqa_secret", "provider_account_sid", "Traceback (most recent"):
        assert LEAKS.search(leaky), leaky
    for clean in ("We could not verify that address.",
                  "Check the street, town and Eircode.",
                  "address_not_accepted", "verification_temporarily_unavailable"):
        assert not LEAKS.search(clean), clean


@pytest.mark.parametrize("break_it", ["address_invalid", "address_outage"])
def test_no_provider_detail_reaches_the_customer(client, break_it):
    c, state = client
    state[break_it] = True
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "X", "city": "Y"}}, headers=hdr())
    assert not LEAKS.search(r.text), r.text


def test_the_requirements_response_carries_no_provider_identifiers(client):
    c, state = client
    r = c.get(f"/regulatory/{TENANT}/verification/requirements", headers=hdr())
    assert r.status_code == 200
    assert "RNqa_secret" not in r.text and "regulation_sid" not in r.text
    assert "requirements_fingerprint" not in r.text
    assert not LEAKS.search(r.text), r.text


def test_the_address_response_never_returns_the_provider_address_sid(client):
    c, state = client
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "20 Thomas Street", "city": "Limerick",
                                 "postal_code": "V94 HT0X"}}, headers=hdr())
    assert r.status_code == 200
    assert "ADqa_secret_sid" not in r.text and "address_sid" not in r.text
    assert "ACqa_secret" not in r.text


def test_a_requirements_outage_is_reported_as_temporary(client):
    c, state = client
    state["requirements_ok"] = False
    r = c.get(f"/regulatory/{TENANT}/verification/requirements", headers=hdr())
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "verification_temporarily_unavailable"
    assert not LEAKS.search(r.text)


def test_a_requirements_outage_does_not_block_review_or_consent(client):
    """The customer can read twelve facts on the screen regardless of whether we
    can reach the provider's form definition just now."""
    c, state = client
    state["requirements_ok"] = False
    snap = _review(c, state)
    assert snap["requirements_context"]["known"] is False
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap["review_token"]}, headers=hdr())
    assert r.status_code == 200


def test_a_review_taken_during_an_outage_cannot_be_redeemed_after_it(client):
    """Empty binds to empty, never to 'anything'."""
    c, state = client
    state["requirements_ok"] = False
    snap = _review(c, state)
    state["requirements_ok"] = True          # the provider comes back
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap["review_token"]}, headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "review_out_of_date"


def test_every_engine_status_a_customer_can_reach_is_mapped():
    """A new engine status must not arrive as an opaque 400 because nobody
    remembered to map it."""
    reachable = [
        engine.MISSING_COUNTRY, engine.INVALID_CUSTOMER_DATA,
        engine.ADDRESS_VALIDATION_FAILED, engine.PROVIDER_UNAVAILABLE,
        engine.REQUIREMENTS_CHANGED, engine.NOT_READY,
        engine.AUTHORIZATION_NOT_RECORDED, engine.AUTHORIZATION_STALE,
        engine.AUTHORIZATION_REVOKED, engine.AUTHORIZATION_WRONG_SCOPE,
        engine.OWNERSHIP_CONFLICT, engine.REGULATORY_IDENTITY_CONFLICT,
        engine.UNSUPPORTED_REQUIREMENT_FIELD, engine.UNSUPPORTED_DOCUMENT_REQUIREMENT,
        review.INVALID, review.EXPIRED, review.STALE, review.SCOPE_MISMATCH,
    ]
    for status in reachable:
        assert cx.is_mapped(status), status
        http, payload = cx.for_status(status)
        assert payload["message"] and not LEAKS.search(payload["message"]), status
        assert isinstance(payload["action_required"], bool)


def test_the_fallback_never_echoes_an_unknown_status(client):
    http, payload = cx.for_status("some_new_internal_status_with_ACdeadbeef")
    assert "ACdeadbeef" not in str(payload)
    assert payload["status"] == "verification_failed"


# ═══ 9. resume ═════════════════════════════════════════════════════════════

def test_state_repopulates_from_canonical_storage(client):
    c, state = client
    st = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr()).json()
    assert st["details"] == {k: DETAILS[k] for k in rv.CUSTOMER_DETAIL_FIELDS}
    assert st["details_complete"] is True
    assert st["addresses"][0]["regulatory_address_id"] == ADDR
    assert st["addresses"][0]["validated"] is True
    assert st["filing_submitted"] is False
    assert "address_sid" not in str(st)


def test_state_names_the_next_step_at_each_stage(client):
    c, state = client
    state["details"] = {}
    assert c.get(f"/regulatory/{TENANT}/verification/state",
                 headers=hdr()).json()["next_step"] == "details"
    state["details"] = dict(DETAILS)
    state["addresses"][0]["validated"] = False
    assert c.get(f"/regulatory/{TENANT}/verification/state",
                 headers=hdr()).json()["next_step"] == "address"
    state["addresses"][0]["validated"] = True
    assert c.get(f"/regulatory/{TENANT}/verification/state",
                 headers=hdr()).json()["next_step"] == "review"


def test_partial_details_merge_rather_than_wipe(client):
    """A one-field correction after a rejection must not become a full retype."""
    c, state = client
    c.post(f"/regulatory/{TENANT}/verification/details",
           json={"business_website": "https://updated.example.ie"}, headers=hdr())
    assert state["details"]["business_name"] == DETAILS["business_name"]
    assert state["details"]["business_website"] == "https://updated.example.ie"


def test_the_country_comes_from_the_confirmed_compliance_country(client):
    """A body-supplied country would validate an address into a country nobody
    confirmed, and the digest would then record it."""
    c, state = client
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "1 Rue", "city": "Paris",
                                 "iso_country": "FR"}}, headers=hdr())
    assert r.status_code == 200
    assert state["addresses"][0]["iso_country"] == "IE"


def test_a_tenant_with_no_confirmed_country_is_sent_back(client):
    c, state = client
    state["tenant"]["business_country_code"] = None
    r = c.get(f"/regulatory/{TENANT}/verification/state", headers=hdr())
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "country_not_confirmed"
    assert r.json()["detail"]["revisit_step"] == "country"


# ═══ 10. the review token itself ═══════════════════════════════════════════

def test_the_review_token_binds_every_scope_field(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "ab" * 32)
    token = review.issue(tenant_id=TENANT, iso_country="IE", end_user_type="business",
                         address_id=ADDR, authorization_fingerprint="a" * 64,
                         requirements_fingerprint="f" * 64)

    def check(**over):
        args = dict(tenant_id=TENANT, iso_country="IE", end_user_type="business",
                    address_id=ADDR, current_authorization_fingerprint="a" * 64,
                    current_requirements_fingerprint="f" * 64)
        args.update(over)
        return review.verify(token, **args)["status"]

    assert check() == review.OK
    assert check(tenant_id=OTHER) == review.SCOPE_MISMATCH
    assert check(iso_country="GB") == review.SCOPE_MISMATCH
    assert check(end_user_type="individual") == review.SCOPE_MISMATCH
    assert check(address_id=ADDR2) == review.SCOPE_MISMATCH
    # Digest changes are STALE, not scope errors: they need a re-read, not a
    # different premises.
    assert check(current_authorization_fingerprint="b" * 64) == review.STALE
    assert check(current_requirements_fingerprint="e" * 64) == review.STALE


def test_a_token_signed_with_another_key_is_invalid(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "ab" * 32)
    token = review.issue(tenant_id=TENANT, iso_country="IE", end_user_type="business",
                         address_id=ADDR, authorization_fingerprint="a" * 64,
                         requirements_fingerprint="f" * 64)
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "cd" * 32)
    out = review.verify(token, tenant_id=TENANT, iso_country="IE",
                        end_user_type="business", address_id=ADDR,
                        current_authorization_fingerprint="a" * 64,
                        current_requirements_fingerprint="f" * 64)
    assert out["status"] == review.INVALID and out["detail"] == "bad_signature"


def test_the_token_never_carries_the_customers_facts(monkeypatch):
    """It is a proof of WHICH facts, not a copy of them. A token in a log or a
    browser history must not be a personal-data disclosure."""
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "ab" * 32)
    import base64, json
    token = review.issue(tenant_id=TENANT, iso_country="IE", end_user_type="business",
                         address_id=ADDR, authorization_fingerprint="a" * 64,
                         requirements_fingerprint="f" * 64)
    body = token.rsplit(".", 1)[0]
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert set(claims) == {"tenant_id", "iso_country", "end_user_type", "address_id",
                           "authorization_fingerprint", "requirements_fingerprint",
                           "expires_at"}
    for value in DETAILS.values():
        assert value not in str(claims)


def test_the_review_secret_is_domain_separated(monkeypatch):
    """Derived from ENCRYPTION_KEY_HEX, never equal to it, so a review signature
    can never be confused with any other use of that secret."""
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", "ab" * 32)
    from services.security import _get_enc_key
    assert review._key() != _get_enc_key()
    assert len(review._key()) == 32


# ═══ 11. the feature flag, and what it does and does not gate ══════════════

def test_public_ireland_signup_stays_closed(monkeypatch):
    """Stage P. The flag gates ENTRY -- the public signup route -- so with it off
    no Irish tenant can be created from outside, and the verification flow has
    nobody to serve."""
    from fastapi.testclient import TestClient as _TC
    from fastapi import FastAPI as _FA
    from routers import onboarding
    from services import onboarding_lifecycle as ob

    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    assert ob.ireland_onboarding_enabled() is False

    app = _FA()
    app.include_router(onboarding.router)
    c = _TC(app, raise_server_exceptions=False)
    r = c.post("/onboarding/provision", json={
        "business_name": "Blocked Ltd", "industry": "realtor", "country": "IE",
        "owner_name": "O", "agent_name": "A", "website_url": ""})
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "country_onboarding_not_open"


def test_the_verification_routes_are_not_gated_by_the_signup_flag():
    """Deliberate, and worth stating. The flag is not a second authorisation
    check: these routes already require tenant ownership, and gating them on it
    too would mean an Irish tenant created for internal QA could not be served
    without weakening the PUBLIC flag -- which is exactly the trade Stage P says
    not to make."""
    referenced = _identifiers(rv)
    assert "ireland_onboarding_enabled" not in referenced


def test_a_successful_authorization_creates_only_an_authorization(client):
    """Stage N, at the unit level: one row, and nothing at the provider."""
    c, state = client
    snap = _review(c, state)
    with patch.object(engine, "prepare_profile", new=AsyncMock()) as prep, \
         patch.object(engine, "resolve_end_user", new=AsyncMock()) as eu, \
         patch.object(engine, "ensure_supporting_document", new=AsyncMock()) as doc, \
         patch.object(engine, "ensure_bundle", new=AsyncMock()) as bundle, \
         patch.object(engine, "ensure_item_assignments", new=AsyncMock()) as items:
        r = c.post(f"/regulatory/{TENANT}/verification/authorize",
                   json={"consent": True, "regulatory_address_id": ADDR,
                         "review_token": snap["review_token"]}, headers=hdr())
    assert r.status_code == 200
    assert len(state["authorizations"]) == 1
    for mock in (prep, eu, doc, bundle, items):
        mock.assert_not_called()


def test_the_onboarding_state_is_not_widened_by_authorizing(client):
    """031's CHECK admits three values. 'ready_for_regulatory_filing' is DERIVED
    from the authorisation rows, which answer per address and can be revoked --
    a tenant-level column could do neither."""
    from services import onboarding_lifecycle as ob
    c, state = client
    snap = _review(c, state)
    r = c.post(f"/regulatory/{TENANT}/verification/authorize",
               json={"consent": True, "regulatory_address_id": ADDR,
                     "review_token": snap["review_token"]}, headers=hdr())
    assert r.json()["next_state"] == "ready_for_regulatory_filing"
    assert state["tenant"]["onboarding_state"] == "regulatory_required"
    assert rv.READY_FOR_REGULATORY_FILING not in ob.STATES


# ═══ 12. what the address step actually sends the engine ═══════════════════
#
# The live Stage T run found this gap and the unit suite did not: the fixture's
# ensure_address accepted anything, while the real engine requires a
# customer_name and refuses the address without one. A fake that is more
# permissive than the thing it stands for hides exactly this class of bug, so
# these assert the CALL, and pin the real engine's requirement alongside it.

def test_the_engine_really_requires_a_customer_name():
    """Pins the requirement the fake cannot express. If ensure_address stops
    requiring it, the test below is testing a field nothing needs."""
    import inspect
    src = inspect.getsource(engine.ensure_address)
    assert 'required = ("customer_name", "street", "city", "iso_country")' in src
    assert '("postal_code",)' in src          # Ireland additionally needs the Eircode


def test_the_address_call_carries_the_registered_business_name(client):
    """Read back from storage, never asked for twice: two fields for one fact
    would let them disagree, and the address would then name a business the
    authorisation digest does not cover."""
    c, state = client
    seen = {}

    async def capture(tenant, *, submitted, tenant_location_id=None, **kw):
        seen.update(submitted)
        row = {**ADDRESS, **submitted, "id": ADDR, "tenant_id": TENANT, "validated": True}
        return {"ok": True, "status": engine.OK, "address": row, "reused": False}

    with patch.object(rv.engine, "ensure_address", new=capture):
        r = c.post(f"/regulatory/{TENANT}/verification/address",
                   json={"address": {"street": "20 Thomas St", "city": "Limerick",
                                     "postal_code": "V94 HT0X"}}, headers=hdr())
    assert r.status_code == 200, r.text
    assert seen["customer_name"] == DETAILS["business_name"]
    assert seen["iso_country"] == "IE"
    # Every field the engine requires for Ireland is present.
    for required in ("customer_name", "street", "city", "iso_country", "postal_code"):
        assert str(seen.get(required) or "").strip(), required


def test_the_customer_cannot_name_the_address_holder(client):
    """A body-supplied customer_name would let the premises be registered to a
    business other than the one whose name is fingerprinted."""
    c, state = client
    seen = {}

    async def capture(tenant, *, submitted, tenant_location_id=None, **kw):
        seen.update(submitted)
        return {"ok": True, "status": engine.OK,
                "address": {**ADDRESS, **submitted, "id": ADDR, "tenant_id": TENANT},
                "reused": False}

    with patch.object(rv.engine, "ensure_address", new=capture):
        c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "X", "city": "Y", "postal_code": "Z",
                                 "customer_name": "Somebody Else Ltd"}}, headers=hdr())
    assert seen["customer_name"] == DETAILS["business_name"]


def test_an_address_before_any_details_is_refused(client):
    """Without a registered name there is nothing to register the premises to."""
    c, state = client
    state["details"] = {}
    r = c.post(f"/regulatory/{TENANT}/verification/address",
               json={"address": {"street": "X", "city": "Y", "postal_code": "Z"}},
               headers=hdr())
    assert r.status_code == 422
    assert r.json()["detail"]["status"] == "business_details_incomplete"
    assert "business_name" in r.json()["detail"]["missing"]
