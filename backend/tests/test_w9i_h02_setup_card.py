"""W9I-H.0.2 — one Stripe Customer per signup, and never a second.

THE CORRECTION THIS SUITE ENFORCES
I previously claimed that if reconciliation found nothing, the next attempt could
safely retry. It cannot. ABSENCE OF POSITIVE RECONCILIATION IS NOT PROOF THAT
CUSTOMER.CREATE FAILED -- a search returns zero because the object is absent, OR
because the index lags, OR because the query could not run, and nothing here can
tell those apart.

So the rule is asymmetric: a POSITIVE identification attaches a Customer;
everything else -- zero results, an error, a rate limit, an outage -- produces a
state a human resolves. The tests are grouped around that asymmetry.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db import payment_sessions as sessions
from routers import onboarding
from services import country_access, payment_customer as pc
from tests.module_identifiers import identifiers

KEY = "e1f0b077-852f-43f1-b4fe-45c0aae97787"
KEY_B = "a2c3d4e5-6789-4abc-8def-0123456789ab"
CUS = "cus_Canonical123"
OTHER_CUS = "cus_Different456"


def _session(**over):
    return {"onboarding_key": KEY, "iso_country": "IE", "stripe_customer_id": None,
            "provider_attempt_at": None, "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00", **over}


class _Store:
    """The four states, as a tiny in-memory table honouring each fence."""

    def __init__(self, rows=None):
        self.rows = {r["onboarding_key"]: dict(r) for r in (rows or [])}
        self.creates = []

    async def get(self, key):
        r = self.rows.get(key)
        return dict(r) if r else None

    async def claim(self, *, onboarding_key, iso_country):
        if onboarding_key in self.rows:
            return False
        self.rows[onboarding_key] = _session(onboarding_key=onboarding_key,
                                             iso_country=iso_country)
        return True

    async def mark_attempt(self, key):
        r = self.rows.get(key)
        if not r or r["provider_attempt_at"] is not None:
            return False
        r["provider_attempt_at"] = "2026-01-01T00:00:01+00:00"
        return True

    async def attach_customer(self, *, onboarding_key, customer_id):
        r = self.rows.get(onboarding_key)
        if not r or r["stripe_customer_id"] is not None:
            return False
        if r["provider_attempt_at"] is None:
            return False            # migration 035's CHECK, in miniature
        if any(o["stripe_customer_id"] == customer_id
               for k, o in self.rows.items() if k != onboarding_key):
            raise RuntimeError("ops_customer_key")
        r["stripe_customer_id"] = customer_id
        return True

    async def retake_unattempted(self, *, onboarding_key):
        r = self.rows.get(onboarding_key)
        return bool(r and r["provider_attempt_at"] is None
                    and r["stripe_customer_id"] is None)


def _world(store, *, create=None, search=None):
    """Patch the repository and Stripe. `create`/`search` are the provider."""
    stripe = MagicMock()
    if create is not None:
        stripe.Customer.create.side_effect = create
    if search is not None:
        stripe.Customer.search.side_effect = search
    import contextlib
    stack = contextlib.ExitStack()
    for cm in (patch.object(pc.sessions, "get", new=store.get),
               patch.object(pc.sessions, "claim", new=store.claim),
               patch.object(pc.sessions, "mark_attempt", new=store.mark_attempt),
               patch.object(pc.sessions, "attach_customer", new=store.attach_customer),
               # Patched even though the service must never call it: unpatched,
               # conftest's MagicMock would make a lease-style mutation invisible.
               patch.object(pc.sessions, "retake_unattempted",
                            new=store.retake_unattempted),
               patch.object(pc, "_stripe", return_value=stripe)):
        stack.enter_context(cm)
    return stack, stripe


def _made(cus=CUS):
    def _create(**kw):
        return MagicMock(id=cus)
    return _create


# ═══ 1. the happy path, and the repeats that used to duplicate ════════════

@pytest.mark.asyncio
async def test_the_first_call_creates_exactly_one_customer():
    store = _Store()
    ctx, stripe = _world(store, create=_made())
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.OK and out["customer_id"] == CUS
    assert out["created"] is True
    assert stripe.Customer.create.call_count == 1


@pytest.mark.asyncio
async def test_a_repeat_call_reuses_the_same_customer():
    """The frontend re-runs setup-card on mount. Before this, every mount left
    another Customer behind."""
    store = _Store()
    ctx, stripe = _world(store, create=_made())
    with ctx:
        first = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
        second = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
        third = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert first["customer_id"] == second["customer_id"] == third["customer_id"] == CUS
    assert second["created"] is False and third["created"] is False
    assert stripe.Customer.create.call_count == 1


@pytest.mark.asyncio
async def test_an_attached_session_never_calls_stripe_again():
    store = _Store([_session(stripe_customer_id=CUS,
                             provider_attempt_at="2026-01-01T00:00:01+00:00")])
    ctx, stripe = _world(store, create=_made(OTHER_CUS))
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["customer_id"] == CUS
    stripe.Customer.create.assert_not_called()


@pytest.mark.asyncio
async def test_two_signups_get_two_customers():
    store = _Store()
    calls = {"n": 0}

    def create(**kw):
        calls["n"] += 1
        return MagicMock(id=f"cus_{calls['n']}")

    ctx, _ = _world(store, create=create)
    with ctx:
        a = await pc.ensure_customer(onboarding_key=KEY, iso_country="CA")
        b = await pc.ensure_customer(onboarding_key=KEY_B, iso_country="CA")
    assert a["customer_id"] != b["customer_id"]


# ═══ 2. the order: claim, mark, THEN the provider ════════════════════════

@pytest.mark.asyncio
async def test_the_attempt_is_recorded_before_stripe_is_called():
    """The irreversible boundary. If the marker is not durable first, a crash
    leaves a session that looks safe to retry when it is not."""
    store = _Store()
    order = []

    async def mark(key):
        order.append("mark")
        return await _Store.mark_attempt(store, key)

    def create(**kw):
        order.append("create")
        return MagicMock(id=CUS)

    stripe = MagicMock(); stripe.Customer.create.side_effect = create
    with patch.object(pc.sessions, "get", new=store.get), \
         patch.object(pc.sessions, "claim", new=store.claim), \
         patch.object(pc.sessions, "mark_attempt", new=mark), \
         patch.object(pc.sessions, "attach_customer", new=store.attach_customer), \
         patch.object(pc, "_stripe", return_value=stripe):
        await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert order == ["mark", "create"]


@pytest.mark.asyncio
async def test_an_attempt_already_recorded_never_issues_a_fresh_create():
    """Entering in STATE 2 means someone already called Stripe. The only calls
    permitted from here carry the ORIGINAL idempotency key, so Stripe returns
    whatever that key already made rather than minting a second Customer. A
    create wearing the same key is a lookup; a create without one is the bug."""
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00",
                             stripe_customer_id=None)])
    seen = []

    def create(**kw):
        seen.append(kw.get("idempotency_key"))
        return MagicMock(id=CUS)

    ctx, stripe = _world(store, create=create,
                         search=lambda **kw: MagicMock(data=[]))
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert seen == [pc.idempotency_key(KEY)]
    # The replay identified the original object, so it is attached -- not created.
    assert out["status"] == pc.OK and out["created"] is False
    assert store.rows[KEY]["stripe_customer_id"] == CUS


# ═══ 3. THE asymmetry: only a positive identification attaches ═══════════

@pytest.mark.asyncio
async def test_an_unknown_outcome_reconciles_by_idempotency_replay():
    """Inside Stripe's retention the same key returns the ORIGINAL object. A
    lookup wearing a create's clothing -- which is why the key never rotates."""
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
    ctx, stripe = _world(store, create=_made())
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.OK and out["customer_id"] == CUS
    assert out["created"] is False
    assert store.rows[KEY]["stripe_customer_id"] == CUS


