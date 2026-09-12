"""W7E.4 — the Square OAuth callback is an observed-fields-only patch.

THE PRINCIPLE
An OAuth response is PARTIAL EVIDENCE. The absence of a field proves nothing
about the durable value, so absence must never mean "write NULL". The callback
had been reconstructing the whole Square integration row from one response:

    "square_refresh_token":   encrypt(refresh_token) if refresh_token else None,
    "square_token_expires_at": expires_at or None,
    "square_currency":        currency or None,

On a reconnect each of those could destroy working state:

  * refresh token -> nulled. get_access_token() needs it to refresh before
    expiry, so a *successful* reconnect could leave a healthy integration
    unable to renew itself later.
  * expiry        -> nulled, disabling that same refresh from the other side:
    the guard is `if expires_at and refresh_enc`, so losing either is enough.
  * currency      -> nulled by a transient merchant lookup failure.

Now a key appears only when this transaction actually established a value.
"""
import ast
import inspect
import itertools
from unittest.mock import AsyncMock, patch

import pytest

from routers import square_connect as sc

MERCHANT = "ML66K1YVCD1P0"
OTHER = "MLZZZOTHERMERCHANT"
CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"
VALID_EXPIRY = "2027-03-01T12:00:00Z"
OLD_EXPIRY = "2026-12-01T12:00:00Z"


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


async def run(*, stored=None, token=None, info=None, info_raises=False,
              info_no_currency=False, locations=None, want_redirect=False):
    """Drive the real callback.

    stored -> the tenant row already on file
    token  -> what exchange_code returns
    info   -> what get_merchant_info returns
    """
    tenant = {"id": "t-1", "business_name": "T", "square_oauth_state": "st8",
              **(stored or {})}
    captured = {}

    async def cap(tid, update):
        captured.update(update)
        return {}

    token = {"access_token": "at-new", "refresh_token": "rt-new",
             "expires_at": VALID_EXPIRY, "merchant_id": MERCHANT, **(token or {})}
    if info_raises:
        info_mock = AsyncMock(side_effect=RuntimeError("merchant info down"))
    elif info_no_currency:
        info_mock = AsyncMock(return_value={"merchant_id": MERCHANT})   # no currency KEY
    else:
        info_mock = AsyncMock(return_value={"currency": "EUR", "merchant_id": MERCHANT, **(info or {})})

    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant)), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap)), \
         patch("services.square_service.exchange_code", new=AsyncMock(return_value=token)), \
         patch("services.square_service.get_merchant_info", new=info_mock), \
         patch("services.square_service.list_locations",
               new=AsyncMock(return_value=locations if locations is not None else [loc(CORK)])), \
         patch("routers.square_connect.encrypt", side_effect=lambda v: f"enc:{v}"), \
         patch("services.vapi.patch_assistant_tools", new=AsyncMock()), \
         patch("services.square_booking.sync", new=AsyncMock()), \
         patch("asyncio.create_task", side_effect=lambda coro: coro.close()):
        resp = await sc.callback(request=None, code="c", state="t-1:st8")
    if want_redirect:
        return captured, str(getattr(resp, "headers", {}).get("location", ""))
    return captured


CONNECTED = {"square_merchant_id": MERCHANT, "square_location_id": CORK,
             "square_refresh_token": "enc:rt-old", "square_token_expires_at": OLD_EXPIRY,
             "square_currency": "cad"}


# ═══════════════════════════════════════════════════════════════════════════
# Refresh token
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_R1_a_new_refresh_token_is_stored():
    got = await run(stored=CONNECTED, token={"refresh_token": "rt-new"})
    assert got["square_refresh_token"] == "enc:rt-new"


@pytest.mark.asyncio
async def test_R2_an_omitted_refresh_token_PRESERVES_the_stored_one():
    """The credential-destroying case: a successful reconnect must not leave a
    healthy integration unable to refresh itself later."""
    got = await run(stored=CONNECTED, token={"refresh_token": None})
    assert "square_refresh_token" not in got, \
        f"the refresh credential was overwritten with {got.get('square_refresh_token')!r}"


@pytest.mark.asyncio
async def test_R3_an_empty_refresh_token_preserves_the_stored_one():
    got = await run(stored=CONNECTED, token={"refresh_token": ""})
    assert "square_refresh_token" not in got


@pytest.mark.asyncio
async def test_R4_first_connect_with_a_refresh_token_stores_it():
    got = await run(stored={}, token={"refresh_token": "rt-new"})
    assert got["square_refresh_token"] == "enc:rt-new"


@pytest.mark.asyncio
async def test_R5_first_connect_without_one_writes_no_artificial_null():
    got = await run(stored={}, token={"refresh_token": None})
    assert "square_refresh_token" not in got
    assert got["square_access_token"] == "enc:at-new"


# ═══════════════════════════════════════════════════════════════════════════
# Expiry
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_E1_a_valid_new_expiry_is_stored_verbatim():
    got = await run(stored=CONNECTED, token={"expires_at": VALID_EXPIRY})
    assert got["square_token_expires_at"] == VALID_EXPIRY, \
        "the provider's own value must be stored, not a reformatted one"


