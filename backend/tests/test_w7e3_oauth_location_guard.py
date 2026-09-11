"""W7E.3 — the Square OAuth callback never invents or destroys a default location.

THE DEFECT, which was the worst of the three
routers/square_connect.py began at `location_id = ""`, ignoring whatever the
tenant already had, then did `locations[0]`, then wrote
`"square_location_id": location_id or None` unconditionally. On a RE-connect
that produced two destructive outcomes:

  * list_locations succeeded -> the tenant's existing pointer was silently
    REPLACED by locations[0], i.e. by Square's list order.
  * list_locations FAILED    -> location_id stayed "" and the pointer was
    written as NULL, WIPING it. available_slot_strings falls back to that
    pointer, so one transient Square hiccup during a re-connect could take a
    live single-location tenant's bookings offline.

W7E.1 (catalog sync) and W7E.2 (deposit links) closed the same defect family.
This is the last one.
"""
import ast
import inspect
import itertools
from unittest.mock import AsyncMock, patch

import pytest

from routers import square_connect as sc
from services import location_sync as ls

CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"


def _executable_source(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def loc(lid, *, status="ACTIVE"):
    return {"id": lid, "status": status, "timezone": "Europe/Dublin", "name": lid}


async def run_callback(*, pointer, locations, list_raises=False, merchant="ML66K1YVCD1P0"):
    """Drive the real OAuth callback with every external call stubbed."""
    tenant = {"id": "t-1", "business_name": "DANI", "square_oauth_state": "st8",
              "square_location_id": pointer}
    captured = {}

    async def cap(tid, update):
        captured.update(update)
        return {}

    lst = AsyncMock(side_effect=RuntimeError("square down")) if list_raises \
        else AsyncMock(return_value=locations)

    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant)), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap)), \
         patch("services.square_service.exchange_code",
               new=AsyncMock(return_value={"access_token": "at", "refresh_token": "rt",
                                           "expires_at": "2027-01-01", "merchant_id": merchant})), \
         patch("services.square_service.get_merchant_info",
               new=AsyncMock(return_value={"currency": "EUR", "merchant_id": merchant})), \
         patch("services.square_service.list_locations", new=lst), \
         patch("routers.square_connect.encrypt", side_effect=lambda v: f"enc:{v}"), \
         patch("services.vapi.patch_assistant_tools", new=AsyncMock()), \
         patch("services.square_booking.sync", new=AsyncMock()), \
         patch("asyncio.create_task", side_effect=lambda coro: coro.close()):
        await sc.callback(request=None, code="c", state="t-1:st8")
    return captured


# ═══════════════════════════════════════════════════════════════════════════
# The chooser is the same one W7E.1/W7E.2 use
# ═══════════════════════════════════════════════════════════════════════════

def test_the_W7E1_policy_is_reused_not_reimplemented():
    code = _executable_source(sc)
    assert "location_sync.choose_legacy_default_square_location" in code
    assert "location_sync.usable_square_locations" in code


def test_no_executable_locations_index_zero_survives():
    code = _executable_source(sc)
    assert "locations[0]" not in code, "the OAuth callback still indexes the provider list"
    assert "locs[0]" not in code


def test_the_pointer_no_longer_starts_from_empty():
    """The root of the destructive behaviour: it began at "" and overwrote."""
    code = _executable_source(sc)
    assert "existing_location_id = " in code
    assert "location_id = existing_location_id" in code


def test_chooser_behaviour_matches_the_other_two_gates():
    assert ls.choose_legacy_default_square_location(CORK, [loc(DUBLIN), loc(CORK)]) == CORK
    assert ls.choose_legacy_default_square_location(None, [loc(CORK)]) == CORK
    assert ls.choose_legacy_default_square_location(None, [loc(CORK), loc(DUBLIN)]) is None
    assert ls.choose_legacy_default_square_location(None, []) is None
    assert ls.choose_legacy_default_square_location(None, [loc(CORK), loc(DUBLIN, status="INACTIVE")]) == CORK


# ═══════════════════════════════════════════════════════════════════════════
# The callback end to end
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A_first_connect_single_location_still_populates():
    """Backwards compatibility — the normal onboarding case."""
    got = await run_callback(pointer=None, locations=[loc(CORK)])
    assert got["square_location_id"] == CORK
    assert got["square_merchant_id"] == "ML66K1YVCD1P0"