@pytest.mark.asyncio
async def test_an_unknown_outcome_reconciles_by_metadata_when_the_key_expired():
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])

    def expired(**kw):
        raise RuntimeError("idempotency key expired")

    ctx, _ = _world(store, create=expired,
                    search=lambda **kw: MagicMock(data=[MagicMock(id=CUS)]))
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.OK and out["customer_id"] == CUS
    assert store.rows[KEY]["stripe_customer_id"] == CUS


@pytest.mark.parametrize("search_result,why", [
    (lambda **kw: MagicMock(data=[]), "zero results"),
    (lambda **kw: (_ for _ in ()).throw(RuntimeError("HTTP 401")), "401"),
    (lambda **kw: (_ for _ in ()).throw(RuntimeError("HTTP 403")), "403"),
    (lambda **kw: (_ for _ in ()).throw(RuntimeError("HTTP 429")), "429"),
    (lambda **kw: (_ for _ in ()).throw(RuntimeError("HTTP 500")), "5xx"),
    (lambda **kw: (_ for _ in ()).throw(TimeoutError("timed out")), "timeout"),
])
@pytest.mark.asyncio
async def test_no_positive_identification_never_creates_another_customer(
        search_result, why):
    """THE property. Zero results and a failed query are indistinguishable from
    here, so neither may authorise a create."""
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
    creates = []

    def create(**kw):
        creates.append(kw)
        raise RuntimeError("idempotency key expired")

    ctx, _ = _world(store, create=create, search=search_result)
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.RECONCILIATION_REQUIRED, why
    assert store.rows[KEY]["stripe_customer_id"] is None, why
    # The only create attempted was the idempotency REPLAY, carrying the same
    # key -- never a fresh creation.
    assert all(c.get("idempotency_key") == pc.idempotency_key(KEY) for c in creates)