@pytest.mark.asyncio
async def test_E2_an_absent_expiry_preserves_the_stored_one():
    got = await run(stored=CONNECTED, token={"expires_at": None})
    assert "square_token_expires_at" not in got


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-date", "2027-13-45T99:99:99Z", "soon", "{}", "12345"])
async def test_E3_a_malformed_expiry_is_neither_stored_nor_allowed_to_erase(bad):
    """Storing garbage would break get_access_token()'s fromisoformat parse and
    silently disable refresh-before-expiry; erasing would do the same thing from
    the other side."""
    got = await run(stored=CONNECTED, token={"expires_at": bad})
    assert "square_token_expires_at" not in got, f"{bad!r} was persisted"


@pytest.mark.asyncio
async def test_E3b_no_expiry_is_ever_FABRICATED_from_the_clock():
    """A synthesised expiry would extend the token's apparent life past the
    point where get_access_token() would have renewed it."""
    for missing in (None, "", "   ", "garbage"):
        got = await run(stored=CONNECTED, token={"expires_at": missing})
        assert "square_token_expires_at" not in got
    code = _executable_source(sc)
    for forbidden in ("timedelta", "utcnow", "now() +", "now(dt_timezone.utc) +"):
        assert forbidden not in code, f"the callback derives an expiry with {forbidden}"


@pytest.mark.asyncio
async def test_E4_first_connect_persists_a_valid_expiry():
    got = await run(stored={}, token={"expires_at": VALID_EXPIRY})
    assert got["square_token_expires_at"] == VALID_EXPIRY


@pytest.mark.asyncio
async def test_E5_first_connect_without_an_expiry_writes_nothing_for_it():
    got = await run(stored={}, token={"expires_at": None})
    assert "square_token_expires_at" not in got


def test_the_expiry_validator_accepts_real_square_shapes():
    for good in ("2027-03-01T12:00:00Z", "2027-03-01T12:00:00+00:00",
                 "2027-03-01T12:00:00.123Z", "2027-03-01T12:00:00"):
        assert sc._observed_expiry(good) == good
    for bad in (None, "", "   ", "nope", 12345.7, {}):
        assert sc._observed_expiry(bad) is None


# ═══════════════════════════════════════════════════════════════════════════
# Currency
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_C1_stored_cad_plus_authoritative_cad_stays_cad():
    got = await run(stored=CONNECTED, info={"currency": "CAD"})
    assert got["square_currency"] == "cad"


@pytest.mark.asyncio
async def test_C2_an_authoritative_different_currency_updates():
    got = await run(stored=CONNECTED, info={"currency": "EUR"})
    assert got["square_currency"] == "eur"


@pytest.mark.asyncio
async def test_C3_a_lookup_FAILURE_preserves_the_stored_currency():
    got = await run(stored=CONNECTED, info_raises=True, token={"merchant_id": MERCHANT})
    assert "square_currency" not in got, \
        f"a transient lookup failure overwrote currency with {got.get('square_currency')!r}"


@pytest.mark.asyncio
async def test_C4_an_absent_currency_preserves_the_stored_one():
    """A successful lookup that simply carries no currency is not evidence of
    USD. The old code defaulted to "USD" and would have overwritten CAD."""
    got = await run(stored=CONNECTED, info={"currency": None})
    assert "square_currency" not in got
    got = await run(stored=CONNECTED, info={"currency": ""})
    assert "square_currency" not in got


@pytest.mark.asyncio
async def test_C5_first_connect_persists_a_valid_currency():
    got = await run(stored={}, info={"currency": "EUR"})
    assert got["square_currency"] == "eur"


@pytest.mark.asyncio
async def test_C6_first_connect_without_a_currency_manufactures_none():
    got = await run(stored={}, info={"currency": None})
    assert "square_currency" not in got


@pytest.mark.asyncio
async def test_C4b_a_lookup_with_NO_currency_KEY_does_not_default_to_usd():
    """The scenario the old `merchant_info.get("currency", "USD")` default
    actually fired on: the lookup SUCCEEDS but simply carries no currency. That
    is not evidence of USD, and it would have overwritten a stored CAD."""
    got = await run(stored=CONNECTED, info={}, info_no_currency=True)
    assert "square_currency" not in got, \
        f"an invented currency {got.get('square_currency')!r} overwrote the stored one"


def test_the_currency_default_of_USD_is_gone():
    code = _executable_source(sc)
    assert '"USD"' not in code and "'USD'" not in code, \
        "a currency default would overwrite stored state with an invented value"


# ═══════════════════════════════════════════════════════════════════════════
# Identity interactions — W7E.3b must be untouched
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_I1_same_merchant_partial_response_patches_only_what_was_observed():
    got = await run(stored=CONNECTED,
                    token={"refresh_token": None, "expires_at": None},
                    info_raises=True)
    assert got["square_access_token"] == "enc:at-new"   # observed
    assert got["square_merchant_id"] == MERCHANT         # preserved
    for preserved in ("square_refresh_token", "square_token_expires_at", "square_currency"):
        assert preserved not in got, f"{preserved} was clobbered by a partial response"


