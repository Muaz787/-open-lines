"""W7E.2 — a deposit link never invents a tenant's default location.

THE DEFECT
routers/tools.py used to resolve the Square deposit location like this:

    location_id = tenant.get("square_location_id") or ""
    if not location_id:
        locs = await list_locations(access_token)
        if locs:
            location_id = locs[0].get("id", "")
            await db.update_tenant(tenant_id, {"square_location_id": location_id})

Two mistakes stacked. It picked `locs[0]` — Square's list order, which is not a
business rule and does not even skip a closed location — and then PERSISTED that
guess as the tenant's permanent default. A multi-location tenant could acquire a
global default merely because someone asked for a deposit. W7E.1 closed this in
catalog sync; this is the same defect on the payments path.

THE DISTINCTION THAT MATTERS
"which location is this deposit for" and "what is this tenant's default
location" are different questions. Answering the first must never invent an
answer to the second. A deposit is always FOR an appointment, and that
appointment already names the location the caller chose.
"""
import ast
import inspect
import itertools
from unittest.mock import AsyncMock, patch

import pytest

from routers import tools
from services import location_sync as ls

CORK, DUBLIN, LIMERICK = "L0Q8GTAZCHD42", "L9SA1AQ7XBM6K", "L9TTF8T2FBQE5"
DANI = "tenant-dani"


def _executable_source(obj) -> str:
    tree = ast.parse(inspect.getsource(obj))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if n.body and isinstance(n.body[0], ast.Expr) and \
               isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def loc(lid, *, status="ACTIVE", tz="Europe/Dublin"):
    return {"id": lid, "status": status, "timezone": tz, "name": lid}


def tenant(*, pointer=None, tid=DANI):
    return {"id": tid, "business_name": "DANI", "square_location_id": pointer,
            "square_access_token": "enc", "square_deposits_enabled": True,
            "square_currency": "eur"}


def appt(pid=None, tid=DANI):
    return {"id": "a-1", "tenant_id": tid, "provider_location_id": pid,
            "tenant_location_id": "loc-x"}


def resolve(t, appointment, locations, *, binding=True, list_raises=False):
    """Run the resolver with the two DB/provider reads stubbed."""
    lst = AsyncMock(side_effect=RuntimeError("square down")) if list_raises \
        else AsyncMock(return_value=locations)
    return patch.multiple(
        "routers.tools",
        _sq_list_locations=lst,
    ), patch("db.locations.get_binding",
             new=AsyncMock(return_value=({"id": "b1"} if binding else None))), t, appointment


async def run_resolve(t, appointment, locations, *, binding=True, list_raises=False):
    p1, p2, _, _ = resolve(t, appointment, locations, binding=binding, list_raises=list_raises)
    with p1, p2:
        return await tools._resolve_square_deposit_location(t, appointment, "tok")


