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



def assert_no_pointer_written(got):
    """W7E.4 turned the callback into an observed-fields-only patch, so "no
    default was invented" is now expressed by the key being ABSENT rather than
    written as None. The database end state is identical — the column was
    already NULL — but omitting is the stronger guarantee: nothing was written
    at all, so the value cannot be clobbered even in principle."""
    assert "square_location_id" not in got or got["square_location_id"] is None, \
        f"a default location was written: {got.get('square_location_id')!r}"


def loc(lid, *, status="ACTIVE"):
    return {"id": lid, "status": status, "timezone": "Europe/Dublin", "name": lid}


async def run_callback(*, pointer, locations, list_raises=False, merchant="ML66K1YVCD1P0",
                       stored_merchant=None, info_merchant=None, info_raises=False,
                       want_redirect=False):
    """Drive the real OAuth callback with every external call stubbed.

    merchant        -> what the TOKEN response carries
    info_merchant   -> what get_merchant_info carries (defaults to `merchant`)
    stored_merchant -> what the tenant already has on file
    """
    tenant = {"id": "t-1", "business_name": "DANI", "square_oauth_state": "st8",
              "square_location_id": pointer, "square_merchant_id": stored_merchant}
    captured = {}

    async def cap(tid, update):
        captured.update(update)
        return {}

    lst = AsyncMock(side_effect=RuntimeError("square down")) if list_raises \
        else AsyncMock(return_value=locations)
    info = AsyncMock(side_effect=RuntimeError("merchant info down")) if info_raises \
        else AsyncMock(return_value={"currency": "EUR",
                                     "merchant_id": (info_merchant if info_merchant is not None
                                                     else merchant)})

    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant)), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap)), \
         patch("services.square_service.exchange_code",
               new=AsyncMock(return_value={"access_token": "at", "refresh_token": "rt",
                                           "expires_at": "2027-01-01", "merchant_id": merchant})), \
         patch("services.square_service.get_merchant_info", new=info), \
         patch("services.square_service.list_locations", new=lst), \
         patch("routers.square_connect.encrypt", side_effect=lambda v: f"enc:{v}"), \
         patch("services.vapi.patch_assistant_tools", new=AsyncMock()), \
         patch("services.square_booking.sync", new=AsyncMock()), \
         patch("asyncio.create_task", side_effect=lambda coro: coro.close()):
        resp = await sc.callback(request=None, code="c", state="t-1:st8")
    if want_redirect:
        return captured, str(getattr(resp, "headers", {}).get("location", ""))
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
    assert_no_pointer_written(got)


@pytest.mark.asyncio
async def test_C_multi_location_first_connect_is_order_independent():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        got = await run_callback(pointer=None, locations=list(order))
        assert_no_pointer_written(got)


