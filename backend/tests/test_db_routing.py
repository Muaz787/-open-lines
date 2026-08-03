"""db/routing helpers: correct table/op/tenant-scoping and idempotent transfer
attempts. Uses a fake Supabase client (no DB) that records the query chain and
returns queued results."""
import pytest

from db import routing


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
        monkeypatch.setattr(routing, "get_client",
                            lambda: FakeClient(state["results"], state["log"]))
        return state["log"]
    return _install


def _tables(log):
    return [a[0] for name, a, k in log if name == "table"]


def _ops(log):
    return [name for name, a, k in log]


@pytest.mark.asyncio
async def test_set_routing_enabled(fake):
    log = fake([FakeResult([{"id": "t1", "routing_enabled": True}])])
    out = await routing.set_routing_enabled("t1", True)
    assert out["routing_enabled"] is True
    assert "tenants" in _tables(log)
    assert ("update", ({"routing_enabled": True},), {}) in [(n, a, k) for n, a, k in log]
    # tenant-scoped
    assert ("eq", ("id", "t1"), {}) in [(n, a, k) for n, a, k in log]


@pytest.mark.asyncio
async def test_create_destination_scopes_tenant(fake):
    log = fake([FakeResult([{"id": "d1"}])])
    out = await routing.create_destination("t1", {"type": "phone", "e164_hash": "h"})
    assert out["id"] == "d1"
    # insert payload carries tenant_id
    inserts = [a[0] for n, a, k in log if n == "insert"]
    assert inserts and inserts[0]["tenant_id"] == "t1" and inserts[0]["type"] == "phone"


@pytest.mark.asyncio
async def test_find_destination_by_hash(fake):
    log = fake([FakeResult([{"id": "d9", "e164_hash": "abc"}])])
    out = await routing.find_destination_by_hash("t1", "abc")
    assert out["id"] == "d9"
    assert ("eq", ("e164_hash", "abc"), {}) in [(n, a, k) for n, a, k in log]
    # empty hash short-circuits without a query
    assert await routing.find_destination_by_hash("t1", "") is None


@pytest.mark.asyncio
async def test_list_rules_ordered_and_scoped(fake):
    log = fake([FakeResult([{"id": "r1", "priority": 1}, {"id": "r2", "priority": 2}])])
    rules = await routing.list_rules("t1", "p1")
    assert [r["id"] for r in rules] == ["r1", "r2"]
    assert ("order", ("priority",), {}) in [(n, a, k) for n, a, k in log]
    assert ("eq", ("profile_id", "p1"), {}) in [(n, a, k) for n, a, k in log]


@pytest.mark.asyncio
async def test_count_rules(fake):
    fake([FakeResult([{"id": "r1"}, {"id": "r2"}, {"id": "r3"}])])
    assert await routing.count_rules("t1", "p1") == 3


@pytest.mark.asyncio
async def test_transfer_attempt_inserts_when_new(fake):
    # 1st execute: existing lookup returns nothing -> insert
    log = fake([FakeResult([]), FakeResult([{"id": "a1"}])])
    out = await routing.record_transfer_attempt(
        {"vapi_call_id": "call_x", "attempt_index": 0, "outcome": "answered"})
    assert out["id"] == "a1"
    assert "insert" in _ops(log)
    assert "update" not in _ops(log)


@pytest.mark.asyncio
async def test_transfer_attempt_updates_when_duplicate(fake):
    # existing lookup returns a row -> update, no insert (idempotent)
    log = fake([FakeResult([{"id": "a1"}]), FakeResult([{"id": "a1", "outcome": "busy"}])])
    out = await routing.record_transfer_attempt(
        {"vapi_call_id": "call_x", "attempt_index": 0, "outcome": "busy"})
    assert out["outcome"] == "busy"
    assert "update" in _ops(log)
    assert "insert" not in _ops(log)


@pytest.mark.asyncio
async def test_create_callback_scopes_tenant(fake):
    log = fake([FakeResult([{"id": "c1", "status": "open"}])])
    out = await routing.create_callback("t1", {"caller_phone": "+1...", "reason": "x"})
    assert out["status"] == "open"
    inserts = [a[0] for n, a, k in log if n == "insert"]
    assert inserts[0]["tenant_id"] == "t1"
