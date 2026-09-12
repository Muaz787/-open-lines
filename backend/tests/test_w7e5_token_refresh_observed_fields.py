"""W7E.5 — the automatic Square token refresh writes only observed fields.

THE DEFECT
get_access_token() renews a token inside its 3-day window and used to persist:

    "square_access_token": encrypt(new_token),
    "square_token_expires_at": data.get("expires_at") or None,

A refresh that returned a new access token but no expiry therefore NULLED the
expiry. The gate above that refresh is

    if expires_at and refresh_enc:

so losing the expiry means the branch can never be entered again: a SUCCESSFUL
refresh would have permanently disabled refreshing for that tenant, and the
integration would simply expire at its next deadline with no warning.

The refresh token was worse in a quieter way — it was never persisted at all, so
a rotated credential was discarded and the next refresh would have presented a
superseded one.

Same partial-observation defect W7E.4 fixed in the OAuth callback, in the one
place that runs unattended.
"""
import ast
import inspect
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import AsyncMock, patch

import pytest

from services import square_booking as sb

TID = "t-1"
OLD_EXPIRY_SOON = (datetime.now(dt_timezone.utc) + timedelta(days=1)).isoformat()
OUTSIDE_WINDOW = (datetime.now(dt_timezone.utc) + timedelta(days=40)).isoformat()
NEW_EXPIRY = "2027-06-01T12:00:00Z"


def _executable_source(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def tenant(*, expiry=OLD_EXPIRY_SOON, refresh="enc:rt-old", access="enc:at-old"):
    return {"id": TID, "square_access_token": access,
            "square_refresh_token": refresh, "square_token_expires_at": expiry}


async def run(t, response, *, refresh_raises=False, update_raises=False):
    """Drive the real get_access_token with the provider and DB stubbed."""
    writes = []

    async def cap(tid, patch_):
        writes.append((tid, patch_))
        if update_raises:
            raise RuntimeError("db down")
        return {}

    rf = AsyncMock(side_effect=RuntimeError("square refresh failed")) if refresh_raises \
        else AsyncMock(return_value=response)

    with patch("services.square_booking.decrypt", side_effect=lambda v: v.replace("enc:", "")), \
         patch("services.security.encrypt", side_effect=lambda v: f"enc:{v}"), \
         patch("services.square_service.refresh_access_token", new=rf), \
         patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap)):
        returned = await sb.get_access_token(t)
    return returned, writes, rf


def only_patch(writes):
    assert len(writes) == 1, f"expected exactly one update_tenant, got {len(writes)}"
    return writes[0][1]


# ═══════════════════════════════════════════════════════════════════════════
# Access token
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A1_a_valid_refresh_persists_and_returns_the_new_access_token():
    got, writes, _ = await run(tenant(), {"access_token": "at-new",
                                          "refresh_token": "rt-new",
                                          "expires_at": NEW_EXPIRY})
    assert got == "at-new"
    assert only_patch(writes)["square_access_token"] == "enc:at-new"


@pytest.mark.asyncio
async def test_A2_a_response_with_NO_access_token_mutates_nothing():
    """An incomplete response is not a refresh."""
    got, writes, _ = await run(tenant(), {"expires_at": NEW_EXPIRY, "refresh_token": "rt-new"})
    assert writes == [], f"an incomplete refresh still wrote {writes}"
    assert got == "at-old", "the stored credential must still be returned"


@pytest.mark.asyncio
async def test_A2b_an_empty_access_token_mutates_nothing():
    got, writes, _ = await run(tenant(), {"access_token": "", "expires_at": NEW_EXPIRY})
    assert writes == []
    assert got == "at-old"


# ═══════════════════════════════════════════════════════════════════════════
# Refresh token rotation
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_R1_a_rotated_refresh_token_is_STORED():
    """Previously discarded entirely — the next refresh would then have
    presented a superseded credential."""
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "refresh_token": "rt-new",
                                        "expires_at": NEW_EXPIRY})
    assert only_patch(writes)["square_refresh_token"] == "enc:rt-new"


@pytest.mark.asyncio
async def test_R2_an_omitted_refresh_token_preserves_the_stored_one():
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": NEW_EXPIRY})
    assert "square_refresh_token" not in only_patch(writes)