@pytest.mark.asyncio
async def test_two_customers_carrying_one_marker_is_an_integrity_incident():
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])

    def expired(**kw):
        raise RuntimeError("expired")

    ctx, _ = _world(store, create=expired,
                    search=lambda **kw: MagicMock(data=[MagicMock(id=CUS),
                                                        MagicMock(id=OTHER_CUS)]))
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.INTEGRITY
    assert store.rows[KEY]["stripe_customer_id"] is None


@pytest.mark.asyncio
async def test_time_passing_does_not_restore_create_authority():
    """A thirty-day-old unresolved attempt is still unresolved."""
    store = _Store([_session(provider_attempt_at="2020-01-01T00:00:00+00:00",
                             created_at="2020-01-01T00:00:00+00:00")])

    def expired(**kw):
        raise RuntimeError("expired")

    ctx, _ = _world(store, create=expired, search=lambda **kw: MagicMock(data=[]))
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.RECONCILIATION_REQUIRED
    assert await store.retake_unattempted(onboarding_key=KEY) is False


@pytest.mark.asyncio
async def test_a_crash_before_the_attempt_is_safely_resumable():
    """The case 035 exists to distinguish: Stripe was provably never called."""
    store = _Store([_session()])          # claimed, no attempt
    assert await store.retake_unattempted(onboarding_key=KEY) is True
    ctx, stripe = _world(store, create=_made())
    with ctx:
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.OK and out["created"] is True
    assert stripe.Customer.create.call_count == 1


# ═══ 4. the idempotency key ══════════════════════════════════════════════

def test_the_key_is_deterministic_and_namespaced():
    assert pc.idempotency_key(KEY) == f"openlines-setup-customer/{KEY}"
    assert pc.idempotency_key(KEY) == pc.idempotency_key(KEY.upper())
    assert pc.idempotency_key(KEY) != pc.idempotency_key(KEY_B)


def test_the_key_is_never_derived_from_the_email():
    """Two signups can share an email, and one signup can change it mid-flow."""
    import inspect
    src = inspect.getsource(pc.idempotency_key)
    assert "email" not in src


def test_the_key_carries_no_secret():
    key = pc.idempotency_key(KEY)
    for leak in ("sk_", "secret", "@"):
        assert leak not in key


@pytest.mark.asyncio
async def test_a_retry_reuses_the_key_rather_than_rotating_it():
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
    seen = []

    def create(**kw):
        seen.append(kw.get("idempotency_key"))
        return MagicMock(id=CUS)

    ctx, _ = _world(store, create=create)
    with ctx:
        await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert seen == [pc.idempotency_key(KEY)]


