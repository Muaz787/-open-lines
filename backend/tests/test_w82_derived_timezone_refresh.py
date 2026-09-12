"""W8.2 — a provider-derived location timezone follows the provider; an override does not.

THE DEFECT
tenant_locations.timezone means "operator override, else the provider value
derived at adoption" (location_adoption.location_payload: "Operator overrides
win over derivation"). sync_square_locations maintained BINDINGS ONLY, so once
adoption captured a value it was frozen. If Square later corrected a location's
timezone, the binding advanced and the location did not — and since scheduling
prefers the location, the stale value won indefinitely.

THE PROOF WE CAN MAKE WITHOUT SCHEMA
There is no timezone_source column, so an override and a stale derivation look
identical. But one case IS provable: if the location's timezone still equals the
provider timezone we last STORED, nothing has overridden it, and it may follow.

TWO THINGS MAKE THAT SAFE
  * ORDERING. The comparison uses the OLD binding value, read from the map
    loaded once before the loop. The location is written BEFORE the binding, so
    neither partial failure strands a stale value.
  * COMPARE-AND-SWAP. The old value goes in the UPDATE's own predicate, so an
    operator editing the timezone between our read and our write makes us LOSE
    rather than clobber.
"""
import ast
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from db import locations as db_loc
from services import location_sync as ls

TOR, VAN, DUB, EDM = "America/Toronto", "America/Vancouver", "Europe/Dublin", "America/Edmonton"
TID, LOC, PID = "t-1", "loc-1", "L1"


def _src(obj) -> str:
    t = ast.parse(inspect.getsource(obj))
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(t)


def prior(*, provider_tz, location_id=LOC, pid=PID):
    return {"id": "b-1", "provider_location_id": pid, "tenant_location_id": location_id,
            "provider_timezone": provider_tz, "provider_status": "ACTIVE"}


async def run_refresh(*, old_provider, new_provider, location_tz, location_id=LOC,
                      cas_fails=False, raises=False):
    """Drive the real _refresh_derived_timezone with a CAS that models the DB."""
    calls = []

    async def cas(tenant_id, loc_id, *, was, now):
        calls.append({"tenant_id": tenant_id, "location_id": loc_id, "was": was, "now": now})
        if raises:
            raise RuntimeError("db down")
        if cas_fails:
            return False
        return location_tz == was          # the real predicate, modelled

    with patch("db.locations.refresh_derived_timezone", new=AsyncMock(side_effect=cas)):
        await ls._refresh_derived_timezone(
            TID, prior(provider_tz=old_provider, location_id=location_id),
            {"provider_timezone": new_provider}, PID)
    return calls


# ═══════════════════════════════════════════════════════════════════════════
# The eight state transitions
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_CASE1_unchanged_provider_timezone_writes_nothing():
    assert await run_refresh(old_provider=TOR, new_provider=TOR, location_tz=TOR) == []


@pytest.mark.asyncio
async def test_CASE2_a_derived_value_FOLLOWS_the_provider():
    calls = await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=TOR)
    assert calls == [{"tenant_id": TID, "location_id": LOC, "was": TOR, "now": VAN}]


@pytest.mark.asyncio
async def test_CASE3_an_explicit_override_is_PRESERVED():
    """The headline safety property. The CAS predicate is the old provider
    value, so a location holding anything else simply does not match."""
    calls = await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=DUB)
    assert calls[0]["was"] == TOR, "the predicate must be the OLD provider value"
    assert calls[0]["now"] == VAN


@pytest.mark.asyncio
async def test_CASE4_a_provider_that_stops_reporting_a_timezone_erases_NOTHING():
    for missing in (None, "", "   "):
        assert await run_refresh(old_provider=TOR, new_provider=missing, location_tz=TOR) == [], \
            f"a missing provider timezone ({missing!r}) attempted a write"


@pytest.mark.asyncio
async def test_CASE5_a_NULL_location_may_be_populated_when_the_provider_first_reports_one():
    calls = await run_refresh(old_provider=None, new_provider=DUB, location_tz=None)
    assert calls == [{"tenant_id": TID, "location_id": LOC, "was": None, "now": DUB}]


@pytest.mark.asyncio
async def test_CASE6_a_value_the_provider_never_supplied_cannot_be_derived():
    """old provider NULL + location set -> that value came from somewhere else.
    The CAS asks for `timezone IS NULL`, so it cannot match."""
    calls = await run_refresh(old_provider=None, new_provider=DUB, location_tz=TOR)
    assert calls[0]["was"] is None
    assert calls[0]["now"] == DUB


@pytest.mark.asyncio
async def test_CASE7_a_repeated_sync_is_idempotent():
    assert await run_refresh(old_provider=VAN, new_provider=VAN, location_tz=VAN) == []


