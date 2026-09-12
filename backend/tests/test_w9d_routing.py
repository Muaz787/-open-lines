"""W9D — dual-model inbound routing (db.supabase.get_tenant_by_phone).

The behaviour under test is the one that makes a regulated-number migration
survivable: while a tenant holds BOTH a temporary test number and a new permanent
number, the scalar can only name one of them, so the table has to answer first.

Every test here drives the real function with a fake Supabase client, so the
lookup ORDER and the fail-closed branch are exercised, not described.
"""
import pytest

import db.phone_numbers as db_phone
import db.supabase as db
from services import phone_lifecycle as lifecycle

TENANT_A = "aaaaaaaa-0000-0000-0000-000000000001"
TENANT_B = "bbbbbbbb-0000-0000-0000-000000000002"
PERMANENT = "+35316170000"
TEMPORARY = "+447400000001"


class FakeResult:
    def __init__(self, data=None):
        self.data = data


class FakeQB:
    """Filters a fixed table of rows by the .eq()/.in_() calls made against it."""
    def __init__(self, rows, log):
        self._rows = rows
        self._log = log
        self._filters = []

    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, col, val):
        self._log.append(("eq", col, val))
        self._filters.append(lambda r: str(r.get(col, "")) == str(val))
        return self

    def in_(self, col, vals):
        self._log.append(("in", col, tuple(vals)))
        self._filters.append(lambda r: str(r.get(col, "")) in {str(v) for v in vals})
        return self

    def single(self):
        return self

    def execute(self):
        rows = [r for r in self._rows if all(f(r) for f in self._filters)]
        return FakeResult(rows)


@pytest.fixture
def world(monkeypatch):
    """A tiny two-table world: tenants + tenant_phone_numbers."""
    state = {"tenants": [], "phones": [], "log": []}

    class FakeClient:
        def table(self, name):
            state["log"].append(("table", name))
            if name == "tenants":
                return FakeQB(state["tenants"], state["log"])
            if name == "tenant_phone_numbers":
                return FakeQB(state["phones"], state["log"])
            raise AssertionError(f"unexpected table {name}")

    monkeypatch.setattr(db, "get_client", lambda: FakeClient())
    monkeypatch.setattr(db_phone, "get_client", lambda: FakeClient())

    # get_tenant_by_id uses .single(); give it its own client so the scalar path
    # (which uses .limit(1) and expects a list) is unaffected.
    async def fake_by_id(tenant_id):
        for t in state["tenants"]:
            if str(t.get("id")) == str(tenant_id):
                return t
        raise RuntimeError("no rows")
    monkeypatch.setattr(db, "get_tenant_by_id", fake_by_id)
    return state


def _tenant(tid, scalar_number=None, vapi=None):
    return {"id": tid, "business_name": f"T-{tid[:4]}",
            "twilio_phone_number": scalar_number, "vapi_phone_number_id": vapi}


def _phone(tid, e164, status, purpose=lifecycle.PURPOSE_PERMANENT, rid="row"):
    return {"id": rid, "tenant_id": tid, "e164": e164, "purpose": purpose,
            "status": status, "provider": "twilio", "provider_sid": "PN1",
            "provider_account_sid": "AC1"}


# ── 1) the canonical model answers first ───────────────────────────────────

@pytest.mark.asyncio
async def test_active_row_in_the_new_table_resolves(world):
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    world["phones"] = [_phone(TENANT_A, PERMANENT, lifecycle.STATUS_ACTIVE)]
    t = await db.get_tenant_by_phone(PERMANENT)
    assert t and t["id"] == TENANT_A
    assert ("table", "tenant_phone_numbers") in world["log"]


@pytest.mark.asyncio
async def test_retiring_row_still_routes(world):
    """The whole point of a grace period: the old number keeps ringing."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    world["phones"] = [_phone(TENANT_A, TEMPORARY, lifecycle.STATUS_RETIRING,
                              purpose=lifecycle.PURPOSE_TEMPORARY, rid="tmp")]
    t = await db.get_tenant_by_phone(TEMPORARY)
    assert t and t["id"] == TENANT_A


@pytest.mark.asyncio
async def test_a_row_the_table_resolves_but_the_scalar_does_not_still_routes(world):
    """The temporary number after the scalar has been promoted to the permanent
    one. This is the exact 404 the dual model exists to prevent."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]      # scalar = permanent
    world["phones"] = [_phone(TENANT_A, TEMPORARY, lifecycle.STATUS_ACTIVE,
                              purpose=lifecycle.PURPOSE_TEMPORARY, rid="tmp")]
    t = await db.get_tenant_by_phone(TEMPORARY)
    assert t and t["id"] == TENANT_A