@pytest.mark.asyncio
async def test_I2_merchant_absent_preserves_merchant_AND_obeys_the_other_rules():
    got = await run(stored=CONNECTED,
                    token={"merchant_id": "", "refresh_token": None, "expires_at": None},
                    info_raises=True)
    assert got["square_merchant_id"] == MERCHANT
    for preserved in ("square_refresh_token", "square_token_expires_at", "square_currency"):
        assert preserved not in got


@pytest.mark.asyncio
async def test_I3_a_conflicting_merchant_writes_NOTHING():
    got, redirect = await run(stored=CONNECTED, token={"merchant_id": OTHER}, want_redirect=True)
    assert got == {}, f"a refused reconnect still wrote {sorted(got)}"
    assert "square=error" in redirect


@pytest.mark.asyncio
async def test_I4_first_connect_with_no_merchant_identity_writes_NOTHING():
    got, redirect = await run(stored={}, token={"merchant_id": ""}, info_raises=True,
                              want_redirect=True)
    assert got == {}
    assert "square=error" in redirect


@pytest.mark.asyncio
async def test_I5_a_conflicting_merchant_persists_NO_credential():
    got, _ = await run(stored=CONNECTED,
                       token={"merchant_id": OTHER, "refresh_token": "rt-attacker",
                              "access_token": "at-attacker"},
                       want_redirect=True)
    for credential in ("square_access_token", "square_refresh_token", "square_token_expires_at"):
        assert credential not in got, f"{credential} leaked on a refused reconnect"


# ═══════════════════════════════════════════════════════════════════════════
# Location regression — W7E.3 must be untouched
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_L1_an_existing_single_location_pointer_is_preserved():
    got = await run(stored=CONNECTED, locations=[loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert got["square_location_id"] == CORK


@pytest.mark.asyncio
async def test_L2_a_DANI_shaped_tenant_gets_no_pointer():
    got = await run(stored={}, locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert "square_location_id" not in got


@pytest.mark.asyncio
async def test_L3_provider_order_does_not_change_topology():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        got = await run(stored={}, locations=list(order))
        assert "square_location_id" not in got
        got = await run(stored=CONNECTED, locations=list(order))
        assert got["square_location_id"] == CORK


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — structural guards
# ═══════════════════════════════════════════════════════════════════════════

def _update_dict_source() -> str:
    code = _executable_source(sc.callback)
    return code[code.index("update = {"):code.index("await db.update_tenant")]


def test_S1_S2_S3_the_three_fields_are_not_unconditionally_in_the_patch():
    literal = _update_dict_source()
    body = literal[:literal.index("}")]
    for key in ("square_refresh_token", "square_token_expires_at", "square_currency"):
        assert key not in body, f"{key} is written unconditionally"
    for key in ("square_refresh_token", "square_token_expires_at", "square_currency"):
        assert f"update['{key}']" in literal.replace('"', "'"), f"{key} is never written at all"


def test_S_no_field_in_the_patch_can_be_written_as_None_except_the_spent_nonce():
    literal = _update_dict_source().replace('"', "'")
    for bad in ("or None", "else None"):
        assert bad not in literal, f"the patch still contains a destructive {bad!r}"
    assert "'square_oauth_state': None" in literal, "the nonce must still be cleared"


def test_S4_S5_both_refusals_happen_before_update_tenant():
    code = _executable_source(sc.callback)
    head = code[:code.index("update = {")]
    assert "observed_merchant_id" in head
    assert head.count("return RedirectResponse") >= 2


def test_S6_merchant_id_can_never_be_written_as_None():
    literal = _update_dict_source().replace('"', "'")
    assert "'square_merchant_id': merchant_id" in literal
    assert "'square_merchant_id': merchant_id or None" not in literal


def test_S7_the_location_pointer_still_uses_the_W7E3_chooser():
    code = _executable_source(sc)
    assert "location_sync.choose_legacy_default_square_location" in code


def test_S8_no_executable_locations_index_zero_reappeared():
    code = _executable_source(sc)
    assert "locations[0]" not in code and "locs[0]" not in code


def test_S9_W7E3b_merchant_preservation_is_intact():
    code = _executable_source(sc.callback)
    assert "existing_merchant_id" in code and "observed_merchant_id" in code


def test_the_patch_keys_are_exactly_the_expected_set():
    """A regression net: if a new integration field is ever added to this dict,
    this test forces a decision about its authority rather than letting it
    inherit the old `x or None` habit."""
    literal = _update_dict_source()
    import re
    unconditional = set(re.findall(r"'(square_[a-z_]+)':", literal.replace('"', "'")))
    conditional = set(re.findall(r"update\['(square_[a-z_]+)'\]", literal.replace('"', "'")))
    assert unconditional == {"square_access_token", "square_merchant_id", "square_oauth_state"}
    assert conditional == {"square_refresh_token", "square_token_expires_at",
                           "square_currency", "square_location_id"}