@pytest.mark.asyncio
async def test_B_first_connect_MULTI_location_invents_nothing():
    got = await run_callback(pointer=None, locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert got["square_location_id"] is None, "a default was invented at OAuth"


@pytest.mark.asyncio
async def test_C_multi_location_first_connect_is_order_independent():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        got = await run_callback(pointer=None, locations=list(order))
        assert got["square_location_id"] is None


@pytest.mark.asyncio
async def test_D_RECONNECT_never_replaces_an_existing_pointer():
    """The silent-replacement half of the defect."""
    got = await run_callback(pointer=CORK, locations=[loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert got["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_D2_reconnect_preserves_the_pointer_in_every_ordering():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        got = await run_callback(pointer=DUBLIN, locations=list(order))
        assert got["square_location_id"] == DUBLIN


@pytest.mark.asyncio
async def test_E_a_provider_failure_NO_LONGER_WIPES_the_pointer():
    """The destructive half. Before this, one transient list_locations failure
    during a re-connect nulled the pointer and took availability offline."""
    got = await run_callback(pointer=CORK, locations=[], list_raises=True)
    assert got["square_location_id"] == CORK, "a transient Square failure wiped the pointer"


@pytest.mark.asyncio
async def test_F_a_provider_failure_on_a_fresh_connect_leaves_it_unset():
    got = await run_callback(pointer=None, locations=[], list_raises=True)
    assert got["square_location_id"] is None


@pytest.mark.asyncio
async def test_G_zero_locations_leaves_it_unset():
    got = await run_callback(pointer=None, locations=[])
    assert got["square_location_id"] is None


@pytest.mark.asyncio
async def test_H_one_active_one_inactive_is_single_location():
    got = await run_callback(pointer=None, locations=[loc(CORK), loc(DUBLIN, status="INACTIVE")])
    assert got["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_I_the_rest_of_the_oauth_update_is_unchanged():
    got = await run_callback(pointer=None, locations=[loc(CORK)])
    assert got["square_access_token"] == "enc:at"
    assert got["square_refresh_token"] == "enc:rt"
    assert got["square_merchant_id"] == "ML66K1YVCD1P0"
    assert got["square_currency"] == "eur"
    assert got["square_oauth_state"] is None


@pytest.mark.asyncio
async def test_J_a_DANI_shaped_merchant_connecting_fresh_gets_no_default():
    """The shape W7F created: three ACTIVE Irish locations."""
    got = await run_callback(pointer=None, locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert got["square_location_id"] is None
    assert "square_location_timezone" not in got, "OAuth should not write a timezone"


# ═══════════════════════════════════════════════════════════════════════════
# Nothing else moved
# ═══════════════════════════════════════════════════════════════════════════

def test_W7E1_and_W7E2_are_unchanged():
    from services import square_booking as sb
    from routers import tools
    assert "locations[0]" not in _executable_source(sb.sync)
    assert "locs[0]" not in _executable_source(tools._create_and_send_deposit)
    assert "choose_legacy_default_square_location" in _executable_source(sb.sync)


def test_booking_catalog_and_payment_webhooks_unchanged():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert "square_booking_reconcile.reconcile_booking_event(" in src
    assert "_w7e.route_catalog_event(event)" in src
    assert '"payment.updated" | "payment.created"' in src


def test_W7T_untouched():
    from db import supabase_transport
    import db.supabase as dbs
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
    assert "supabase_transport.install()" in inspect.getsource(dbs.get_client)


def test_the_whole_repository_is_now_free_of_arbitrary_location_defaults():
    """The closing invariant for the W7E.1 / W7E.2 / W7E.3 family."""
    from services import square_booking as sb, location_sync as lsmod, square_catalog_routing as w7e
    from routers import tools
    for mod in (sb, lsmod, w7e, tools, sc):
        code = _executable_source(mod)
        assert "locations[0]" not in code, f"{mod.__name__} still indexes the provider list"
        assert "locs[0]" not in code, f"{mod.__name__} still indexes the provider list"