@pytest.mark.asyncio
async def test_CASE8_an_override_set_AFTER_a_derived_update_still_survives():
    """Toronto -> Vancouver propagated; operator then set Europe/Dublin;
    provider later moves Vancouver -> Edmonton. Dublin must survive."""
    calls = await run_refresh(old_provider=VAN, new_provider=EDM, location_tz=DUB)
    assert calls[0]["was"] == VAN and calls[0]["now"] == EDM


# ═══════════════════════════════════════════════════════════════════════════
# Ordering, partial failure, concurrency
# ═══════════════════════════════════════════════════════════════════════════

def test_the_location_is_written_BEFORE_the_binding():
    """The whole partial-failure argument rests on this order."""
    src = _src(ls.sync_square_locations)
    assert src.index("_refresh_derived_timezone") < src.index("update_binding"), \
        "writing the binding first would destroy the derivation evidence"


def test_the_comparison_uses_the_OLD_binding_value():
    src = _src(ls._refresh_derived_timezone)
    assert "prior.get('provider_timezone')" in src.replace('"', "'")
    assert "meta.get('provider_timezone')" in src.replace('"', "'")


def test_the_prior_map_is_loaded_once_before_the_loop():
    """So `prior` genuinely holds the pre-sync value."""
    src = _src(ls.sync_square_locations)
    assert src.index("existing = ") < src.index("for location in")


def test_the_refresh_is_skipped_entirely_on_a_dry_run():
    src = _src(ls.sync_square_locations)
    tail = src[src.index("if not dry_run:"):]
    assert "_refresh_derived_timezone" in tail.split("result['updated']")[0].replace('"', "'")


@pytest.mark.asyncio
async def test_a_CAS_LOSS_is_reported_and_changes_nothing():
    """The operator-race outcome: we lose, the override stands."""
    calls = await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=TOR, cas_fails=True)
    assert len(calls) == 1                       # attempted once, no retry, no fallback write


@pytest.mark.asyncio
async def test_a_DB_failure_does_not_break_the_sync():
    await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=TOR, raises=True)


@pytest.mark.asyncio
async def test_an_unadopted_binding_has_no_location_to_refresh():
    assert await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=TOR,
                             location_id=None) == []


def test_the_CAS_predicate_is_in_the_UPDATE_not_a_read_then_write():
    src = _src(db_loc.refresh_derived_timezone)
    assert ".update(" in src
    assert ".eq('id', location_id)" in src.replace('"', "'")
    assert "len(res.data or []) == 1" in src
    assert "is_('timezone', 'null')" in src.replace('"', "'")
    assert "eq('timezone', was)" in src.replace('"', "'")
    # a read-then-write would look like this, and must not appear
    assert "get_location_by_id" not in src


def test_the_CAS_is_scoped_to_the_tenant():
    src = _src(db_loc.refresh_derived_timezone)
    assert ".eq('tenant_id', tenant_id)" in src.replace('"', "'")


# ═══════════════════════════════════════════════════════════════════════════
# No name inference, and the per-location independence
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_canadian_location_NAMED_Dublin_follows_the_provider_not_its_name():
    calls = await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=TOR)
    assert calls[0]["now"] == VAN, "the name must never enter this decision"
    for src in (_src(ls._refresh_derived_timezone), _src(db_loc.refresh_derived_timezone)):
        for city in ("Dublin", "Cork", "Limerick", "Toronto", "Vancouver"):
            assert city not in src


@pytest.mark.asyncio
async def test_a_synthetic_irish_provider_correction_propagates_when_derived():
    calls = await run_refresh(old_provider=TOR, new_provider=DUB, location_tz=TOR)
    assert calls[0] == {"tenant_id": TID, "location_id": LOC, "was": TOR, "now": DUB}


@pytest.mark.asyncio
async def test_a_synthetic_irish_override_is_preserved_against_a_provider_change():
    calls = await run_refresh(old_provider=TOR, new_provider=VAN, location_tz=DUB)
    assert calls[0]["was"] == TOR


@pytest.mark.asyncio
async def test_a_mixed_timezone_tenant_updates_each_location_independently():
    """Two bindings, two locations, two different transitions. Each CAS names
    its own location id, so one can never cross-update the other."""
    seen = []

    async def cas(tenant_id, loc_id, *, was, now):
        seen.append((loc_id, was, now))
        return True

    with patch("db.locations.refresh_derived_timezone", new=AsyncMock(side_effect=cas)):
        await ls._refresh_derived_timezone(
            TID, prior(provider_tz=TOR, location_id="loc-tor", pid="L-TOR"),
            {"provider_timezone": EDM}, "L-TOR")
        await ls._refresh_derived_timezone(
            TID, prior(provider_tz=VAN, location_id="loc-van", pid="L-VAN"),
            {"provider_timezone": DUB}, "L-VAN")

    assert seen == [("loc-tor", TOR, EDM), ("loc-van", VAN, DUB)]
    assert len({s[0] for s in seen}) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Nothing else moved
