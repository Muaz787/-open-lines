"""W7E — catalog.version.updated routes to EVERY eligible tenant, not to one row.

WHAT WAS WRONG
catalog.version.updated was the last Square webhook family choosing its tenant
with get_tenant_by_square_merchant_id() -> .limit(1), no ORDER BY. After the W7F
cutover ML66K1YVCD1P0 is claimed by two tenants, so the same event produced two
different outcomes depending on database row order: land on Shahid (appointments
off) and DANI silently never learns its catalog changed; land on DANI and it is
correct. Nothing is corrupted — which is what makes it dangerous. The failure is
a refresh that quietly does not happen.

WHY NOT THE BOOKING RESOLVER
W7A resolves a booking by LOCATION. A catalog envelope carries no location at
all, so there is nothing to resolve and inventing one would be guessing. Catalog
is merchant-level truth, so every eligible tenant claiming the merchant gets it.

THE TESTS THAT MATTER MOST
Three properties are asserted by showing something did NOT happen:
  * candidate ORDER cannot change the result
  * an INELIGIBLE tenant cannot suppress an eligible one
  * one tenant's FAILURE cannot stop another being attempted
"""
import ast
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from services import square_catalog_routing as w7e

MERCHANT = "ML66K1YVCD1P0"
DANI, SHAHID, THIRD = "tenant-dani", "tenant-shahid", "tenant-third"


def _executable_source(module) -> str:
    tree = ast.parse(inspect.getsource(module))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def tenant(tid, *, merchant=MERCHANT, appts=True, token="enc", active=True):
    return {"id": tid, "business_name": tid, "square_merchant_id": merchant,
            "square_appointments_enabled": appts, "square_access_token": token,
            "is_active": active}


def event(merchant=MERCHANT, etype="catalog.version.updated"):
    return {"event_id": "evt-cat-1", "type": etype, "merchant_id": merchant,
            "data": {"type": "catalog.version", "id": "cv1",
                     "object": {"catalog_version": {"updated_at": "2026-09-11T22:00:00Z"}}}}


def routed(candidates, *, sync=None):
    """Run the router with a given candidate set and a stubbed sync()."""
    calls = []

    async def default_sync(tid):
        calls.append(tid)
        return {"ok": True, "services": [1, 2], "staff": [3]}

    impl = sync or default_sync

    async def spy(tid):
        calls.append(tid)
        return await impl(tid) if sync else {"ok": True, "services": [1, 2], "staff": [3]}

    return calls, patch.multiple(
        "db.square_routing",
        list_tenants_by_square_merchant_id=AsyncMock(return_value=list(candidates))), \
        patch("services.square_booking.sync", new=AsyncMock(side_effect=spy))


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — the eligibility rule, independently testable
# ═══════════════════════════════════════════════════════════════════════════

def test_B_a_single_eligible_candidate_is_eligible():
    ok, why = w7e.catalog_sync_eligibility(tenant(DANI), MERCHANT)
    assert (ok, why) == (True, "")


def test_C_appointments_disabled_is_ineligible():
    ok, why = w7e.catalog_sync_eligibility(tenant(SHAHID, appts=False), MERCHANT)
    assert (ok, why) == (False, w7e.SKIP_APPOINTMENTS_DISABLED)


def test_eligibility_requires_a_square_credential():
    ok, why = w7e.catalog_sync_eligibility(tenant(DANI, token=None), MERCHANT)
    assert (ok, why) == (False, w7e.SKIP_NOT_CONNECTED)


def test_eligibility_refuses_a_deactivated_tenant():
    """An operator-deactivated tenant takes no unsolicited provider writes."""
    ok, why = w7e.catalog_sync_eligibility(tenant(DANI, active=False), MERCHANT)
    assert (ok, why) == (False, w7e.SKIP_TENANT_INACTIVE)