@pytest.mark.asyncio
async def test_R3_an_empty_refresh_token_preserves_the_stored_one():
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "refresh_token": "",
                                        "expires_at": NEW_EXPIRY})
    assert "square_refresh_token" not in only_patch(writes)
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "refresh_token": "   ",
                                        "expires_at": NEW_EXPIRY})
    assert "square_refresh_token" not in only_patch(writes)


# ═══════════════════════════════════════════════════════════════════════════
# Expiry — the defect this gate exists for
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_E1_a_valid_new_expiry_is_stored_verbatim():
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": NEW_EXPIRY})
    assert only_patch(writes)["square_token_expires_at"] == NEW_EXPIRY


@pytest.mark.asyncio
async def test_E2_an_OMITTED_expiry_preserves_the_stored_one():
    """The headline case: nulling this would permanently disable refreshing,
    because the refresh branch requires `expires_at and refresh_enc`."""
    _, writes, _ = await run(tenant(), {"access_token": "at-new"})
    assert "square_token_expires_at" not in only_patch(writes), \
        "a successful refresh destroyed the expiry and disabled future refreshes"


@pytest.mark.asyncio
async def test_E3_an_empty_expiry_preserves_the_stored_one():
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": ""})
    assert "square_token_expires_at" not in only_patch(writes)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["not-a-date", "2027-13-45T99:99:99Z", "soon", "{}", "0"])
async def test_E4_a_malformed_expiry_is_neither_stored_nor_allowed_to_erase(bad):
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": bad})
    assert "square_token_expires_at" not in only_patch(writes), f"{bad!r} was persisted"


@pytest.mark.asyncio
async def test_E5_no_expiry_is_ever_FABRICATED():
    code = _executable_source(sb.get_access_token) + _executable_source(sb._observed_expiry)
    for forbidden in ("timedelta(days=90", "utcnow", "now() +"):
        assert forbidden not in code, f"the refresh path derives an expiry with {forbidden}"
    for missing in (None, "", "garbage"):
        _, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": missing})
        assert "square_token_expires_at" not in only_patch(writes)


def test_the_validator_matches_its_OAuth_twin_on_every_case():
    """The two copies must not drift."""
    from routers import square_connect as sc
    for case in ("2027-03-01T12:00:00Z", "2027-03-01T12:00:00+00:00", "2027-03-01T12:00:00",
                 None, "", "   ", "nope", "2027-13-45T99:99:99Z", 12345.7, {}):
        assert sb._observed_expiry(case) == sc._observed_expiry(case), f"drifted on {case!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Combinations
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_C1_new_access_refresh_and_expiry_all_update():
    _, writes, _ = await run(tenant(), {"access_token": "at-new", "refresh_token": "rt-new",
                                        "expires_at": NEW_EXPIRY})
    p = only_patch(writes)
    assert p == {"square_access_token": "enc:at-new",
                 "square_refresh_token": "enc:rt-new",
                 "square_token_expires_at": NEW_EXPIRY}


@pytest.mark.asyncio
async def test_C2_access_only_preserves_refresh_AND_expiry():
    _, writes, _ = await run(tenant(), {"access_token": "at-new"})
    assert only_patch(writes) == {"square_access_token": "enc:at-new"}


@pytest.mark.asyncio
async def test_C3_access_and_rotated_refresh_preserve_expiry():
    p = only_patch((await run(tenant(), {"access_token": "at-new", "refresh_token": "rt-new"}))[1])
    assert p == {"square_access_token": "enc:at-new", "square_refresh_token": "enc:rt-new"}


@pytest.mark.asyncio
async def test_C4_access_and_expiry_preserve_the_refresh_token():
    p = only_patch((await run(tenant(), {"access_token": "at-new", "expires_at": NEW_EXPIRY}))[1])
    assert p == {"square_access_token": "enc:at-new", "square_token_expires_at": NEW_EXPIRY}


@pytest.mark.asyncio
async def test_C5_a_provider_exception_mutates_nothing():
    got, writes, _ = await run(tenant(), {}, refresh_raises=True)
    assert writes == []
    assert got == "at-old", "the stored credential must still be usable"


