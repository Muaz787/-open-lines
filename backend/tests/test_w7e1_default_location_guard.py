"""W7E.1 — a multi-location tenant never gets an invented default location.

THE HAZARD
`square_booking.sync()` settled the legacy pointer with
`location_id or locations[0]`, and the timezone with `locations[0].timezone`.
For a single-location merchant that is a fair compatibility default: there is
one answer, and list order cannot matter. For a MULTI-LOCATION tenant it is a
guess — Square's list order is not a business rule.

It became live the moment W7E made catalog events actually reach a
multi-location tenant. DANI has Cork, Dublin and Limerick and deliberately has
NO default: its topology lives in tenant_locations + location_provider_bindings,
and resolve_active_location() refuses to guess a city for a caller. Without this
guard the first catalog webhook would have stamped whichever city Square
happened to return first, and location_sync keys default-binding drift detection
off that pointer.

WHAT THIS DOES NOT CHANGE
Single-location compatibility, which several live tenants depend on. A tenant
with one usable location still gets it, and an existing pointer is never
rewritten because a webhook fired.
"""
import ast
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import location_sync as ls
from services import square_booking as sb

CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"
choose = ls.choose_legacy_default_square_location


def loc(lid, *, status="ACTIVE", tz="Europe/Dublin", name=None):
    return {"id": lid, "status": status, "timezone": tz, "name": name or lid}


def _executable_source(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# ═══════════════════════════════════════════════════════════════════════════
# The chooser, in isolation — A through H
# ═══════════════════════════════════════════════════════════════════════════

def test_A_existing_pointer_plus_one_location_is_preserved():
    assert choose(CORK, [loc(CORK)]) == CORK


def test_B_existing_pointer_plus_many_locations_is_preserved():
    """A tenant that already resolved this question does not get it re-decided
    because a catalog webhook fired."""
    assert choose(CORK, [loc(DUBLIN), loc(CORK), loc(LIMERICK)]) == CORK
    # even when the stored pointer is not in the provider list any more
    assert choose("L-GONE", [loc(CORK), loc(DUBLIN)]) == "L-GONE"


def test_C_null_plus_exactly_one_usable_location_is_populated():
    assert choose(None, [loc(CORK)]) == CORK
    assert choose("", [loc(CORK)]) == CORK
    assert choose("   ", [loc(CORK)]) == CORK


def test_D_null_plus_three_usable_locations_stays_null():
    assert choose(None, [loc(CORK), loc(DUBLIN), loc(LIMERICK)]) is None


def test_E_F_provider_ORDER_cannot_change_the_answer():
    """The defect in one property: list order is not a business rule."""
    import itertools
    answers = {choose(None, list(order))
               for order in itertools.permutations([loc(CORK), loc(DUBLIN)])}
    assert answers == {None}, f"order changed the answer: {answers}"

    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    assert {choose(None, list(o)) for o in itertools.permutations(three)} == {None}

    # and with exactly one usable, every order must give the SAME id
    mixed = [loc(CORK), loc(DUBLIN, status="INACTIVE"), loc(LIMERICK, status="INACTIVE")]
    assert {choose(None, list(o)) for o in itertools.permutations(mixed)} == {CORK}


def test_G_null_plus_zero_locations_stays_null():
    assert choose(None, []) is None
    assert choose(None, None) is None


def test_H_inactive_locations_are_not_usable():
    """Square reports INACTIVE for a closed location. One open + one closed is
    a single-location business, not an ambiguous one."""
    assert choose(None, [loc(CORK), loc(DUBLIN, status="INACTIVE")]) == CORK
    assert choose(None, [loc(CORK, status="INACTIVE")]) is None
    assert choose(None, [loc(CORK, status="inactive")]) is None, "status compare must be case-insensitive"
    assert [x["id"] for x in ls.usable_square_locations(
        [loc(CORK), loc(DUBLIN, status="INACTIVE"), loc(LIMERICK)])] == [CORK, LIMERICK]


def test_H2_an_unrecognised_status_counts_as_usable():
    """Asymmetric on purpose. Requiring status == "ACTIVE" exactly would make a
    location whose status Square stopped sending read as zero-usable, and a
    legacy single-location tenant would LOSE its pointer and start failing with
    "No Square location found". Excluding only what is explicitly closed can
    only ever push a tenant toward "ambiguous", where we decline to choose."""
    assert choose(None, [loc(CORK, status=None)]) == CORK
    assert choose(None, [loc(CORK, status="")]) == CORK
    assert choose(None, [loc(CORK, status="SOMETHING_NEW")]) == CORK
    assert choose(None, [loc(CORK, status=None), loc(DUBLIN)]) is None


def test_a_location_without_an_id_is_not_usable():
    assert choose(None, [{"status": "ACTIVE"}, loc(CORK)]) == CORK
    assert choose(None, [{"id": "  ", "status": "ACTIVE"}]) is None


def test_the_chooser_is_pure():
    locations = [loc(CORK), loc(DUBLIN)]
    snapshot = [dict(x) for x in locations]
    choose(None, locations)
    assert locations == snapshot


# ═══════════════════════════════════════════════════════════════════════════
# sync() end to end — I, J, L, M
# ═══════════════════════════════════════════════════════════════════════════

def _sync_env(tenant, locations):
    """Run sync() with the provider stubbed, capturing the tenant update."""
    captured = {}

    async def cap(tid, patch_):
        captured.update(patch_)
        return {}

    return captured, [
        patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant)),
        patch("services.square_booking.get_access_token", new=AsyncMock(return_value="tok")),
        patch("services.square_service.list_locations", new=AsyncMock(return_value=locations)),
        patch("services.square_booking.retrieve_booking_profile",
              new=AsyncMock(return_value={"booking_enabled": True})),
        patch("services.square_booking.list_services", new=AsyncMock(return_value=[{"s": 1}])),
        patch("services.square_booking.list_team_members", new=AsyncMock(return_value=[{"t": 1}])),
        patch("db.supabase.replace_square_services", new=AsyncMock()),
        patch("db.supabase.replace_square_staff", new=AsyncMock()),
        patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap)),
        patch("services.location_sync.sync_square_locations", new=AsyncMock(return_value={})),
    ]