def test_eligibility_rechecks_the_merchant_itself():
    """Defensive: this function authorises a write, so it does not trust its
    caller to have filtered correctly."""
    ok, why = w7e.catalog_sync_eligibility(tenant(DANI, merchant="OTHER"), MERCHANT)
    assert (ok, why) == (False, w7e.SKIP_MERCHANT_MISMATCH)
    assert w7e.catalog_sync_eligibility({}, MERCHANT)[0] is False


def test_eligibility_is_pure_and_total():
    t = tenant(DANI)
    snapshot = dict(t)
    w7e.catalog_sync_eligibility(t, MERCHANT)
    assert t == snapshot, "the eligibility rule mutated the tenant it was given"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — all-candidate routing
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_A_no_candidates_is_a_safe_explicit_no_op():
    calls, p1, p2 = routed([])
    with p1, p2:
        r = await w7e.route_catalog_event(event())
    assert r.result == w7e.RESULT_NO_CANDIDATES
    assert calls == []
    assert r.should_retry is False, "retrying cannot conjure a candidate"


@pytest.mark.asyncio
async def test_B2_one_candidate_eligible_syncs_exactly_once():
    calls, p1, p2 = routed([tenant(DANI)])
    with p1, p2:
        r = await w7e.route_catalog_event(event())
    assert calls == [DANI]
    assert r.result == w7e.RESULT_SYNCED
    assert [o.result for o in r.outcomes] == [w7e.SYNCED]


@pytest.mark.asyncio
async def test_C2_one_candidate_ineligible_syncs_nothing():
    calls, p1, p2 = routed([tenant(SHAHID, appts=False)])
    with p1, p2:
        r = await w7e.route_catalog_event(event())
    assert calls == []
    assert r.result == w7e.RESULT_NO_ELIGIBLE
    assert r.skipped[0].detail == w7e.SKIP_APPOINTMENTS_DISABLED
    assert r.should_retry is False


@pytest.mark.asyncio
async def test_D_two_candidates_only_dani_eligible_is_production_today():
    """The exact live topology: Shahid (appointments off) + DANI (on)."""
    calls, p1, p2 = routed([tenant(SHAHID, appts=False), tenant(DANI)])
    with p1, p2:
        r = await w7e.route_catalog_event(event())
    assert calls == [DANI], "Shahid must not be synced, DANI must be"
    assert r.candidate_count == 2
    assert r.eligible_count == 1
    assert r.result == w7e.RESULT_SYNCED


@pytest.mark.asyncio
async def test_E_two_eligible_tenants_are_BOTH_synced():
    """The property .limit(1) could never have: a merchant may legitimately be
    claimed by two tenants that both book through Square."""
    calls, p1, p2 = routed([tenant(DANI), tenant(THIRD)])
    with p1, p2:
        r = await w7e.route_catalog_event(event())
    assert sorted(calls) == sorted([DANI, THIRD])
    assert len(r.synced) == 2
    assert r.result == w7e.RESULT_SYNCED


@pytest.mark.asyncio
async def test_F_candidate_ORDER_cannot_change_the_result():
    """Row order from the database must decide nothing. This is the bug."""
    results = []
    for order in ([tenant(SHAHID, appts=False), tenant(DANI), tenant(THIRD)],
                  [tenant(THIRD), tenant(DANI), tenant(SHAHID, appts=False)],
                  [tenant(DANI), tenant(SHAHID, appts=False), tenant(THIRD)]):
        calls, p1, p2 = routed(order)
        with p1, p2:
            r = await w7e.route_catalog_event(event())
        results.append((tuple(sorted(calls)), r.result, len(r.synced), len(r.skipped)))
    assert len(set(results)) == 1, f"order changed the outcome: {results}"
    assert results[0] == (tuple(sorted([DANI, THIRD])), w7e.RESULT_SYNCED, 2, 1)