@pytest.mark.asyncio
async def test_the_customer_carries_the_onboarding_key_as_metadata():
    store = _Store()
    seen = {}

    def create(**kw):
        seen.update(kw)
        return MagicMock(id=CUS)

    ctx, _ = _world(store, create=create)
    with ctx:
        await pc.ensure_customer(onboarding_key=KEY, iso_country="IE",
                                 email="o@x.ie", business_name="Acme", plan="starter")
    assert seen["metadata"][pc.METADATA_KEY] == KEY
    assert seen["email"] == "o@x.ie" and seen["name"] == "Acme"


# ═══ 5. the route ════════════════════════════════════════════════════════

@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(onboarding.router)
    monkeypatch.setattr(onboarding.limiter, "enabled", False, raising=False)
    monkeypatch.delenv("IRELAND_ONBOARDING_ENABLED", raising=False)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    # The card-setup token is encrypted, so the route needs a real key to return.
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", __import__("os").urandom(32).hex())
    return TestClient(app, raise_server_exceptions=False)


def _route(monkeypatch, *, access, ensure=None):
    seen = {"ensure": [], "intents": []}

    async def decide(**kw):
        seen["decide"] = kw
        return access

    async def ensure_customer(**kw):
        seen["ensure"].append(kw)
        return ensure or {"status": pc.OK, "customer_id": CUS, "created": True}

    stripe = MagicMock()

    def si(**kw):
        seen["intents"].append(kw)
        return MagicMock(client_secret="seti_x_secret_y")

    stripe.SetupIntent.create.side_effect = si
    monkeypatch.setattr(onboarding.country_access, "decide", decide)
    monkeypatch.setattr(onboarding.payment_customer, "ensure_customer", ensure_customer)
    monkeypatch.setitem(__import__("sys").modules, "stripe", stripe)
    return seen, stripe


def _body(country="IE", key=KEY, **over):
    return {"plan": "starter", "email": "o@x.ie", "business_name": "Acme",
            "country": country, "onboarding_key": key, **over}


def test_a_closed_country_touches_no_stripe(client, monkeypatch):
    seen, stripe = _route(monkeypatch,
                          access={"access": country_access.DENIED, "reason": "no_grant",
                                  "pilot_grant": False})
    r = client.post("/onboarding/setup-card", json=_body())
    assert r.status_code == 503
    assert r.json()["detail"]["status"] == "country_onboarding_not_open"
    assert seen["ensure"] == []          # no Customer
    assert seen["intents"] == []         # no SetupIntent


def test_a_closed_country_refusal_leaks_nothing(client, monkeypatch):
    _route(monkeypatch, access={"access": country_access.DENIED,
                                "reason": "bound_tenant_missing", "pilot_grant": False})
    r = client.post("/onboarding/setup-card", json=_body())
    assert set(r.json()["detail"]) == {"status", "country", "message"}
    for leak in ("grant", "pilot", "integrity", "expired", "bound"):
        assert leak not in r.text.lower()


def test_an_allowed_pilot_reaches_stripe(client, monkeypatch):
    seen, _ = _route(monkeypatch, access={"access": country_access.ALLOWED,
                                          "reason": "pilot_grant_create",
                                          "pilot_grant": True})
    r = client.post("/onboarding/setup-card", json=_body())
    assert r.status_code == 200
    assert seen["ensure"][0]["onboarding_key"] == KEY
    assert seen["ensure"][0]["iso_country"] == "IE"
    assert seen["intents"][0]["customer"] == CUS


def test_setup_card_never_consumes_the_pilot_grant(client, monkeypatch):
    seen, _ = _route(monkeypatch, access={"access": country_access.ALLOWED,
                                          "reason": "pilot_grant_create",
                                          "pilot_grant": True})
    with patch.object(onboarding.ireland_pilot, "consume", new=AsyncMock()) as consume:
        client.post("/onboarding/setup-card", json=_body())
    consume.assert_not_called()


def test_a_missing_onboarding_key_is_refused_before_stripe(client, monkeypatch):
    seen, _ = _route(monkeypatch, access={"access": country_access.ALLOWED,
                                          "reason": "unregulated_country",
                                          "pilot_grant": False})
    r = client.post("/onboarding/setup-card", json=_body(country="CA", key=""))
    assert r.status_code == 400
    assert seen["ensure"] == [] and seen["intents"] == []


