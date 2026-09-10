"""
Which Square events may rewrite a tenant's service and team caches.

The distinction that matters: an UNSOLICITED provider event must not touch a
tenant that does not book through Square, while the EXPLICIT paths — the manual
sync endpoint and the OAuth callback — must still work before appointments are
enabled, because a merchant has to connect and preview a catalog before switching
booking on.

Written after a real incident: a catalog edit on a shared test merchant fired
catalog.version.updated, and the ungated handler wrote that merchant's services
and staff into a live tenant with Square booking switched off.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import square_booking as sb

MERCHANT = "ML66K1YVCD1P0"


def _tenant(appointments_enabled=False, **over):
    return {"id": "t-1", "business_name": "Acme",
            "square_access_token": "enc-token",
            "square_appointments_enabled": appointments_enabled,
            "square_location_id": "L1", **over}


def _event(kind="catalog"):
    if kind == "catalog":
        return {"merchant_id": MERCHANT, "type": "catalog.version.updated"}
    return {"merchant_id": MERCHANT, "type": "booking.created",
            "data": {"object": {"booking": {"id": "bk-1", "status": "ACCEPTED"}}}}


# ── 1 & 2. the catalog webhook gate ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_catalog_webhook_does_not_sync_when_appointments_disabled():
    with patch("db.supabase.get_tenant_by_square_merchant_id",
               new=AsyncMock(return_value=_tenant(appointments_enabled=False))), \
         patch("services.square_booking.sync", new=AsyncMock()) as sync:
        await sb.handle_catalog_update(_event())
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalog_webhook_syncs_when_appointments_enabled():
    with patch("db.supabase.get_tenant_by_square_merchant_id",
               new=AsyncMock(return_value=_tenant(appointments_enabled=True))), \
         patch("services.square_booking.sync", new=AsyncMock()) as sync:
        await sb.handle_catalog_update(_event())
    sync.assert_awaited_once_with("t-1")


@pytest.mark.asyncio
async def test_catalog_webhook_ignores_an_unknown_or_disconnected_merchant():
    for tenant in (None, _tenant(appointments_enabled=True, square_access_token=None)):
        with patch("db.supabase.get_tenant_by_square_merchant_id",
                   new=AsyncMock(return_value=tenant)), \
             patch("services.square_booking.sync", new=AsyncMock()) as sync:
            await sb.handle_catalog_update(_event())
        sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_incident_cannot_recur():
    """A live tenant connected to a shared merchant, Square booking off. A catalog
    edit by anyone must leave its caches alone."""
    shahid = _tenant(appointments_enabled=False, id="a85ba5cf", business_name="Shahid Real Estate")
    with patch("db.supabase.get_tenant_by_square_merchant_id",
               new=AsyncMock(return_value=shahid)), \
         patch("db.supabase.replace_square_services", new=AsyncMock()) as svc, \
         patch("db.supabase.replace_square_staff", new=AsyncMock()) as stf, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        await sb.handle_catalog_update(_event())
    svc.assert_not_awaited()
    stf.assert_not_awaited()
    upd.assert_not_awaited()


# ── 3 & 4. the explicit paths keep working ───────────────────────────────────

def _patch_sync_internals(tenant):
    """Everything sync() reaches out to, stubbed."""
    return {
        "db.supabase.get_tenant_by_id": AsyncMock(return_value=tenant),
        "services.square_booking.get_access_token": AsyncMock(return_value="tok"),
        "services.square_service.list_locations": AsyncMock(
            return_value=[{"id": "L1", "name": "Main", "timezone": "America/Toronto"}]),
        "services.square_booking.retrieve_booking_profile": AsyncMock(
            return_value={"booking_enabled": True}),
        "services.square_booking.list_services": AsyncMock(
            return_value=[{"square_variation_id": "V1", "name": "Cut"}]),
        "services.square_booking.list_team_members": AsyncMock(
            return_value=[{"square_team_member_id": "TM1", "display_name": "Sam"}]),
        "services.location_sync.sync_square_locations": AsyncMock(return_value={}),
        "db.supabase.replace_square_services": AsyncMock(),
        "db.supabase.replace_square_staff": AsyncMock(),
        "db.supabase.update_tenant": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_explicit_sync_still_works_with_appointments_disabled():
    """The manual endpoint and the OAuth callback both call sync() directly. A
    merchant must be able to connect and preview its catalog before enabling
    booking — gating sync() itself would break onboarding."""
    mocks = _patch_sync_internals(_tenant(appointments_enabled=False))
    patchers = [patch(target, new=m) for target, m in mocks.items()]
    for p in patchers:
        p.start()
    try:
        out = await sb.sync("t-1")
    finally:
        for p in patchers:
            p.stop()

    assert out["ok"] is True
    mocks["db.supabase.replace_square_services"].assert_awaited_once()
    mocks["db.supabase.replace_square_staff"].assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_itself_has_no_appointments_gate():
    """Structural: the gate belongs on the webhook handler, not on sync()."""
    import inspect
    src = inspect.getsource(sb.sync)
    assert "square_appointments_enabled" not in src


@pytest.mark.asyncio
async def test_oauth_callback_still_delegates_to_sync_unchanged():
    from routers import square_connect
    import inspect
    src = inspect.getsource(square_connect)
    assert "square_booking.sync(tenant_id)" in src          # OAuth background task
    assert "await square_booking.sync(tenant_id)" in src    # explicit endpoint


# ── 5. the booking guard is untouched ────────────────────────────────────────

@pytest.mark.asyncio
async def test_booking_webhook_guard_unchanged():
    with patch("db.supabase.get_tenant_by_square_merchant_id",
               new=AsyncMock(return_value=_tenant(appointments_enabled=False))), \
         patch("db.supabase.get_appointment_by_event_id", new=AsyncMock()) as lookup:
        await sb.handle_booking_event(_event("booking"))
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_booking_webhook_proceeds_when_enabled():
    with patch("db.supabase.get_tenant_by_square_merchant_id",
               new=AsyncMock(return_value=_tenant(appointments_enabled=True))), \
         patch("db.supabase.get_appointment_by_event_id",
               new=AsyncMock(return_value=None)) as lookup, \
         patch("db.supabase.get_square_services", new=AsyncMock(return_value=[])), \
         patch("db.supabase.get_square_staff", new=AsyncMock(return_value=[])), \
         patch("services.square_booking.get_access_token", new=AsyncMock(return_value=None)), \
         patch("db.supabase.insert_appointment", new=AsyncMock()):
        await sb.handle_booking_event(_event("booking"))
    lookup.assert_awaited()


def test_both_webhook_handlers_gate_on_the_same_flag():
    """The two handlers drifted apart once and it cost a production write. If a
    third provider event is added, it should fail this test until it gates too."""
    import inspect
    for fn in (sb.handle_catalog_update, sb.handle_booking_event):
        assert "square_appointments_enabled" in inspect.getsource(fn), \
            f"{fn.__name__} must gate on square_appointments_enabled"