@pytest.mark.asyncio
async def test_an_ineligible_candidate_cannot_suppress_an_eligible_one():
    """The original defect in one sentence: Shahid was chosen, returned early,
    and DANI never learned anything had changed."""
    for order in ([tenant(SHAHID, appts=False), tenant(DANI)],
                  [tenant(DANI), tenant(SHAHID, appts=False)]):
        calls, p1, p2 = routed(order)
        with p1, p2:
            await w7e.route_catalog_event(event())
        assert DANI in calls


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — tenant isolation and retry semantics
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_G_one_eligible_sync_fails_and_the_other_is_STILL_attempted():
    attempted = []

    async def flaky(tid):
        attempted.append(tid)
        if tid == DANI:
            raise RuntimeError("square 500")
        return {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=flaky)):
        r = await w7e.route_catalog_event(event())

    assert sorted(attempted) == sorted([DANI, THIRD]), "a failure stopped the other tenant"
    assert len(r.failed) == 1 and len(r.synced) == 1
    assert r.result == w7e.RESULT_PARTIAL
    assert r.should_retry is True, "a raised sync is transient and worth redelivery"


@pytest.mark.asyncio
async def test_H_all_eligible_syncs_fail():
    async def boom(tid):
        raise RuntimeError("provider down")

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=boom)):
        r = await w7e.route_catalog_event(event())
    assert r.result == w7e.RESULT_FAILED
    assert len(r.failed) == 2
    assert r.should_retry is True


@pytest.mark.asyncio
async def test_K_a_credential_failure_for_one_tenant_is_reported_not_retried():
    """sync() reports not_connected by returning ok=False rather than raising.
    Retrying cannot fix it, so it must not become an endless redelivery."""
    async def refuse(tid):
        return {"ok": False, "error": "not_connected"} if tid == DANI else \
               {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=refuse)):
        r = await w7e.route_catalog_event(event())
    assert [o.detail for o in r.failed] == ["not_connected"]
    assert len(r.synced) == 1
    assert r.should_retry is False, "a structural refusal must not loop forever"


def _http_error(status: int, url: str = "https://connect.squareup.com/v2/catalog/search", code: str = ""):
    import httpx
    request = httpx.Request("POST", url)
    body = {"errors": [{"category": "AUTHENTICATION_ERROR", "code": code}]} if code else {}
    return httpx.HTTPStatusError(f"Client error '{status}'", request=request,
                                 response=httpx.Response(status, request=request, json=body))


@pytest.mark.asyncio
async def test_M_a_confirmed_rejection_fails_that_tenant_while_healthy_ones_sync():
    """Production 2026-11-06: one workspace's Square credential was revoked. Its
    sync raised a 401 and the whole event was redelivered, re-syncing every other
    workspace each time. Now a CONFIRMED rejection is reported for that workspace,
    the healthy workspace syncs, and the event is not retried for it."""
    from services import square_booking as sb
    attempted = []

    async def mixed(tid):
        attempted.append(tid)
        if tid == DANI:
            raise sb.CredentialRejected("UNAUTHORIZED")
        return {"ok": True, "services": [{"id": "s"}], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=mixed)):
        r = await w7e.route_catalog_event(event())
    assert sorted(attempted) == sorted([DANI, THIRD])
    assert [o.tenant_id for o in r.synced] == [THIRD], "the healthy workspace synced"
    assert [(o.tenant_id, o.detail) for o in r.failed] == [(DANI, w7e.FAIL_CREDENTIAL_REJECTED)]
    assert r.result == w7e.RESULT_PARTIAL
    assert r.should_retry is False, "a confirmed rejection must not redeliver the event"
    assert f"{DANI[:8]}…=failed(credential_rejected)" in r.summary, "surfaced in the ledger"


@pytest.mark.asyncio
@pytest.mark.parametrize("transient", [
    lambda: _http_error(401), lambda: _http_error(401, code="ACCESS_TOKEN_EXPIRED"),
    lambda: _http_error(500), lambda: _http_error(503), lambda: _http_error(429),
    lambda: _http_error(403), lambda: TimeoutError("read timeout"), lambda: ConnectionError("reset")])
async def test_M2_anything_not_confirmed_is_still_retried(transient):
    """A bare 401 reaching the router has not been confirmed by sync(), so it is
    retried like any other raised failure."""
    async def flaky(tid):
        if tid == DANI:
            raise transient()
        return {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=flaky)):
        r = await w7e.route_catalog_event(event())
    assert len(r.synced) == 1 and r.failed[0].detail.startswith("raised:")
    assert r.should_retry is True