@pytest.mark.asyncio
async def test_D_RECONNECT_never_replaces_an_existing_pointer():
    """The silent-replacement half of the defect."""
    got = await run_callback(pointer=CORK, stored_merchant="ML66K1YVCD1P0",
                             locations=[loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert got["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_D2_reconnect_preserves_the_pointer_in_every_ordering():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        got = await run_callback(pointer=DUBLIN, stored_merchant="ML66K1YVCD1P0",
                                 locations=list(order))
        assert got["square_location_id"] == DUBLIN


@pytest.mark.asyncio
async def test_E_a_provider_failure_NO_LONGER_WIPES_the_pointer():
    """The destructive half. Before this, one transient list_locations failure
    during a re-connect nulled the pointer and took availability offline."""
    got = await run_callback(pointer=CORK, stored_merchant="ML66K1YVCD1P0",
                             locations=[], list_raises=True)
    assert got["square_location_id"] == CORK, "a transient Square failure wiped the pointer"


@pytest.mark.asyncio
async def test_F_a_provider_failure_on_a_fresh_connect_leaves_it_unset():
    got = await run_callback(pointer=None, locations=[], list_raises=True)
    assert_no_pointer_written(got)


@pytest.mark.asyncio
async def test_G_zero_locations_leaves_it_unset():
    got = await run_callback(pointer=None, locations=[])
    assert_no_pointer_written(got)


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
    assert_no_pointer_written(got)
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


# ═══════════════════════════════════════════════════════════════════════════
# W7E.3b — merchant identity is preserved, never nulled, never swapped
#
# square_merchant_id stopped being a label when W7D and W7E made it part of the
# identity chain. `merchant_id or None` had become a routing hazard: a re-connect
# during a transient get_merchant_info failure wrote NULL and silently turned a
# correctly routed tenant into an unrouteable one.
# ═══════════════════════════════════════════════════════════════════════════

MERCHANT = "ML66K1YVCD1P0"
OTHER = "MLZZZOTHERMERCHANT"


@pytest.mark.asyncio
async def test_M1_existing_merchant_plus_the_same_id_persists_it():
    got = await run_callback(pointer=CORK, stored_merchant=MERCHANT,
                             locations=[loc(CORK)], merchant=MERCHANT)
    assert got["square_merchant_id"] == MERCHANT


@pytest.mark.asyncio
async def test_M2_a_transient_lookup_failure_PRESERVES_the_existing_merchant():
    """The routing-integrity case. Before this, the token response carrying no
    merchant id plus a failed get_merchant_info wrote NULL — and a NULL merchant
    means W7D booking routing and W7E catalog routing can no longer find the
    tenant at all."""
    got = await run_callback(pointer=CORK, stored_merchant=MERCHANT,
                             locations=[loc(CORK)], merchant="", info_raises=True)
    assert got["square_merchant_id"] == MERCHANT, "a transient failure wiped merchant identity"
    assert got["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_M3_a_DIFFERENT_authoritative_merchant_is_REFUSED_not_swapped():
    """Silently re-pointing a tenant at another Square account would leave its
    location bindings and mirrored appointments describing a merchant that no
    longer owns them. Nothing is written at all."""
    got, redirect = await run_callback(pointer=CORK, stored_merchant=MERCHANT,
                                       locations=[loc(CORK)], merchant=OTHER,
                                       want_redirect=True)
    assert got == {}, "a conflicting merchant identity was persisted"
    assert "square=error" in redirect


@pytest.mark.asyncio
async def test_M3b_the_refusal_also_withholds_the_new_access_token():
    """Refusing must not half-apply: the credential for the other merchant must
    not land on this tenant either."""
    got, _ = await run_callback(pointer=CORK, stored_merchant=MERCHANT,
                                locations=[loc(CORK)], merchant=OTHER, want_redirect=True)
    assert "square_access_token" not in got


@pytest.mark.asyncio
async def test_M4_first_connect_with_a_token_merchant_id_persists_it():
    got = await run_callback(pointer=None, stored_merchant=None,
                             locations=[loc(CORK)], merchant=MERCHANT)
    assert got["square_merchant_id"] == MERCHANT


@pytest.mark.asyncio
async def test_M5_first_connect_falls_back_to_the_provider_lookup():
    """Token response carried no merchant id; get_merchant_info supplies it."""
    got = await run_callback(pointer=None, stored_merchant=None, locations=[loc(CORK)],
                             merchant="", info_merchant=MERCHANT)
    assert got["square_merchant_id"] == MERCHANT


@pytest.mark.asyncio
async def test_M6_first_connect_with_NO_merchant_identity_persists_nothing():
    """Completing OAuth here would leave a half-configured integration that
    cannot route and yet looks connected."""
    got, redirect = await run_callback(pointer=None, stored_merchant=None, locations=[loc(CORK)],
                                       merchant="", info_raises=True, want_redirect=True)
    assert got == {}, "a half-configured Square integration was persisted"
    assert "square=error" in redirect


@pytest.mark.asyncio
async def test_M7_the_merchant_id_is_never_written_as_None():
    got = await run_callback(pointer=None, stored_merchant=None,
                             locations=[loc(CORK)], merchant=MERCHANT)
    assert got["square_merchant_id"]
    assert got["square_merchant_id"] is not None


def test_M8_the_write_can_no_longer_null_the_merchant():
    code = _executable_source(sc)
    assert "'square_merchant_id': merchant_id" in code.replace('"', "'")
    assert "'square_merchant_id': merchant_id or None" not in code.replace('"', "'")


def test_M9_both_refusals_happen_BEFORE_any_write():
    code = _executable_source(sc.callback)
    head = code[:code.index("update = {")]
    assert head.count("return RedirectResponse") >= 2, \
        "the merchant guard does not refuse before update_tenant"
    assert "observed_merchant_id" in head
