"""W9F.1 — clearing a dangling phone pointer must refuse on every ambiguity.

This mutates production tenant rows, so the interesting tests are the refusals. Each
one reintroduces a single doubt and asserts the cleanup stops and writes nothing.
"""
import pytest

from services import stale_phone_cleanup as cleanup
from services import telephony, vapi

TENANT = "14a639c5-0000-0000-0000-000000000001"
OTHER = "99999999-0000-0000-0000-000000000002"
E164 = "+14374769773"
VID = "vapi-phone-1"
SUB = "ACsub00000000000000000000000000001"


def tenant(**over):
    base = {"id": TENANT, "business_name": "Visado", "twilio_phone_number": E164,
            "twilio_subaccount_sid": SUB, "twilio_auth_token": "tok",
            "vapi_phone_number_id": VID, "is_active": False,
            "subscription_status": "none"}
    base.update(over)
    return base


class FakeResult:
    def __init__(self, data): self.data = data


class FakeQB:
    def __init__(self, table, state):
        self.table, self.state, self.filters, self.patch = table, state, {}, None
    def select(self, *a, **k): return self
    def update(self, patch): self.patch = patch; return self
    def eq(self, col, val): self.filters[col] = val; return self
    def limit(self, *a, **k): return self
    def execute(self):
        if self.patch is not None:
            rows = [r for r in self.state["tenants"]
                    if all(str(r.get(c)) == str(v) for c, v in self.filters.items())]
            for r in rows:
                r.update(self.patch)
            self.state["writes"].append((self.table, dict(self.filters), dict(self.patch)))
            return FakeResult(rows)
        rows = self.state.get(self.table, [])
        for c, v in self.filters.items():
            rows = [r for r in rows if str(r.get(c)) == str(v)]
        return FakeResult(rows)


@pytest.fixture
def world(monkeypatch):
    state = {"tenants": [tenant()], "tenant_phone_numbers": [], "writes": [],
             "listing": telephony.ProviderNumberList(status="success", numbers=()),
             "search": telephony.NumberSearch(status="success", accounts=(), scanned=22),
             "vapi": vapi.PHONE_ABSENT}

    class FakeClient:
        def table(self, name): return FakeQB(name, state)

    async def fake_fetch(sub, tok): return state["listing"]
    async def fake_search(num): return state["search"]
    async def fake_vapi(pid, key=None): return state["vapi"]

    monkeypatch.setattr(cleanup, "get_client", lambda: FakeClient())
    monkeypatch.setattr(cleanup.telephony, "fetch_subaccount_numbers", fake_fetch)
    monkeypatch.setattr(cleanup.telephony, "find_number_across_accounts", fake_search)
    monkeypatch.setattr(cleanup.vapi, "phone_number_state", fake_vapi)
    monkeypatch.setattr(cleanup.vapi, "get_tenant_vapi_key", lambda t: None)
    return state


# ── the eligible case ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_conclusively_stale_tenant_is_eligible(world):
    v = await cleanup.evaluate_tenant(tenant())
    assert v["eligible"] is True
    assert v["reason"] == ""
    assert v["checks"]["provider_query"] == "success"
    assert v["checks"]["provider_numbers_held"] == 0
    assert v["checks"]["vapi_state"] == vapi.PHONE_ABSENT


@pytest.mark.asyncio
async def test_dry_run_is_the_default_and_writes_nothing(world):
    r = await cleanup.clear_stale_pointers(tenant())
    assert r["dry_run"] is True and r["action"] == "would_clear"
    assert r["rows_changed"] == 0
    assert world["writes"] == []
    assert world["tenants"][0]["twilio_phone_number"] == E164


@pytest.mark.asyncio
async def test_live_mode_clears_exactly_two_columns_on_one_row(world):
    r = await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    assert r["action"] == "cleared"
    assert r["rows_changed"] == 1
    assert len(world["writes"]) == 1
    table, filters, patch = world["writes"][0]
    assert table == "tenants"
    assert set(patch) == {"twilio_phone_number", "vapi_phone_number_id"}, (
        "exactly two columns -- tenants has no updated_at, and a wider patch is a "
        "wider blast radius")
    assert patch["twilio_phone_number"] is None
    assert patch["vapi_phone_number_id"] is None


