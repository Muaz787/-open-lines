"""db/locations helpers: correct table, correct op, and tenant-scoping on every
query. Uses the same fake Supabase client as test_db_routing (no DB) that records
the query chain and returns queued results.

Tenant-scoping is the point of these tests. Every one of these helpers is reachable
from a future API surface, so a missing .eq("tenant_id", …) is an IDOR waiting to
happen — the class of bug the tenant-auth work already had to fix once.
"""
import pytest

from db import locations


class FakeResult:
    def __init__(self, data=None):
        self.data = data


class FakeQB:
    """Records every chained call; .execute() pops the next queued result."""
    def __init__(self, results, log):
        self._results = results
        self._log = log

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self._log.append((name, args, kwargs))
            if name == "execute":
                return self._results.pop(0) if self._results else FakeResult([])
            return self
        return method


class FakeClient:
    def __init__(self, results, log):
        self._results = results
        self._log = log

    def table(self, name):
        self._log.append(("table", (name,), {}))
        return FakeQB(self._results, self._log)


@pytest.fixture
def fake(monkeypatch):
    state = {"log": [], "results": []}

    def _install(results):
        state["results"] = list(results)
        monkeypatch.setattr(locations, "get_client",
                            lambda: FakeClient(state["results"], state["log"]))
        return state["log"]
    return _install


def _calls(log, name):
    return [entry for entry in log if entry[0] == name]


def _tables(log):
    return [entry[1][0] for entry in log if entry[0] == "table"]


def _scoped_to(log, tenant_id):
    return any(entry[0] == "eq" and entry[1] == ("tenant_id", tenant_id) for entry in log)


# ── tenant_locations ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_locations_is_tenant_scoped(fake):
    log = fake([FakeResult([{"id": "loc-1"}])])
    out = await locations.list_locations("t-1")
    assert out == [{"id": "loc-1"}]
    assert _tables(log) == ["tenant_locations"]
    assert _scoped_to(log, "t-1")


@pytest.mark.asyncio
async def test_list_locations_active_only_adds_the_filter(fake):
    log = fake([FakeResult([])])
    await locations.list_locations("t-1", active_only=True)
    assert ("eq", ("active", True), {}) in log


@pytest.mark.asyncio
async def test_get_default_location_filters_on_is_default(fake):
    log = fake([FakeResult([{"id": "loc-1"}])])
    out = await locations.get_default_location("t-1")
    assert out == {"id": "loc-1"}
    assert ("eq", ("is_default", True), {}) in log
    assert _scoped_to(log, "t-1")


@pytest.mark.asyncio
async def test_get_default_location_returns_none_when_absent(fake):
    fake([FakeResult([])])
    assert await locations.get_default_location("t-1") is None


@pytest.mark.asyncio
async def test_insert_location_stamps_tenant_and_timestamps(fake):
    log = fake([FakeResult([{"id": "loc-1"}])])
    await locations.insert_location("t-1", {"slug": "main", "name": "Acme"})
    inserted = _calls(log, "insert")[0][1][0]
    assert inserted["tenant_id"] == "t-1"
    assert inserted["slug"] == "main"
    assert inserted["created_at"] and inserted["updated_at"]


@pytest.mark.asyncio
async def test_update_location_is_scoped_by_tenant_and_id(fake):
    log = fake([FakeResult([{"id": "loc-1"}])])
    await locations.update_location("t-1", "loc-1", {"name": "New"})
    assert _scoped_to(log, "t-1")
    assert ("eq", ("id", "loc-1"), {}) in log
    assert _calls(log, "update")[0][1][0]["updated_at"]


# ── location_provider_bindings ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_binding_uses_the_provider_natural_key(fake):
    log = fake([FakeResult([{"id": "b-1"}])])
    out = await locations.get_binding("t-1", "square", "L123")
    assert out == {"id": "b-1"}
    assert _tables(log) == ["location_provider_bindings"]
    assert _scoped_to(log, "t-1")
    assert ("eq", ("provider", "square"), {}) in log
    assert ("eq", ("provider_location_id", "L123"), {}) in log


@pytest.mark.asyncio
async def test_list_bindings_can_filter_by_provider(fake):
    log = fake([FakeResult([])])
    await locations.list_bindings("t-1", provider="google")
    assert ("eq", ("provider", "google"), {}) in log


@pytest.mark.asyncio
async def test_list_bindings_without_provider_returns_all_providers(fake):
    log = fake([FakeResult([])])
    await locations.list_bindings("t-1")
    assert not [e for e in log if e[0] == "eq" and e[1][0] == "provider"]


@pytest.mark.asyncio
async def test_insert_binding_stamps_tenant(fake):
    log = fake([FakeResult([{"id": "b-1"}])])
    await locations.insert_binding("t-1", {"provider": "square", "provider_location_id": "L1"})
    inserted = _calls(log, "insert")[0][1][0]
    assert inserted["tenant_id"] == "t-1"
    assert inserted["provider"] == "square"


@pytest.mark.asyncio
async def test_bindings_table_is_not_square_specific(fake):
    """The table must take any provider. If this ever needs a branch per provider,
    the provider-neutral design has been lost."""
    for provider in ("square", "google", "microsoft", "vagaro"):
        # the fake's log accumulates across installs, so assert on the latest insert
        log = fake([FakeResult([{"id": "b"}])])
        await locations.insert_binding("t-1", {"provider": provider,
                                               "provider_location_id": "X"})
        assert _calls(log, "insert")[-1][1][0]["provider"] == provider


# ── the backfill's tenant read ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_tenant_select_is_narrow_and_holds_no_credentials(fake):
    """A narrow select keeps tokens and auth keys out of the backfill process
    entirely — it cannot leak what it never fetched."""
    log = fake([FakeResult([{"id": "t-1"}])])
    await locations.list_all_tenants_for_backfill()

    columns = _calls(log, "select")[0][1][0]
    for forbidden in ("token", "secret", "key", "password", "*"):
        assert forbidden not in columns, f"backfill select must not include {forbidden}"
    for needed in ("id", "business_name", "square_location_id"):
        assert needed in columns