def test_a_malformed_onboarding_key_is_refused(client, monkeypatch):
    _route(monkeypatch, access={"access": country_access.ALLOWED,
                                "reason": "unregulated_country", "pilot_grant": False})
    r = client.post("/onboarding/setup-card", json=_body(country="CA", key="nope"))
    assert r.status_code == 422


@pytest.mark.parametrize("status", [pc.RECONCILIATION_REQUIRED, pc.IN_PROGRESS,
                                    pc.INTEGRITY])
def test_an_unresolved_customer_makes_no_setup_intent(client, monkeypatch, status):
    seen, _ = _route(monkeypatch,
                     access={"access": country_access.ALLOWED,
                             "reason": "unregulated_country", "pilot_grant": False},
                     ensure={"status": status, "customer_id": ""})
    r = client.post("/onboarding/setup-card", json=_body(country="CA"))
    assert r.status_code == 503
    assert seen["intents"] == []
    for leak in ("reconciliation", "integrity", "stripe", "customer"):
        assert leak not in r.text.lower()


def test_a_fresh_setup_intent_always_uses_the_canonical_customer(client, monkeypatch):
    seen, _ = _route(monkeypatch, access={"access": country_access.ALLOWED,
                                          "reason": "unregulated_country",
                                          "pilot_grant": False})
    for _ in range(3):
        client.post("/onboarding/setup-card", json=_body(country="CA"))
    assert len(seen["intents"]) == 3
    assert {i["customer"] for i in seen["intents"]} == {CUS}


def test_the_response_never_exposes_the_customer_id(client, monkeypatch):
    _route(monkeypatch, access={"access": country_access.ALLOWED,
                                "reason": "unregulated_country", "pilot_grant": False})
    r = client.post("/onboarding/setup-card", json=_body(country="CA"))
    assert CUS not in r.text
    assert set(r.json()) == {"client_secret", "card_setup_token"}


def test_country_access_precedes_every_stripe_call():
    import inspect
    src = inspect.getsource(onboarding.setup_card)
    access = src.index("country_access.decide")
    for later in ("ensure_customer", "SetupIntent.create", "STRIPE_SECRET_KEY"):
        assert access < src.index(later), later


def test_setup_card_creates_no_tenant_trial_or_provider_state():
    import inspect
    src = inspect.getsource(onboarding.setup_card)
    for forbidden in ("provision_tenant", "create_trial_subscription", "create_subaccount",
                      "purchase_number", "prepare_profile", "ireland_pilot.consume",
                      "send_welcome_email", "Customer.create"):
        assert forbidden not in src, forbidden


# ═══ 6. the tenant handoff ══════════════════════════════════════════════

def test_the_server_resolves_the_customer_rather_than_trusting_the_token():
    import inspect
    src = inspect.getsource(onboarding.provision)
    assert "payment_customer.resolve_for_tenant" in src
    # ...and the token's value is only allowed to agree with it.
    assert "refusing" in src


@pytest.mark.asyncio
async def test_resolve_for_tenant_reads_only_our_own_record():
    store = _Store([_session(stripe_customer_id=CUS,
                             provider_attempt_at="2026-01-01T00:00:01+00:00")])
    with patch.object(pc.sessions, "get", new=store.get):
        assert await pc.resolve_for_tenant(KEY) == CUS
        assert await pc.resolve_for_tenant(KEY_B) == ""


# ═══ 7. security ════════════════════════════════════════════════════════

def test_no_client_supplied_customer_id_is_accepted():
    """The request model has no field for one, so there is nothing to ignore."""
    assert "stripe_customer_id" not in onboarding.SetupCardRequest.model_fields
    assert "customer_id" not in onboarding.SetupCardRequest.model_fields


def test_the_customer_service_cannot_reach_billing_or_provisioning():
    refs = identifiers(pc)
    for forbidden in ("create_trial_subscription", "provision_tenant", "consume",
                      "purchase_number", "Subscription"):
        assert forbidden not in refs, forbidden