async def _run_sync(tenant, locations):
    captured, patches = _sync_env(tenant, locations)
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = await sb.sync(tenant["id"])
    return captured, result


@pytest.mark.asyncio
async def test_I_DANI_shaped_tenant_keeps_square_location_id_NULL():
    """The production case this gate exists for."""
    dani = {"id": "t-dani", "square_location_id": None, "square_location_timezone": None,
            "square_access_token": "enc", "square_appointments_enabled": True}
    captured, result = await _run_sync(dani, [loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert captured["square_location_id"] is None, "a default location was invented"
    assert captured["square_location_timezone"] is None, "a timezone was inherited from a location we declined to choose"
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_I2_DANI_stays_NULL_whatever_order_square_returns():
    import itertools
    three = [loc(CORK, tz="Europe/Dublin"), loc(DUBLIN, tz="Europe/Dublin"),
             loc(LIMERICK, tz="Europe/Dublin")]
    for order in itertools.permutations(three):
        dani = {"id": "t-dani", "square_location_id": None, "square_location_timezone": None,
                "square_access_token": "enc", "square_appointments_enabled": True}
        captured, _ = await _run_sync(dani, list(order))
        assert captured["square_location_id"] is None


@pytest.mark.asyncio
async def test_L_DANI_catalog_caches_STILL_sync_despite_a_null_pointer():
    """Declining to choose a default must not stop the catalog refresh, which is
    the entire reason the webhook fired."""
    dani = {"id": "t-dani", "square_location_id": None, "square_location_timezone": None,
            "square_access_token": "enc", "square_appointments_enabled": True}
    captured, patches = _sync_env(dani, [loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    import contextlib
    with contextlib.ExitStack() as stack:
        ps = [stack.enter_context(p) for p in patches]
        result = await sb.sync("t-dani")
        services_call, staff_call = ps[6], ps[7]
    assert services_call.await_count == 1 and staff_call.await_count == 1
    assert services_call.await_args.args[0] == "t-dani"
    assert staff_call.await_args.args[0] == "t-dani"
    assert result["ok"] is True and result["services"] == [{"s": 1}]
    assert captured["square_appointments_bookable"] is True
    assert captured["square_booking_synced_at"]


@pytest.mark.asyncio
async def test_J_legacy_single_location_tenant_keeps_working():
    """Shahid-shaped: one location, pointer already set. Nothing changes."""
    shahid = {"id": "t-shahid", "square_location_id": CORK,
              "square_location_timezone": "America/Toronto",
              "square_access_token": "enc", "square_appointments_enabled": False}
    captured, _ = await _run_sync(shahid, [loc(CORK, tz="America/Toronto")])
    assert captured["square_location_id"] == CORK
    assert captured["square_location_timezone"] == "America/Toronto"


@pytest.mark.asyncio
async def test_J2_a_fresh_single_location_tenant_still_gets_its_pointer():
    """Backwards compatibility: NULL + one usable location still populates."""
    fresh = {"id": "t-fresh", "square_location_id": None, "square_location_timezone": None,
             "square_access_token": "enc", "square_appointments_enabled": True}
    captured, _ = await _run_sync(fresh, [loc(CORK, tz="Europe/Dublin")])
    assert captured["square_location_id"] == CORK
    assert captured["square_location_timezone"] == "Europe/Dublin"


@pytest.mark.asyncio
async def test_an_existing_pointer_is_never_rewritten_by_a_sync():
    """Even when the tenant has since become multi-location."""
    t = {"id": "t-1", "square_location_id": CORK, "square_location_timezone": "Europe/Dublin",
         "square_access_token": "enc", "square_appointments_enabled": True}
    captured, _ = await _run_sync(t, [loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert captured["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_M_location_sync_still_runs_with_every_location():
    """The multi-location tables stay the source of truth, and they are still
    fed the FULL provider list — the guard only affects the legacy pointer."""
    dani = {"id": "t-dani", "square_location_id": None, "square_location_timezone": None,
            "square_access_token": "enc", "square_appointments_enabled": True}
    locations = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    _, patches = _sync_env(dani, locations)
    import contextlib
    with contextlib.ExitStack() as stack:
        ps = [stack.enter_context(p) for p in patches]
        await sb.sync("t-dani")
        loc_sync = ps[9]
    assert loc_sync.await_count == 1
    assert loc_sync.await_args.args[1] == locations, "location_sync lost locations"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5 — static invariants
# ═══════════════════════════════════════════════════════════════════════════

def test_1_2_no_locations_index_zero_survives_in_the_sync_pointer_path():
    code = _executable_source(sb.sync)
    assert "locations[0]" not in code, "sync() still indexes the provider list"
    assert "choose_legacy_default_square_location" in code


def test_3_an_existing_pointer_is_structurally_preserved():
    code = _executable_source(ls.choose_legacy_default_square_location)
    assert "if current:" in code and "return current" in code


def test_4_single_location_compatibility_is_explicit():
    code = _executable_source(ls.choose_legacy_default_square_location)
    assert "len(usable) == 1" in code


def test_5_the_chooser_never_indexes_an_ambiguous_list():
    code = _executable_source(ls.choose_legacy_default_square_location)
    # the ONLY subscript permitted is the single-element case, guarded by len==1
    guarded = code.split("len(usable) == 1")[1].split("return None")[0]
    assert "usable[0]" in guarded
    assert code.count("[0]") == 1, "more than one positional access exists"


def test_6_7_multi_location_topology_still_lives_in_the_location_tables():
    code = _executable_source(sb.sync)
    assert "location_sync.sync_square_locations" in code or "sync_square_locations" in code
    import db.locations as db_loc
    assert hasattr(db_loc, "list_bindings")


def test_8_booking_routing_does_not_depend_on_the_global_pointer_for_a_resolved_location():
    """For DANI the pointer is unreachable: a caller names a location, W4
    resolves it to a provider id, and THAT is what Square is asked about. The
    tenant pointer is only the legacy fallback when nothing was resolved — which
    is exactly the single-location case the guard still serves."""
    from services import square_booking
    code = _executable_source(square_booking.available_slot_strings)
    assert "provider_location_id" in code
    expected = ("location_id = (provider_location_id or '').strip() "
                "or (tenant.get('square_location_id') or '')")
    assert expected in code, "the pointer is no longer a strict fallback"

    from services import call_location
    assert "square_location_id" not in _executable_source(call_location.resolve_active_location),         "location resolution must never consult the global pointer"


def test_9_W7E_all_candidate_routing_is_unchanged():
    from services import square_catalog_routing as w7e
    code = _executable_source(w7e)
    assert "list_tenants_by_square_merchant_id" in code
    assert ".limit(1)" not in code
    assert "get_tenant_by_square_merchant_id" not in code


def test_10_W7T_transport_untouched():
    from db import supabase_transport
    import db.supabase as dbs
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
    assert "supabase_transport.install()" in inspect.getsource(dbs.get_client)


def test_N_booking_routing_behaviour_unchanged():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert "square_booking_reconcile.reconcile_booking_event(" in src
    assert "resolution=_resolution" in src


def test_O_payment_and_refund_behaviour_unchanged():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert '"payment.updated" | "payment.created"' in src
    assert "_handle_square_payment_completed(event)" in src


def test_K_W7E_multi_tenant_fan_out_still_works():
    """The guard lives below routing and must not have disturbed it."""
    from services import square_catalog_routing as w7e
    code = _executable_source(w7e)
    assert "for tenant in candidates" in code
    assert "sorted(candidates" in code