@pytest.mark.asyncio
async def test_M3_a_confirmed_rejection_does_not_hide_a_transient_failure_elsewhere():
    from services import square_booking as sb

    async def both(tid):
        if tid == DANI:
            raise sb.CredentialRejected("ACCESS_TOKEN_REVOKED")
        if tid == SHAHID:
            raise _http_error(502)
        return {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(SHAHID), tenant(THIRD)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=both)):
        r = await w7e.route_catalog_event(event())
    assert len(r.synced) == 1 and len(r.failed) == 2
    assert r.should_retry is True, "the transient failure still earns a redelivery"


# ── through the REAL sync() and the REAL token refresh ───────────────────────

def _near_expiry(hours=2):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _real_sync(stored, *, refresh=None, catalog_error=None, extra=()):
    """Patches for running the real route -> sync -> get_access_token_checked chain.
    Records every database write the sync makes."""
    from services import square_booking as sb
    writes = []
    ps = [patch("db.square_routing.list_tenants_by_square_merchant_id", new=AsyncMock(return_value=[stored])),
          patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=stored)),
          patch.object(sb, "decrypt", new=lambda v: f"plain-{v}"),
          patch("services.square_service.list_locations", new=AsyncMock(return_value=[])),
          patch.object(sb, "retrieve_booking_profile", new=AsyncMock(return_value={"booking_enabled": True})),
          patch.object(sb, "list_services", new=AsyncMock(side_effect=catalog_error) if catalog_error
                       else AsyncMock(return_value=[])),
          patch.object(sb, "list_team_members", new=AsyncMock(return_value=[])),
          patch("db.supabase.replace_square_services", new=AsyncMock(side_effect=lambda *a: writes.append(("services", a)))),
          patch("db.supabase.replace_square_staff", new=AsyncMock(side_effect=lambda *a: writes.append(("staff", a)))),
          patch("db.supabase.update_tenant", new=AsyncMock(side_effect=lambda *a: writes.append(("tenant", a)))),
          patch("services.square_service.refresh_access_token",
                new=refresh or AsyncMock(side_effect=AssertionError("no refresh expected"))),
          *extra]
    return ps, writes


async def _route_with(ps):
    import contextlib
    with contextlib.ExitStack() as st:
        for p in ps:
            st.enter_context(p)
        return await w7e.route_catalog_event(event())


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["ACCESS_TOKEN_EXPIRED", "UNAUTHORIZED", ""])
async def test_M6_refresh_fails_then_the_expired_token_gets_401_and_is_RETRIED(code):
    """The sequence: the token is near expiry, the refresh fails temporarily, sync
    falls back to the stored (expired) token, and Square answers 401. A later
    delivery may refresh successfully, so this must stay retryable."""
    stored = tenant(DANI) | {"square_refresh_token": "r", "square_token_expires_at": _near_expiry(-1)}
    refresh = AsyncMock(side_effect=ConnectionError("oauth endpoint unreachable"))
    ps, writes = _real_sync(stored, refresh=refresh, catalog_error=_http_error(401, code=code))
    r = await _route_with(ps)
    assert refresh.await_count == 1, "the normal refresh was attempted first"
    assert r.failed[0].detail.startswith("raised:") and r.failed[0].detail != w7e.FAIL_CREDENTIAL_REJECTED
    assert r.should_retry is True
    assert writes == [], "nothing written for a failed sync"


@pytest.mark.asyncio
async def test_M6b_an_incomplete_refresh_response_is_also_not_a_confirmation():
    stored = tenant(DANI) | {"square_refresh_token": "r", "square_token_expires_at": _near_expiry(-1)}
    ps, _ = _real_sync(stored, refresh=AsyncMock(return_value={}), catalog_error=_http_error(401))
    r = await _route_with(ps)
    assert r.should_retry is True and r.failed[0].detail.startswith("raised:")