# ── non-routable statuses ──────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [lifecycle.STATUS_PROVISIONING,
                                    lifecycle.STATUS_RELEASED,
                                    lifecycle.STATUS_FAILED])
async def test_non_routable_statuses_do_not_route(world, status):
    """provisioning has no webhook configured yet; released and failed are history.
    With no scalar match either, the lookup must find nothing."""
    world["tenants"] = [_tenant(TENANT_A, None)]
    world["phones"] = [_phone(TENANT_A, PERMANENT, status)]
    assert await db.get_tenant_by_phone(PERMANENT) is None


@pytest.mark.asyncio
async def test_the_status_filter_is_pushed_into_the_query(world):
    world["tenants"] = [_tenant(TENANT_A, None)]
    await db.get_tenant_by_phone(PERMANENT)
    assert ("in", "status", lifecycle.ROUTABLE_STATUSES) in world["log"]


# ── 2) legacy scalar fallback ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scalar_fallback_when_the_table_is_empty(world):
    """Every tenant before the backfill. Behaviour must be unchanged."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    world["phones"] = []
    t = await db.get_tenant_by_phone(PERMANENT)
    assert t and t["id"] == TENANT_A


@pytest.mark.asyncio
async def test_vapi_id_fallback_survives(world):
    world["tenants"] = [_tenant(TENANT_A, PERMANENT, vapi="vapi-uuid-1")]
    world["phones"] = []
    t = await db.get_tenant_by_phone("vapi-uuid-1")
    assert t and t["id"] == TENANT_A


@pytest.mark.asyncio
async def test_unknown_number_resolves_to_nothing(world):
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    assert await db.get_tenant_by_phone("+15555550123") is None


@pytest.mark.asyncio
async def test_a_table_failure_falls_back_instead_of_dropping_the_call(world, monkeypatch):
    """If migration 027 is not applied yet, the query raises. Inbound calls must
    keep working on the scalar."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]

    class Boom:
        def table(self, name):
            if name == "tenant_phone_numbers":
                raise RuntimeError('relation "tenant_phone_numbers" does not exist')
            raise AssertionError
    monkeypatch.setattr(db_phone, "get_client", lambda: Boom())
    t = await db.get_tenant_by_phone(PERMANENT)
    assert t and t["id"] == TENANT_A


# ── 3) fail closed on disagreement ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_table_and_scalar_disagreeing_on_the_tenant_fails_closed(world, caplog):
    """Choosing either answer risks handing tenant A's caller to tenant B's
    assistant. Returning nothing is the only safe direction."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT), _tenant(TENANT_B, None)]
    world["phones"] = [_phone(TENANT_B, PERMANENT, lifecycle.STATUS_ACTIVE)]
    with caplog.at_level("ERROR"):
        assert await db.get_tenant_by_phone(PERMANENT) is None
    assert "PHONE IDENTITY CONFLICT" in caplog.text


@pytest.mark.asyncio
async def test_two_tenants_claiming_one_routable_number_fails_closed(world, caplog):
    world["tenants"] = [_tenant(TENANT_A, None), _tenant(TENANT_B, None)]
    world["phones"] = [_phone(TENANT_A, PERMANENT, lifecycle.STATUS_ACTIVE, rid="r1"),
                       _phone(TENANT_B, PERMANENT, lifecycle.STATUS_ACTIVE, rid="r2")]
    with caplog.at_level("ERROR"):
        assert await db.get_tenant_by_phone(PERMANENT) is None
    assert "PHONE IDENTITY CONFLICT" in caplog.text


@pytest.mark.asyncio
async def test_a_dangling_row_does_not_raise_into_the_call_path(world, caplog):
    world["tenants"] = []
    world["phones"] = [_phone(TENANT_A, PERMANENT, lifecycle.STATUS_ACTIVE)]
    with caplog.at_level("ERROR"):
        assert await db.get_tenant_by_phone(PERMANENT) is None
    assert "could not be loaded" in caplog.text


@pytest.mark.asyncio
async def test_two_routable_rows_for_one_tenant_still_routes(world, caplog):
    """A data error, but not an identity ambiguity: the tenant is unambiguous, so a
    caller must not be dropped for it."""
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    world["phones"] = [_phone(TENANT_A, PERMANENT, lifecycle.STATUS_ACTIVE, rid="r1"),
                       _phone(TENANT_A, PERMANENT, lifecycle.STATUS_RETIRING, rid="r2")]
    with caplog.at_level("ERROR"):
        t = await db.get_tenant_by_phone(PERMANENT)
    assert t and t["id"] == TENANT_A


@pytest.mark.asyncio
async def test_blank_input_resolves_to_nothing(world):
    world["tenants"] = [_tenant(TENANT_A, PERMANENT)]
    assert await db.get_tenant_by_phone("") is None