def test_the_repository_offers_no_way_to_unmark_an_attempt():
    """State 2 must have no route back to state 1, and the absence is the
    mechanism -- so it is asserted rather than assumed."""
    refs = identifiers(sessions)
    import inspect
    src = inspect.getsource(sessions)
    assert "clear_attempt" not in refs and "unmark" not in refs
    assert 'provider_attempt_at": None' not in src
    assert '"stripe_customer_id": None' not in src


def test_retake_is_gated_on_proof_not_on_time():
    """Parse, do not grep: the docstring is allowed to discuss age precisely
    because the code must not consult it."""
    import ast, inspect, textwrap
    src = inspect.getsource(sessions.retake_unattempted)
    assert 'is_("provider_attempt_at", "null")' in src
    fn = ast.parse(textwrap.dedent(src)).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]          # drop the docstring, keep the code
    code = ast.unparse(fn)
    for smell in ("timedelta", "STALE", "seconds", "age", "interval", "utcnow"):
        assert smell not in code, smell
    # _now() may appear -- but only as the updated_at bookkeeping VALUE, never
    # inside a filter. A time-valued filter is exactly the lease this refuses.
    filters = {"eq", "neq", "lt", "lte", "gt", "gte", "is_", "in_", "filter"}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in filters):
            assert "_now" not in ast.unparse(node.args and ast.Tuple(
                elts=list(node.args), ctx=ast.Load()) or ast.Tuple(elts=[], ctx=ast.Load()))


# ═══ 8. the reason an operator gets, and the fences underneath ════════════

@pytest.mark.asyncio
async def test_an_unreadable_index_is_reported_differently_from_an_empty_one():
    """Both refuse to create -- that is the invariant. But "we could not look"
    and "we looked and found nothing" are different investigations, and an
    operator who cannot tell them apart cannot triage either."""
    async def _run(search):
        store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
        ctx, _ = _world(store, create=lambda **kw: (_ for _ in ()).throw(
            RuntimeError("expired")), search=search)
        with ctx:
            out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
        assert store.rows[KEY]["stripe_customer_id"] is None
        return out

    empty = await _run(lambda **kw: MagicMock(data=[]))
    broken = await _run(lambda **kw: (_ for _ in ()).throw(RuntimeError("HTTP 500")))
    assert empty["status"] == broken["status"] == pc.RECONCILIATION_REQUIRED
    assert empty["reason"] == "no_match"
    assert broken["reason"] == "search_failed"
    assert empty["reason"] != broken["reason"]


@pytest.mark.asyncio
async def test_a_lease_over_an_unresolved_attempt_would_be_noticed():
    """retake_unattempted is reachable from here, so this asserts it is not
    reached -- rather than leaving the absence to a mock that swallows it."""
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
    calls = []

    async def retake(**kw):
        calls.append(kw)
        return True

    with patch.object(pc.sessions, "get", new=store.get), \
         patch.object(pc.sessions, "claim", new=store.claim), \
         patch.object(pc.sessions, "mark_attempt", new=store.mark_attempt), \
         patch.object(pc.sessions, "attach_customer", new=store.attach_customer), \
         patch.object(pc.sessions, "retake_unattempted", new=retake), \
         patch.object(pc, "_stripe", return_value=MagicMock(
             **{"Customer.create.side_effect": RuntimeError("expired"),
                "Customer.search.side_effect": lambda **kw: MagicMock(data=[])})):
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert calls == []
    assert out["status"] == pc.RECONCILIATION_REQUIRED


class _Query:
    """Records the PostgREST call chain instead of executing it. The fences are
    WHERE clauses, so this is the only place they can be asserted without a
    live database -- stage_v/stage_w prove the same thing against real PG."""

    def __init__(self, rows):
        # `tbl`, not `table`: assigning self.table would shadow the method that
        # records it -- the same trap that bit the W9I-G recorder's `eq`.
        self.rows, self.tbl, self.patch = rows, None, None
        self.eqs, self.nulls, self.not_nulls = {}, [], []
        self._negate = False

    def __call__(self, *a, **k):
        return self

    def table(self, name):
        self.tbl = name; return self

    def update(self, patch):
        self.patch = patch; return self

    def insert(self, row):
        self.patch = row; return self

    def select(self, *a):
        return self

    def limit(self, n):
        return self

    def eq(self, col, val):
        self.eqs[col] = val; return self

    @property
    def not_(self):
        self._negate = True; return self

    def is_(self, col, val):
        (self.not_nulls if self._negate else self.nulls).append((col, val))
        self._negate = False
        return self

    def execute(self):
        return MagicMock(data=self.rows)