@pytest.mark.asyncio
async def test_the_write_is_fenced_on_the_values_just_proved_stale(world):
    """A concurrent re-provision between evaluation and write must not be clobbered."""
    await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    _, filters, _ = world["writes"][0]
    assert filters == {"id": TENANT, "twilio_phone_number": E164,
                       "vapi_phone_number_id": VID}


@pytest.mark.asyncio
async def test_a_concurrent_reprovision_changes_zero_rows(world):
    """The fence fires: the row no longer matches, so nothing is written and the
    caller is told it changed zero rows rather than one."""
    world["tenants"][0]["twilio_phone_number"] = "+14160000000"
    r = await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    assert r["rows_changed"] == 0
    assert r["action"] == "unexpected_row_count"
    assert world["tenants"][0]["twilio_phone_number"] == "+14160000000"


@pytest.mark.asyncio
async def test_nothing_else_on_the_tenant_is_touched(world):
    before = dict(world["tenants"][0])
    await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    after = world["tenants"][0]
    for field in ("twilio_subaccount_sid", "twilio_auth_token", "is_active",
                  "subscription_status", "business_name", "id"):
        assert after[field] == before[field], f"{field} was modified"
    assert "number_released_at" not in world["writes"][0][2]
    assert "twilio_subaccount_sid" not in world["writes"][0][2]


@pytest.mark.asyncio
async def test_no_provider_mutation_is_ever_attempted(world, monkeypatch):
    """No Twilio release, no Vapi delete. There is nothing left to release."""
    called = []
    for name in ("release_number", "close_subaccount"):
        monkeypatch.setattr(cleanup.telephony, name,
                            lambda *a, **k: called.append(name), raising=False)
    monkeypatch.setattr(cleanup.vapi, "delete_phone_number",
                        lambda *a, **k: called.append("delete_phone_number"),
                        raising=False)
    await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    assert called == []


# ── every refusal ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refuses_when_there_is_no_scalar_to_clear(world):
    v = await cleanup.evaluate_tenant(tenant(twilio_phone_number=None))
    assert (v["eligible"], v["reason"]) == (False, cleanup.NO_SCALAR)


@pytest.mark.asyncio
async def test_refuses_without_twilio_credentials(world):
    for over in ({"twilio_subaccount_sid": ""}, {"twilio_auth_token": ""}):
        v = await cleanup.evaluate_tenant(tenant(**over))
        assert (v["eligible"], v["reason"]) == (False, cleanup.MISSING_CREDS)


@pytest.mark.asyncio
async def test_refuses_when_the_provider_query_FAILED(world):
    """"We could not ask" is never "it is gone"."""
    world["listing"] = telephony.ProviderNumberList(status="error",
                                                    error_detail="http=500")
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.PROVIDER_UNAVAILABLE)


@pytest.mark.asyncio
async def test_refuses_when_a_provider_number_suddenly_exists(world):
    world["listing"] = telephony.ProviderNumberList(
        status="success", numbers=({"sid": "PN1", "phone_number": E164,
                                    "account_sid": SUB},))
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.PROVIDER_OWNS_NUMBERS)


@pytest.mark.asyncio
async def test_refuses_when_the_org_sweep_was_incomplete(world):
    """A partial sweep cannot prove absence."""
    world["search"] = telephony.NumberSearch(status="success", accounts=(),
                                             scanned=22, unreadable=1)
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.ORG_SEARCH_INCOMPLETE)
    world["search"] = telephony.NumberSearch(status="error", error_detail="boom")
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.ORG_SEARCH_INCOMPLETE)


@pytest.mark.asyncio
async def test_refuses_when_the_number_turns_up_somewhere_in_the_org(world):
    world["search"] = telephony.NumberSearch(status="success", accounts=("ACelse",),
                                             scanned=22)
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.NUMBER_FOUND_IN_ORG)