# ═══════════════════════════════════════════════════════════════════════════
# Authority order
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_I_the_appointments_own_location_is_the_authority():
    """DANI multi-location + a trusted Cork appointment -> Cork, and no default."""
    got, why = await run_resolve(tenant(), appt(CORK), [loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert (got, why) == (CORK, "appointment")


@pytest.mark.asyncio
async def test_I2_a_different_location_gives_a_different_operation_location():
    got, _ = await run_resolve(tenant(), appt(DUBLIN), [loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert got == DUBLIN


@pytest.mark.asyncio
async def test_M_N_an_unverified_provider_location_is_NOT_trusted():
    """The id came from a row, but it must still be proved to belong to THIS
    tenant. Without the binding check a stale or cross-tenant id would be
    charged against."""
    got, why = await run_resolve(tenant(), appt("L-SOMEONE-ELSE"),
                                 [loc(CORK), loc(DUBLIN)], binding=False)
    assert got == "", "an unbound provider location was trusted"
    assert why == "ambiguous"


@pytest.mark.asyncio
async def test_an_unverified_location_falls_back_to_the_tenant_default():
    got, why = await run_resolve(tenant(pointer=CORK), appt("L-SOMEONE-ELSE"),
                                 [loc(CORK), loc(DUBLIN)], binding=False)
    assert (got, why) == (CORK, "tenant_default")


@pytest.mark.asyncio
async def test_A_existing_pointer_plus_one_location_is_used_and_preserved():
    got, why = await run_resolve(tenant(pointer=CORK), None, [loc(CORK)])
    assert (got, why) == (CORK, "tenant_default")


@pytest.mark.asyncio
async def test_B_existing_pointer_plus_many_locations_is_not_rewritten():
    got, why = await run_resolve(tenant(pointer=CORK), None, [loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert (got, why) == (CORK, "tenant_default")


@pytest.mark.asyncio
async def test_C_null_pointer_plus_exactly_one_usable_location_works():
    got, why = await run_resolve(tenant(), None, [loc(CORK)])
    assert (got, why) == (CORK, "single_location")


@pytest.mark.asyncio
async def test_G_one_active_one_inactive_is_a_single_location_business():
    got, why = await run_resolve(tenant(), None, [loc(CORK), loc(DUBLIN, status="INACTIVE")])
    assert (got, why) == (CORK, "single_location")


@pytest.mark.asyncio
async def test_D_H_multi_location_with_no_context_REFUSES():
    got, why = await run_resolve(tenant(), None, [loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert got == ""
    assert why == "ambiguous"


@pytest.mark.asyncio
async def test_D2_an_appointment_without_a_location_gives_no_context():
    got, why = await run_resolve(tenant(), appt(None), [loc(CORK), loc(DUBLIN)])
    assert (got, why) == ("", "ambiguous")


@pytest.mark.asyncio
async def test_E_provider_ORDER_cannot_change_the_refusal():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    results = set()
    for order in itertools.permutations(three):
        results.add(await run_resolve(tenant(), None, list(order)))
    assert results == {("", "ambiguous")}, f"order changed the answer: {results}"


@pytest.mark.asyncio
async def test_E2_order_cannot_change_which_single_location_is_chosen():
    mixed = [loc(CORK), loc(DUBLIN, status="INACTIVE"), loc(LIMERICK, status="INACTIVE")]
    results = {await run_resolve(tenant(), None, list(o)) for o in itertools.permutations(mixed)}
    assert results == {(CORK, "single_location")}


@pytest.mark.asyncio
async def test_F_zero_usable_locations_is_a_safe_refusal():
    assert await run_resolve(tenant(), None, []) == ("", "no_location")
    assert await run_resolve(tenant(), None, [loc(CORK, status="INACTIVE")]) == ("", "no_location")


@pytest.mark.asyncio
async def test_J_a_provider_list_failure_refuses_without_mutating():
    got, why = await run_resolve(tenant(), None, [], list_raises=True)
    assert (got, why) == ("", "provider_unavailable")


@pytest.mark.asyncio
async def test_a_binding_lookup_failure_does_not_trust_the_appointment():
    with patch("routers.tools._sq_list_locations", new=AsyncMock(return_value=[loc(CORK), loc(DUBLIN)])), \
         patch("db.locations.get_binding", new=AsyncMock(side_effect=RuntimeError("db down"))):
        got, why = await tools._resolve_square_deposit_location(tenant(), appt(CORK), "tok")
    assert (got, why) == ("", "ambiguous"), "a failed verification was treated as a pass"


# ═══════════════════════════════════════════════════════════════════════════
# The deposit operation end to end — no provider call, no topology write
# ═══════════════════════════════════════════════════════════════════════════

def _deposit_env(t, *, appointment=None, locations, binding=True):
    updates, links = [], []

    async def cap_update(tid, patch_):
        updates.append((tid, patch_))
        return {}

    async def cap_link(**kw):
        links.append(kw)
        return ("link-1", "order-1", "https://squareup.link/x")

    return updates, links, [
        patch("routers.payments._deposit_provider", return_value="square"),
        patch("services.security.decrypt", return_value="tok"),
        patch("db.supabase.get_payment_by_appointment_id", new=AsyncMock(return_value=None)),
        patch("db.supabase.get_appointment_by_id", new=AsyncMock(return_value=appointment)),
        patch("routers.tools._sq_list_locations", new=AsyncMock(return_value=locations)),
        patch("db.locations.get_binding", new=AsyncMock(return_value=({"id": "b1"} if binding else None))),
        patch("db.supabase.update_tenant", new=AsyncMock(side_effect=cap_update)),
        patch("services.square_service.create_payment_link", new=AsyncMock(side_effect=cap_link)),
        patch("db.supabase.insert_payment", new=AsyncMock(return_value={})),
        patch("db.supabase.get_payment_short_link_by_code", new=AsyncMock(return_value=None)),
        patch("db.supabase.create_payment_short_link", new=AsyncMock(return_value={})),
        patch("services.telephony.send_sms", new=AsyncMock(return_value=True)),
    ]


async def _deposit(t, *, appointment=None, locations, binding=True, appointment_id="a-1"):
    import contextlib
    updates, links, patches = _deposit_env(t, appointment=appointment,
                                           locations=locations, binding=binding)
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        out = await tools._create_and_send_deposit(
            t, caller_phone="+353871234567", caller_name="Aoife", service="Dress Fitting",
            appointment_id=appointment_id, amount_cents=2500)
    return out, updates, links


@pytest.mark.asyncio
async def test_H_DANI_shaped_deposit_with_no_context_creates_NOTHING():
    """The production shape this gate exists for."""
    out, updates, links = await _deposit(
        tenant(), appointment=appt(None), locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert out["error"] == "location_required"
    assert out["sms_sent"] is False
    assert links == [], "a Square payment link was created for an ambiguous location"
    assert updates == [], "the tenant topology was written"


@pytest.mark.asyncio
async def test_H2_the_refusal_is_identical_in_every_provider_ordering():
    three = [loc(CORK), loc(DUBLIN), loc(LIMERICK)]
    for order in itertools.permutations(three):
        out, updates, links = await _deposit(
            tenant(), appointment=appt(None), locations=list(order))
        assert out["error"] == "location_required"
        assert links == [] and updates == []


@pytest.mark.asyncio
async def test_I3_DANI_with_a_trusted_Cork_appointment_charges_Cork_and_writes_no_default():
    out, updates, links = await _deposit(
        tenant(), appointment=appt(CORK), locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert out["error"] is None
    assert len(links) == 1 and links[0]["location_id"] == CORK
    assert updates == [], "an operation location was persisted as a tenant default"


@pytest.mark.asyncio
async def test_I4_a_Dublin_appointment_charges_Dublin():
    out, _, links = await _deposit(
        tenant(), appointment=appt(DUBLIN), locations=[loc(CORK), loc(DUBLIN), loc(LIMERICK)])
    assert links[0]["location_id"] == DUBLIN


@pytest.mark.asyncio
async def test_R_legacy_single_location_tenant_still_works_and_settles_its_pointer():
    """Backwards compatibility: one usable location means nothing is guessed, so
    the legacy pointer repair may still happen."""
    out, updates, links = await _deposit(tenant(), appointment=appt(None), locations=[loc(CORK)])
    assert out["error"] is None
    assert links[0]["location_id"] == CORK
    assert updates == [("tenant-dani", {"square_location_id": CORK})]


@pytest.mark.asyncio
async def test_R2_a_tenant_with_an_existing_pointer_is_never_rewritten():
    out, updates, links = await _deposit(
        tenant(pointer=CORK), appointment=appt(None),
        locations=[loc(DUBLIN), loc(CORK), loc(LIMERICK)])
    assert links[0]["location_id"] == CORK
    assert updates == [], "an existing pointer was rewritten by a deposit"


@pytest.mark.asyncio
async def test_L_a_square_link_failure_produces_no_false_local_success():
    import contextlib
    _, _, patches = _deposit_env(tenant(pointer=CORK), appointment=appt(None), locations=[loc(CORK)])
    patches = [p for p in patches if "create_payment_link" not in str(p)]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        stack.enter_context(patch("services.square_service.create_payment_link",
                                  new=AsyncMock(side_effect=RuntimeError("square 500"))))
        out = await tools._create_and_send_deposit(
            tenant(pointer=CORK), caller_phone="+353871234567", caller_name="A",
            service="S", appointment_id="a-1", amount_cents=2500)
    assert out["error"] == "exception"
    assert out["sms_sent"] is False


@pytest.mark.asyncio
async def test_K_no_provider_configured_is_unchanged():
    with patch("routers.payments._deposit_provider", return_value=""):
        out = await tools._create_and_send_deposit(
            tenant(), caller_phone="+1", caller_name="A", service="S",
            appointment_id=None, amount_cents=2500)
    assert out["error"] == "no_provider"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 10 — static invariants
# ═══════════════════════════════════════════════════════════════════════════

def test_1_no_executable_locs_index_zero_in_the_deposit_path():
    for fn in (tools._create_and_send_deposit, tools._resolve_square_deposit_location):
        code = _executable_source(fn)
        assert "locs[0]" not in code and "locations[0]" not in code, fn.__name__


def test_2_5_an_operation_location_is_never_persisted_as_a_default():
    """The only update_tenant on this path sits behind the single-location
    branch, where there is nothing to guess."""
    code = _executable_source(tools._create_and_send_deposit)
    assert code.count("update_tenant") == 1
    guarded = code.split("_why == 'single_location'")[1]
    assert "update_tenant" in guarded, "the pointer write escaped its guard"


def test_3_4_ambiguity_reaches_no_provider_and_no_write():
    code = _executable_source(tools._create_and_send_deposit)
    head = code[:code.index("create_payment_link")]
    assert "out['error'] = " in head and "return out" in head, \
        "the refusal does not return before the provider call"


def test_6_7_the_W7E1_policy_is_reused_not_reimplemented():
    code = _executable_source(tools._resolve_square_deposit_location)
    assert "location_sync.choose_legacy_default_square_location" in code
    assert "location_sync.usable_square_locations" in code


def test_the_appointment_location_is_always_verified_before_use():
    code = _executable_source(tools._resolve_square_deposit_location)
    assert "db_loc.get_binding" in code
    assert code.index("db_loc.get_binding") < code.index("'appointment'")


def test_9_W7E_and_W7E1_are_unchanged():
    from services import square_catalog_routing as w7e
    assert ".limit(1)" not in _executable_source(w7e)
    assert "len(usable) == 1" in _executable_source(ls.choose_legacy_default_square_location)
    assert "locations[0]" not in _executable_source(ls)


def test_10_11_booking_and_payment_webhooks_unchanged():
    from routers import payments
    src = inspect.getsource(payments.square_webhook)
    assert "square_booking_reconcile.reconcile_booking_event(" in src
    assert '"payment.updated" | "payment.created"' in src
    assert "_w7e.route_catalog_event(event)" in src


def test_12_W7T_untouched():
    from db import supabase_transport
    import db.supabase as dbs
    assert "http2" in inspect.getsource(supabase_transport.http2_enabled)
    assert "supabase_transport.install()" in inspect.getsource(dbs.get_client)


def test_O_P_Q_the_deposit_guard_did_not_reach_into_other_paths():
    code = _executable_source(tools._resolve_square_deposit_location)
    for forbidden in ("reconcile_booking_event", "route_catalog_event",
                      "insert_appointment", "cancel_booking", "create_booking"):
        assert forbidden not in code