@pytest.mark.asyncio
async def test_M7_refreshed_just_now_and_still_rejected_is_confirmed():
    stored = tenant(DANI) | {"square_refresh_token": "r", "square_token_expires_at": _near_expiry()}
    refresh = AsyncMock(return_value={"access_token": "new", "expires_at": "2026-12-06T00:00:00Z"})
    ps, writes = _real_sync(stored, refresh=refresh, catalog_error=_http_error(401, code="UNAUTHORIZED"),
                            extra=[patch("services.security.encrypt", new=lambda v: f"enc-{v}")])
    r = await _route_with(ps)
    assert refresh.await_count == 1
    assert [(o.tenant_id, o.detail) for o in r.failed] == [(DANI, w7e.FAIL_CREDENTIAL_REJECTED)]
    assert r.should_retry is False
    assert [w[0] for w in writes] == ["tenant"], "only the refresh's own token write happened"


@pytest.mark.asyncio
async def test_M8_no_refresh_due_and_square_says_expired_with_a_refresh_token_is_retried():
    """Expired per Square, but a refresh token is on file: a refresh might fix it."""
    stored = tenant(DANI) | {"square_refresh_token": "r", "square_token_expires_at": None}
    ps, _ = _real_sync(stored, catalog_error=_http_error(401, code="ACCESS_TOKEN_EXPIRED"))
    r = await _route_with(ps)
    assert r.should_retry is True and r.failed[0].detail.startswith("raised:")


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_extra, code", [
    ({"square_refresh_token": None}, "UNAUTHORIZED"),            # production's DANI Test
    ({"square_refresh_token": None}, "ACCESS_TOKEN_EXPIRED"),    # expired, nothing to refresh with
    ({"square_refresh_token": None}, ""),                        # bare 401, nothing to refresh with
    ({"square_refresh_token": "r", "square_token_expires_at": None}, "ACCESS_TOKEN_REVOKED"),
    ({"square_refresh_token": "r", "square_token_expires_at": "2027-01-01T00:00:00Z"}, "ACCESS_TOKEN_REVOKED"),
    ({"square_refresh_token": "r", "square_token_expires_at": None}, "V1_ACCESS_TOKEN"),
])
async def test_M9_confirmed_rejections_through_the_real_sync(stored_extra, code):
    stored = tenant(DANI) | stored_extra
    ps, writes = _real_sync(stored, catalog_error=_http_error(401, code=code))
    r = await _route_with(ps)
    assert [(o.tenant_id, o.detail) for o in r.failed] == [(DANI, w7e.FAIL_CREDENTIAL_REJECTED)]
    assert r.should_retry is False and writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_at", [None, "2027-01-01T00:00:00Z"])
@pytest.mark.parametrize("code", ["", "UNAUTHORIZED", "ACCESS_TOKEN_EXPIRED", "CLIENT_DISABLED",
                                  "APPLICATION_DISABLED", "SOMETHING_SQUARE_ADDS_LATER"])
async def test_M13_a_current_token_with_a_refresh_token_needs_an_explicit_permanent_code(expires_at, code):
    """Current token (no refresh due), refresh token on file: a bare 401, the
    generic UNAUTHORIZED, an expiry, an app-wide code or an unknown code is NOT a
    confirmed rejection. Through the real sync(); retried, nothing written."""
    stored = tenant(DANI) | {"square_refresh_token": "r", "square_token_expires_at": expires_at}
    ps, writes = _real_sync(stored, catalog_error=_http_error(401, code=code))
    r = await _route_with(ps)
    assert r.failed[0].detail.startswith("raised:"), r.summary
    assert r.should_retry is True and writes == []