def _record(rows=None):
    q = _Query(rows if rows is not None else [{"onboarding_key": KEY}])
    return q, patch.object(sessions, "get_client", return_value=q)


@pytest.mark.asyncio
async def test_mark_attempt_only_writes_when_no_attempt_exists():
    q, ctx = _record()
    with ctx:
        assert await sessions.mark_attempt(KEY) is True
    assert q.tbl == "onboarding_payment_sessions"
    assert q.eqs == {"onboarding_key": KEY}
    assert ("provider_attempt_at", "null") in q.nulls    # THE fence
    assert "provider_attempt_at" in q.patch


@pytest.mark.asyncio
async def test_mark_attempt_reports_a_lost_race_rather_than_raising():
    q, ctx = _record(rows=[])
    with ctx:
        assert await sessions.mark_attempt(KEY) is False


@pytest.mark.asyncio
async def test_attach_requires_an_unbound_session_that_did_attempt():
    q, ctx = _record()
    with ctx:
        assert await sessions.attach_customer(onboarding_key=KEY,
                                              customer_id=CUS) is True
    assert q.eqs == {"onboarding_key": KEY}
    assert ("stripe_customer_id", "null") in q.nulls        # never overwrite
    assert ("provider_attempt_at", "null") in q.not_nulls   # 035's CHECK, echoed
    assert q.patch["stripe_customer_id"] == CUS


@pytest.mark.asyncio
async def test_attach_refuses_a_session_that_is_already_bound():
    q, ctx = _record(rows=[])
    with ctx:
        assert await sessions.attach_customer(onboarding_key=KEY,
                                              customer_id=OTHER_CUS) is False


@pytest.mark.asyncio
async def test_retake_requires_both_columns_null():
    q, ctx = _record()
    with ctx:
        assert await sessions.retake_unattempted(onboarding_key=KEY) is True
    assert ("provider_attempt_at", "null") in q.nulls
    assert ("stripe_customer_id", "null") in q.nulls
    assert q.patch == {"updated_at": q.patch["updated_at"]}   # bookkeeping only


@pytest.mark.asyncio
async def test_get_is_scoped_to_the_one_session():
    q, ctx = _record(rows=[{"onboarding_key": KEY, "stripe_customer_id": CUS}])
    with ctx:
        row = await sessions.get(KEY)
    assert q.eqs == {"onboarding_key": KEY}
    assert row["stripe_customer_id"] == CUS


# ═══ 9. the tenant handoff, behaviourally ════════════════════════════════
# Section 6 asserts the binding EXISTS in the source. These assert it BITES --
# a source assertion survives `if False:` in front of the check it names.

import os  # noqa: E402

from services import subscriptions  # noqa: E402


