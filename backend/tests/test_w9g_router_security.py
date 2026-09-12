"""W9G — route-level security: no customer route may name another tenant.

Every tenant-facing route carries {tenant_id} in the path AND a router-level
`require_tenant_owner` dependency, so the path parameter is only honoured after the
bearer token has been verified to belong to that tenant. The webhook is
unauthenticated by nature and is protected by Twilio's signature instead.
"""
import pytest
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from routers import regulatory
from services import regulatory_state as st

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def test_every_tenant_route_is_scoped_to_a_path_tenant_id():
    for route in regulatory.router.routes:
        assert "{tenant_id}" in route.path, route.path


def test_the_router_carries_the_ownership_dependency():
    """One router-level dependency, so no route can forget it."""
    assert len(regulatory.router.dependencies) == 1
    dep = regulatory.router.dependencies[0].dependency
    assert dep.__name__ == "require_tenant_owner"


def test_the_webhook_router_is_separate_and_unauthenticated():
    """It cannot borrow tenant auth -- Twilio has no bearer token. Its protection is
    the signature, checked inside the handler."""
    assert regulatory.webhook_router.dependencies == []
    assert [r.path for r in regulatory.webhook_router.routes] == \
        ["/webhooks/twilio/regulatory"]
    assert not any("{tenant_id}" in r.path for r in regulatory.webhook_router.routes)


def test_no_tenant_route_accepts_a_tenant_id_in_the_body():
    """A body-supplied tenant would bypass the path-scoped ownership check."""
    import inspect
    src = inspect.getsource(regulatory)
    assert 'body or {}).get("tenant_id"' not in src
    assert 'body.get("tenant_id")' not in src


# ── behaviour, with the ownership dependency exercised ─────────────────────

@pytest.fixture
def client(monkeypatch):
    """Mounts the REAL router and overrides only the repository's auth dependency with
    a stand-in enforcing the same contract: the bearer token must belong to the path
    tenant. Using dependency_overrides keeps every other dependency and every route
    exactly as production has them."""
    from services.security import require_tenant_owner

    state = {"profiles": [], "tenant": {"id": TENANT, "business_country_code": None}}

    # Annotated exactly like the real dependency: without this FastAPI treats
    # `request` as a query parameter and every call 422s.
    async def fake_owner(request: Request,
                         authorization: Annotated[str | None, Header()] = None):
        token = (authorization or "").removeprefix("Bearer ").strip()
        tenant_id = request.path_params.get("tenant_id")
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required")
        if token != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")

    app = FastAPI()
    app.include_router(regulatory.router)
    app.dependency_overrides[require_tenant_owner] = fake_owner

    async def list_profiles(tid):
        return [p for p in state["profiles"] if p["tenant_id"] == tid]
    monkeypatch.setattr(regulatory.db_reg, "list_profiles", list_profiles)

    class FakeQB:
        def __init__(self, table): self.table, self.filters = table, {}
        def select(self, *a, **k): return self
        def eq(self, c, v): self.filters[c] = v; return self
        def limit(self, *a, **k): return self
        def execute(self):
            rows = [state["tenant"]] if self.table == "tenants" else []
            for c, v in self.filters.items():
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            class R: data = rows
            return R()
    monkeypatch.setattr(regulatory, "get_client",
                        lambda: type("C", (), {"table": lambda s, n: FakeQB(n)})())
    return TestClient(app, raise_server_exceptions=False), state


def test_a_request_without_a_token_is_401(client):
    c, _ = client
    assert c.get(f"/regulatory/{TENANT}/status").status_code == 401


def test_a_token_for_another_tenant_is_403(client):
    """The path tenant_id is never authority on its own."""
    c, _ = client
    r = c.get(f"/regulatory/{TENANT}/status",
              headers={"Authorization": f"Bearer {OTHER}"})
    assert r.status_code == 403


def test_the_owning_tenant_is_allowed(client):
    c, _ = client
    r = c.get(f"/regulatory/{TENANT}/status",
              headers={"Authorization": f"Bearer {TENANT}"})
    assert r.status_code == 200
    assert r.json()["business_country_code"] is None


def test_the_status_route_never_returns_provider_sids_or_failure_reasons(client):
    """Provider identifiers are operational, and failure_reason can quote submitted
    identity."""
    c, state = client
    state["profiles"].append({
        "id": "p1", "tenant_id": TENANT, "iso_country": "IE", "number_type": "local",
        "state": st.PENDING_REVIEW, "bundle_status": "pending-review",
        "evaluation_status": "compliant", "regulation_sid": "RN1",
        "bundle_sid": "BU_secret", "end_user_sid": "IT_secret",
        "failure_reason": "Ann Byrne at ann@dani.ie is not a director",
        "submitted_at": None, "decided_at": None})
    r = c.get(f"/regulatory/{TENANT}/status",
              headers={"Authorization": f"Bearer {TENANT}"})
    body = r.text
    assert r.status_code == 200
    assert "BU_secret" not in body and "IT_secret" not in body
    assert "ann@dani.ie" not in body and "Ann Byrne" not in body
    assert r.json()["profiles"][0]["has_bundle"] is True


def test_another_tenants_profiles_are_never_listed(client):
    c, state = client
    state["profiles"].append({"id": "p-other", "tenant_id": OTHER,
                              "iso_country": "IE", "number_type": "local",
                              "state": st.PENDING_REVIEW})
    r = c.get(f"/regulatory/{TENANT}/status",
              headers={"Authorization": f"Bearer {TENANT}"})
    assert r.json()["profiles"] == []