@pytest.mark.asyncio
async def test_C6_a_DB_write_failure_does_not_claim_a_durable_refresh():
    """Documenting actual behaviour: the write is attempted, the exception is
    caught by the best-effort handler, and the STORED token is returned rather
    than the new one — so nothing downstream acts as if the refresh persisted."""
    got, writes, _ = await run(tenant(), {"access_token": "at-new", "expires_at": NEW_EXPIRY},
                               update_raises=True)
    assert len(writes) == 1, "the write was attempted"
    assert got == "at-old", "a failed persist must not return the unsaved token"


# ═══════════════════════════════════════════════════════════════════════════
# The refresh decision itself — unchanged
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_D1_a_token_OUTSIDE_the_window_is_not_refreshed():
    got, writes, rf = await run(tenant(expiry=OUTSIDE_WINDOW), {"access_token": "at-new"})
    rf.assert_not_awaited()
    assert writes == [] and got == "at-old"


@pytest.mark.asyncio
async def test_D2_a_token_INSIDE_the_window_with_a_refresh_token_is_refreshed():
    got, writes, rf = await run(tenant(), {"access_token": "at-new", "expires_at": NEW_EXPIRY})
    rf.assert_awaited_once()
    assert got == "at-new" and len(writes) == 1


@pytest.mark.asyncio
async def test_D3_no_refresh_token_means_no_refresh_attempt():
    """Documented limitation, unchanged: without a stored refresh credential the
    token simply runs to expiry."""
    got, writes, rf = await run(tenant(refresh=None), {"access_token": "at-new"})
    rf.assert_not_awaited()
    assert writes == [] and got == "at-old"


@pytest.mark.asyncio
async def test_D4_no_stored_expiry_means_no_refresh_attempt():
    """Unchanged, and exactly why nulling the expiry was so damaging."""
    got, writes, rf = await run(tenant(expiry=None), {"access_token": "at-new"})
    rf.assert_not_awaited()
    assert writes == [] and got == "at-old"


@pytest.mark.asyncio
async def test_D5_a_tenant_with_no_square_credential_returns_None():
    assert await sb.get_access_token({"id": TID}) is None


# ═══════════════════════════════════════════════════════════════════════════
# Phase C9 — structural invariants
# ═══════════════════════════════════════════════════════════════════════════

def _refresh_block() -> str:
    code = _executable_source(sb.get_access_token)
    return code[code.index("patch = {"):code.index("return new_token")]


def test_S1_S2_S3_no_optional_field_is_written_because_it_is_absent():
    block = _refresh_block().replace('"', "'")
    for bad in ("or None", "else None"):
        assert bad not in block, f"the refresh patch still contains {bad!r}"
    for key in ("square_refresh_token", "square_token_expires_at"):
        assert f"patch['{key}']" in block, f"{key} is never written at all"


def test_S5_the_access_token_must_be_observed_before_any_credential_write():
    code = _executable_source(sb.get_access_token)
    assert code.index("if new_token:") < code.index("patch = {")
    assert code.index("patch = {") < code.index("update_tenant")


def test_S6_exactly_one_update_tenant_on_the_refresh_path():
    assert _executable_source(sb.get_access_token).count("update_tenant") == 1


def test_S7_the_W7E4_OAuth_callback_is_untouched():
    from routers import square_connect as sc
    code = _executable_source(sc)
    assert "observed_merchant_id" in code
    assert "location_sync.choose_legacy_default_square_location" in code
    literal = code[code.index("update = {"):code.index("await db.update_tenant")].replace('"', "'")
    assert "or None" not in literal and "else None" not in literal


def test_S8_merchant_and_location_routing_untouched():
    from services import square_catalog_routing as w7e
    from services import square_webhook_identity as ident
    assert ".limit(1)" not in _executable_source(w7e)
    assert "load_location_candidates" in _executable_source(ident)


def test_S9_W7T_untouched():
    from db import supabase_transport
    import db.supabase as dbs
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
    assert "supabase_transport.install()" in inspect.getsource(dbs.get_client)


def test_S10_the_disconnect_path_still_clears_credentials_on_purpose():
    """An intentional clear, and it must stay intentional."""
    from routers import square_connect as sc
    code = _executable_source(sc)
    assert "'square_access_token': None" in code.replace('"', "'")
    assert "'square_refresh_token': None" in code.replace('"', "'")