# ═══════════════════════════════════════════════════════════════════════════

def test_adoption_semantics_are_unchanged():
    from services import location_adoption as la
    assert la.location_payload("Cork", business_name="D", provider_timezone=DUB,
                               tenant_country="IE", is_default=False)["timezone"] == DUB
    assert la.location_payload("Cork", business_name="D", provider_timezone=TOR,
                               tenant_country="IE", is_default=False,
                               timezone=DUB)["timezone"] == DUB


def test_the_reader_precedence_from_PR_67_is_unchanged():
    from routers import tools
    src = _src(tools._offer_timezone)
    assert "location.get('timezone')" in src.replace('"', "'")
    assert "provider_timezone" in src


def test_sync_still_maintains_bindings_and_now_also_derived_location_timezones():
    src = _src(ls.sync_square_locations)
    assert "update_binding" in src and "insert_binding" in src
    assert "insert_location" not in src, "sync must still never CREATE a location"
    assert "_refresh_derived_timezone" in src


# ═══════════════════════════════════════════════════════════════════════════
# The CAS itself, driven against a fake PostgREST that honours the predicate
# ═══════════════════════════════════════════════════════════════════════════

class _FakeQuery:
    """Models PostgREST filter chaining over one in-memory row."""

    def __init__(self, store, patch_):
        self.store, self.patch, self.filters = store, patch_, []

    def eq(self, col, val):
        self.filters.append(("eq", col, val)); return self

    def is_(self, col, val):
        self.filters.append(("is", col, val)); return self

    def execute(self):
        row = self.store
        for kind, col, val in self.filters:
            actual = row.get(col)
            if kind == "eq" and actual != val:
                return type("R", (), {"data": []})()
            if kind == "is" and val == "null" and actual is not None:
                return type("R", (), {"data": []})()
        row.update(self.patch)
        return type("R", (), {"data": [dict(row)]})()


class _FakeTable:
    def __init__(self, store): self.store = store
    def update(self, patch_): return _FakeQuery(self.store, patch_)


class _FakeClient:
    def __init__(self, store): self.store = store
    def table(self, name): return _FakeTable(self.store)


def _row(tz):
    return {"id": LOC, "tenant_id": TID, "timezone": tz}


@pytest.mark.asyncio
async def test_REAL_cas_advances_a_row_that_still_matches():
    row = _row(TOR)
    with patch("db.locations.get_client", return_value=_FakeClient(row)):
        won = await db_loc.refresh_derived_timezone(TID, LOC, was=TOR, now=VAN)
    assert won is True and row["timezone"] == VAN


@pytest.mark.asyncio
async def test_REAL_cas_REFUSES_a_row_an_operator_changed():
    """The concurrency guarantee, exercised rather than asserted: the predicate
    is the old provider value, so an override simply does not match."""
    row = _row(DUB)
    with patch("db.locations.get_client", return_value=_FakeClient(row)):
        won = await db_loc.refresh_derived_timezone(TID, LOC, was=TOR, now=VAN)
    assert won is False and row["timezone"] == DUB, "an operator override was clobbered"


@pytest.mark.asyncio
async def test_REAL_cas_populates_only_a_genuinely_NULL_row():
    null_row = _row(None)
    with patch("db.locations.get_client", return_value=_FakeClient(null_row)):
        assert await db_loc.refresh_derived_timezone(TID, LOC, was=None, now=DUB) is True
    assert null_row["timezone"] == DUB

    set_row = _row(TOR)
    with patch("db.locations.get_client", return_value=_FakeClient(set_row)):
        assert await db_loc.refresh_derived_timezone(TID, LOC, was=None, now=DUB) is False
    assert set_row["timezone"] == TOR, "a non-NULL value was treated as derivable"


@pytest.mark.asyncio
async def test_REAL_cas_will_not_cross_tenants():
    row = {"id": LOC, "tenant_id": "someone-else", "timezone": TOR}
    with patch("db.locations.get_client", return_value=_FakeClient(row)):
        assert await db_loc.refresh_derived_timezone(TID, LOC, was=TOR, now=VAN) is False
    assert row["timezone"] == TOR


@pytest.mark.asyncio
async def test_REAL_cas_refuses_incomplete_arguments():
    for args in ((None, LOC, TOR, VAN), (TID, None, TOR, VAN), (TID, LOC, TOR, "")):
        assert await db_loc.refresh_derived_timezone(args[0], args[1], was=args[2], now=args[3]) is False