def test_M14_the_permanent_codes_are_explicit():
    from services import square_booking as sb
    assert sb.PERMANENT_CREDENTIAL_CODES == frozenset({"ACCESS_TOKEN_REVOKED", "V1_ACCESS_TOKEN"})
    for status, code, expected in [
        (sb.TOKEN_CURRENT, "ACCESS_TOKEN_REVOKED", True), (sb.TOKEN_CURRENT, "V1_ACCESS_TOKEN", True),
        (sb.TOKEN_CURRENT, "UNAUTHORIZED", False), (sb.TOKEN_CURRENT, "", False),
        (sb.TOKEN_CURRENT, "ACCESS_TOKEN_EXPIRED", False), (sb.TOKEN_CURRENT, "CLIENT_DISABLED", False),
        (sb.TOKEN_REFRESH_FAILED, "ACCESS_TOKEN_REVOKED", False), (sb.TOKEN_REFRESH_FAILED, "", False),
        (sb.TOKEN_REFRESHED, "", True), (sb.TOKEN_REFRESHED, "UNAUTHORIZED", True),
        (sb.TOKEN_NOT_REFRESHABLE, "", True), (sb.TOKEN_NOT_REFRESHABLE, "UNAUTHORIZED", True)]:
        assert sb.rejection_confirmed(_http_error(401, code=code), status) is expected, (status, code)
    assert sb.rejection_confirmed(_http_error(403, code="ACCESS_TOKEN_REVOKED"), sb.TOKEN_CURRENT) is False


@pytest.mark.asyncio
async def test_M10_mixed_workspaces_through_the_real_sync():
    """A confirmed rejection for one workspace; the other syncs and writes its catalog."""
    from services import square_booking as sb
    revoked = tenant(DANI) | {"square_access_token": "enc-dani", "square_refresh_token": None}
    healthy = tenant(THIRD) | {"square_access_token": "enc-third", "square_refresh_token": "r"}

    async def services_for(token):
        if token == "plain-enc-dani":
            raise _http_error(401, code="UNAUTHORIZED")
        return [{"id": "svc"}]
    ps, writes = _real_sync(healthy, extra=[
        patch("db.square_routing.list_tenants_by_square_merchant_id", new=AsyncMock(return_value=[revoked, healthy])),
        patch("db.supabase.get_tenant_by_id", new=AsyncMock(side_effect=lambda tid: {DANI: revoked, THIRD: healthy}[tid])),
        patch.object(sb, "list_services", new=AsyncMock(side_effect=services_for))])
    r = await _route_with(ps)
    assert [o.tenant_id for o in r.synced] == [THIRD], "the healthy workspace synced"
    assert [(o.tenant_id, o.detail) for o in r.failed] == [(DANI, w7e.FAIL_CREDENTIAL_REJECTED)]
    assert r.should_retry is False
    assert ("services", (THIRD, [{"id": "svc"}])) in writes and all(w[1][0] == THIRD for w in writes)


def test_M11_get_access_token_is_unchanged_from_main():
    import subprocess
    from services import square_booking as sb
    import inspect
    main_src = subprocess.run(["git", "show", "main:backend/services/square_booking.py"],
                              capture_output=True, text=True).stdout
    if main_src:
        start = main_src.index("async def get_access_token(")
        end = main_src.index("\n\n\n", start)
        assert inspect.getsource(sb.get_access_token).strip() == main_src[start:end].strip()


@pytest.mark.parametrize("hours, has_refresh, due", [
    (-1, True, True), (2, True, True), (71, True, True), (73, True, False), (24 * 30, True, False),
    (2, False, False), (None, True, False)])
def test_M12_the_refresh_due_rule_matches_get_access_token(hours, has_refresh, due):
    """_refresh_due() mirrors get_access_token()'s window: drive the real function
    and see whether it tries to refresh."""
    import asyncio
    from services import square_booking as sb
    t = {"id": "t", "square_access_token": "enc",
         "square_refresh_token": "r" if has_refresh else None,
         "square_token_expires_at": _near_expiry(hours) if hours is not None else None}
    refresh = AsyncMock(side_effect=ConnectionError("x"))
    with patch.object(sb, "decrypt", new=lambda v: v), \
         patch("services.square_service.refresh_access_token", new=refresh):
        asyncio.run(sb.get_access_token(t))
    assert bool(refresh.await_count) is due
    assert sb._refresh_due(t) is due