@pytest.mark.asyncio
async def test_refuses_when_a_canonical_row_exists_for_the_tenant(world):
    world["tenant_phone_numbers"] = [{"id": "r1", "tenant_id": TENANT, "e164": "+1416"}]
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.CANONICAL_ROW_EXISTS)


@pytest.mark.asyncio
async def test_refuses_when_a_canonical_row_claims_that_e164(world):
    world["tenant_phone_numbers"] = [{"id": "r1", "tenant_id": OTHER, "e164": E164}]
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.CANONICAL_CLAIMS_E164)


@pytest.mark.asyncio
async def test_refuses_when_another_tenant_scalar_claims_that_e164(world):
    world["tenants"].append({"id": OTHER, "twilio_phone_number": E164})
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.OTHER_TENANT_CLAIMS)


@pytest.mark.asyncio
async def test_refuses_when_the_vapi_resource_still_EXISTS(world):
    """Removing our only pointer to a live resource would orphan it."""
    world["vapi"] = vapi.PHONE_EXISTS
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.VAPI_RESOURCE_EXISTS)


@pytest.mark.asyncio
async def test_refuses_when_the_vapi_state_is_UNKNOWN(world):
    world["vapi"] = vapi.PHONE_UNKNOWN
    v = await cleanup.evaluate_tenant(tenant())
    assert (v["eligible"], v["reason"]) == (False, cleanup.VAPI_STATE_UNKNOWN)


@pytest.mark.asyncio
async def test_a_tenant_with_no_vapi_pointer_is_still_eligible(world):
    v = await cleanup.evaluate_tenant(tenant(vapi_phone_number_id=None))
    assert v["eligible"] is True
    assert v["checks"]["vapi_state"] == "no_pointer"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate,reason", [
    ({"listing": telephony.ProviderNumberList(status="error", error_detail="x")},
     "provider_numbers_unavailable"),
    ({"search": telephony.NumberSearch(status="success", accounts=("AC1",), scanned=2)},
     "number_found_in_organisation"),
    ({"vapi": vapi.PHONE_EXISTS}, "vapi_resource_exists"),
])
async def test_no_refusal_state_ever_writes_even_in_live_mode(world, mutate, reason):
    world.update(mutate)
    r = await cleanup.clear_stale_pointers(tenant(), dry_run=False)
    assert r["reason"] == reason
    assert r["rows_changed"] == 0
    assert world["writes"] == []
    assert world["tenants"][0]["twilio_phone_number"] == E164


@pytest.mark.asyncio
async def test_the_masked_number_is_reported_not_the_full_one(world):
    v = await cleanup.evaluate_tenant(tenant())
    assert v["number"] != E164 and "…" in v["number"]


# ── the Vapi probe's own three states ──────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [
    (404, vapi.PHONE_ABSENT), (200, vapi.PHONE_EXISTS),
    (401, vapi.PHONE_UNKNOWN), (403, vapi.PHONE_UNKNOWN),
    (500, vapi.PHONE_UNKNOWN), (429, vapi.PHONE_UNKNOWN),
])
async def test_vapi_probe_maps_status_codes_conservatively(monkeypatch, code, expected):
    """Only a 404 proves absence. A 401 means our credentials are wrong, not that the
    resource vanished."""
    class _Res:
        status_code = code
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Res()
    monkeypatch.setattr(vapi.httpx, "AsyncClient", lambda *a, **k: _Client())
    assert await vapi.phone_number_state("pid") == expected


@pytest.mark.asyncio
async def test_vapi_probe_returns_unknown_on_transport_failure(monkeypatch):
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("dns")
    monkeypatch.setattr(vapi.httpx, "AsyncClient", lambda *a, **k: _Client())
    assert await vapi.phone_number_state("pid") == vapi.PHONE_UNKNOWN


@pytest.mark.asyncio
async def test_vapi_probe_with_no_id_is_unknown_not_absent():
    assert await vapi.phone_number_state("") == vapi.PHONE_UNKNOWN
    assert await vapi.phone_number_state(None) == vapi.PHONE_UNKNOWN