@pytest.fixture
def _enc(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_HEX", os.urandom(32).hex())


def _prov_body(**over):
    return onboarding.ProvisionRequest(business_name="Acme", industry="beauty",
                                       email="a@b.com", password="12345678", **over)


@pytest.mark.asyncio
async def test_a_token_naming_another_signups_customer_is_refused(_enc):
    """The token is authenticated, so its contents are ours -- but the browser
    holds it, and it names a billing identity. Ours wins."""
    body = _prov_body(card_setup_token=subscriptions.issue_card_setup_token(OTHER_CUS),
                      payment_method_id="pm_x", plan="pro", onboarding_key=KEY)
    with patch.object(onboarding.payment_customer, "resolve_for_tenant",
                      new=AsyncMock(return_value=CUS)), \
         patch("services.provisioning.provision_tenant", new=AsyncMock()) as prov:
        with pytest.raises(Exception) as exc:
            await onboarding.provision(None, body)
    assert getattr(exc.value, "status_code", None) == 400
    prov.assert_not_called()            # refused BEFORE any money is spent


@pytest.mark.asyncio
async def test_the_bound_customer_is_the_one_billed(_enc):
    """Even when the token agrees, the value that reaches billing is the one we
    resolved -- not the one that arrived from the browser."""
    billed = {}

    async def sub(**kw):
        billed.update(kw)
        return {"ok": True, "plan": "pro", "status": "trialing",
                "trial_ends_at": "2026-09-19T00:00:00+00:00"}

    body = _prov_body(card_setup_token=subscriptions.issue_card_setup_token(CUS),
                      payment_method_id="pm_x", plan="pro", onboarding_key=KEY)
    with patch.object(onboarding.payment_customer, "resolve_for_tenant",
                      new=AsyncMock(return_value=CUS)), \
         patch("services.provisioning.provision_tenant",
               new=AsyncMock(return_value={"tenant_id": "t1",
                                           "phone_number": "+14165550100"})), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription", new=sub):
        await onboarding.provision(None, body)
    assert billed["customer_id"] == CUS


@pytest.mark.asyncio
async def test_provision_never_creates_a_customer_of_its_own(_enc):
    """A signup that reaches provisioning already has its Customer, or it has
    none. Minting one here is how the handoff grows a second billing identity."""
    body = _prov_body(card_setup_token=subscriptions.issue_card_setup_token(CUS),
                      payment_method_id="pm_x", plan="pro", onboarding_key=KEY)
    stripe = MagicMock()
    with patch.object(onboarding.payment_customer, "resolve_for_tenant",
                      new=AsyncMock(return_value=CUS)), \
         patch.dict(__import__("sys").modules, {"stripe": stripe}), \
         patch("services.provisioning.provision_tenant",
               new=AsyncMock(return_value={"tenant_id": "t1",
                                           "phone_number": "+14165550100"})), \
         patch("db.supabase.create_auth_user", new=AsyncMock(return_value="u1")), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.subscriptions.create_trial_subscription",
               new=AsyncMock(return_value={"ok": True, "plan": "pro",
                                           "status": "trialing",
                                           "trial_ends_at": "2026-09-19T00:00:00+00:00"})), \
         patch.object(onboarding.payment_customer, "ensure_customer",
                      new=AsyncMock()) as ensure:
        await onboarding.provision(None, body)
    stripe.Customer.create.assert_not_called()
    ensure.assert_not_called()


@pytest.mark.asyncio
async def test_an_unconfigured_provider_never_reports_a_resolved_absence():
    """If we cannot reach Stripe at all, we know less than nothing about the
    Customer -- so OK with an empty id is the one answer that must not come
    back. A caller reading only `status` would take it as settled."""
    store = _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")])
    with patch.object(pc.sessions, "get", new=store.get), \
         patch.object(pc.sessions, "attach_customer", new=store.attach_customer), \
         patch.object(pc, "_stripe",
                      side_effect=RuntimeError("STRIPE_SECRET_KEY is not configured")):
        out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
    assert out["status"] == pc.RECONCILIATION_REQUIRED
    assert out["reason"] == "provider_unconfigured"
    assert store.rows[KEY]["stripe_customer_id"] is None


@pytest.mark.asyncio
async def test_ensure_customer_never_returns_ok_without_a_customer():
    """The contract the route depends on, asserted across every outcome."""
    cases = [
        ("attached", _Store([_session(stripe_customer_id=CUS,
                                      provider_attempt_at="2026-01-01T00:00:01+00:00")]),
         _made(), lambda **kw: MagicMock(data=[])),
        ("fresh", _Store(), _made(), lambda **kw: MagicMock(data=[])),
        ("unresolved", _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")]),
         lambda **kw: (_ for _ in ()).throw(RuntimeError("expired")),
         lambda **kw: MagicMock(data=[])),
        ("ambiguous", _Store([_session(provider_attempt_at="2026-01-01T00:00:01+00:00")]),
         lambda **kw: (_ for _ in ()).throw(RuntimeError("expired")),
         lambda **kw: MagicMock(data=[MagicMock(id=CUS), MagicMock(id=OTHER_CUS)])),
    ]
    for label, store, create, search in cases:
        ctx, _ = _world(store, create=create, search=search)
        with ctx:
            out = await pc.ensure_customer(onboarding_key=KEY, iso_country="IE")
        assert bool(out["customer_id"]) == (out["status"] == pc.OK), label