@pytest.mark.asyncio
async def test_L_a_candidate_lookup_failure_is_transient_and_retried():
    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(side_effect=RuntimeError("postgrest down"))):
        r = await w7e.route_catalog_event(event())
    assert r.result == w7e.RESULT_FAILED
    assert r.should_retry is True


@pytest.mark.asyncio
async def test_J_missing_or_malformed_merchant_id_is_a_safe_no_op():
    for bad in ({"merchant_id": ""}, {"merchant_id": "   "}, {"merchant_id": None}):
        with patch("db.square_routing.list_tenants_by_square_merchant_id",
                   new=AsyncMock(side_effect=AssertionError("must not be called"))):
            r = await w7e.route_catalog_event({**event(), **bad})
        assert r.result == w7e.RESULT_NO_MERCHANT
        assert r.should_retry is False


class _Nasty(Exception):
    """An exception type the router has never heard of."""


@pytest.mark.asyncio
async def test_route_catalog_event_never_raises():
    """The caller is a webhook endpoint whose other arms carry payments, so an
    unknown sync failure must become a recorded outcome, not an exception.

    KeyboardInterrupt/SystemExit are deliberately NOT guarded — those must
    always propagate."""
    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=_Nasty("boom"))):
        r = await w7e.route_catalog_event(event())
    assert r.result == w7e.RESULT_FAILED
    assert r.failed[0].detail == "raised: _Nasty"
    assert r.should_retry is True


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5/6 — tenant-scoped writes and duplicate delivery
# ═══════════════════════════════════════════════════════════════════════════

def test_R_catalog_writes_are_tenant_scoped_by_construction():
    """Cross-tenant leakage is impossible because the write helpers filter and
    stamp tenant_id themselves — not because the router remembers to."""
    import db.supabase as dbs
    for fn in (dbs.replace_square_services, dbs.replace_square_staff):
        src = inspect.getsource(fn)
        assert '.eq("tenant_id", tenant_id)' in src, f"{fn.__name__} deletes unscoped"
        assert '"tenant_id": tenant_id' in src, f"{fn.__name__} inserts unstamped"


def test_S_T_service_and_staff_reads_are_tenant_scoped():
    import db.supabase as dbs
    for fn in (dbs.get_square_services, dbs.get_square_staff):
        assert '.eq("tenant_id", tenant_id)' in inspect.getsource(fn)


@pytest.mark.asyncio
async def test_R2_the_router_syncs_each_tenant_under_its_OWN_id():
    seen = []

    async def record(tid):
        seen.append(tid)
        return {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(DANI), tenant(THIRD), tenant(SHAHID, appts=False)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=record)):
        await w7e.route_catalog_event(event())
    assert sorted(seen) == sorted([DANI, THIRD])
    assert SHAHID not in seen, "an ineligible tenant received a catalog write"


@pytest.mark.asyncio
async def test_I_duplicate_delivery_is_stable_and_does_not_contaminate():
    calls = []

    async def record(tid):
        calls.append(tid)
        return {"ok": True, "services": [], "staff": []}

    with patch("db.square_routing.list_tenants_by_square_merchant_id",
               new=AsyncMock(return_value=[tenant(SHAHID, appts=False), tenant(DANI)])), \
         patch("services.square_booking.sync", new=AsyncMock(side_effect=record)):
        first = await w7e.route_catalog_event(event())
        second = await w7e.route_catalog_event(event())

    assert calls == [DANI, DANI], "a duplicate must re-sync the same tenant, no other"
    assert first.result == second.result
    assert [o.result for o in first.outcomes] == [o.result for o in second.outcomes]
    assert SHAHID not in calls


def test_duplicate_safety_comes_from_replace_semantics_not_event_dedupe():
    """sync() replaces the tenant's rows wholesale, so a second identical
    delivery converges rather than duplicating. No event-id dedupe was added,
    and the ledger is not consulted."""
    import db.supabase as dbs
    assert ".delete()" in inspect.getsource(dbs.replace_square_services)
    code = _executable_source(w7e)
    assert "provider_webhook_events" not in code
    assert "delivery_count" not in code


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9 — static invariants
# ═══════════════════════════════════════════════════════════════════════════

def test_O_no_limit_1_merchant_selection_on_the_live_catalog_path():
    code = _executable_source(w7e)
    assert ".limit(1)" not in code
    assert "get_tenant_by_square_merchant_id" not in code
    assert "list_tenants_by_square_merchant_id" in code


def test_no_arbitrary_first_row_choice():
    code = _executable_source(w7e)
    for pattern in ("candidates[0]", "[0]", ".pop()", "next(iter("):
        assert pattern not in code, f"the router picks a row with {pattern!r}"


def test_M_the_catalog_path_never_invokes_the_booking_resolver():
    code = _executable_source(w7e)
    for forbidden in ("resolve_square_tenant_location", "load_location_candidates",
                      "reconcile_booking_event", "square_webhook_identity",
                      "provider_location_id", "tenant_location_id"):
        assert forbidden not in code, f"catalog reached for {forbidden}"


def test_N_the_catalog_path_makes_no_provider_mutation():
    code = _executable_source(w7e)
    for forbidden in ("create_booking", "cancel_booking", "update_booking",
                      "create_customer", "create_payment", "refund"):
        assert forbidden not in code


def test_no_W6A2_integration_was_added():
    code = _executable_source(w7e)
    # "appointments_disabled" is an eligibility reason, not W6A2 — match the
    # actual W6A2 identifiers rather than a substring that collides with it.
    for forbidden in ("mutation_claims", "claim_mutation", "reschedule_ops",
                      "insert_appointment", "reconcile_appointment_if_newer",
                      "appointment_mutation", "db.supabase"):
        assert forbidden not in code, f"W7E reached for {forbidden}"


def test_the_ledger_is_not_read_as_routing_authority():
    code = _executable_source(w7e)
    assert "provider_webhook_events" not in code
    assert "ledger" not in code


def test_outcomes_are_immutable_records():
    o = w7e.TenantOutcome(DANI, w7e.SYNCED)
    with pytest.raises(Exception):
        o.result = w7e.FAILED
    r = w7e.CatalogRouting(MERCHANT, 1, (o,))
    with pytest.raises(Exception):
        r.merchant_id = "OTHER"


def test_the_summary_carries_no_credential_or_catalog_payload():
    r = w7e.CatalogRouting(MERCHANT, 2, (w7e.TenantOutcome(DANI, w7e.SYNCED),
                                         w7e.TenantOutcome(SHAHID, w7e.SKIPPED,
                                                           w7e.SKIP_APPOINTMENTS_DISABLED)))
    s = r.summary
    assert "candidates=2" in s and "eligible=1" in s and "synced=1" in s and "skipped=1" in s
    for leak in ("token", "access", "secret", "service_variation", "Bearer"):
        assert leak not in s.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Phase 9 — the endpoint arm, and what it must NOT have disturbed
# ═══════════════════════════════════════════════════════════════════════════

def test_the_catalog_arm_routes_through_W7E_and_signals_retry_correctly():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert 'case "catalog.version.updated"' in src
    assert "_w7e.route_catalog_event(event)" in src
    assert "square_booking.handle_catalog_update(event)" not in src
    assert "_routing.should_retry" in src
    assert "status_code=503" in src


def test_Q_booking_routing_is_unchanged_by_W7E():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert '"booking.created" | "booking.updated"' in src
    assert "square_booking_reconcile.reconcile_booking_event(" in src
    assert "resolution=_resolution" in src
    assert "_w7id.resolve_event(event)" in src


def test_P_payment_and_refund_routing_is_unchanged_by_W7E():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert '"payment.updated" | "payment.created"' in src
    assert "_handle_square_payment_completed(event)" in src
    assert "get_payment_by_checkout_session(order_id)" in inspect.getsource(
        payments._handle_square_payment_completed)


def test_W7T_transport_files_are_untouched_by_W7E():
    from db import supabase_transport
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
    import db.supabase as dbs
    assert "supabase_transport.install()" in inspect.getsource(dbs.get_client)
