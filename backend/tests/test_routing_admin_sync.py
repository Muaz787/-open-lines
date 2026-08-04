"""Admin sync-assistant endpoint: a provider (Vapi) rejection is surfaced as a
controlled 502, never an opaque 500 that leaks the raw upstream response."""
import pytest
import httpx
from unittest.mock import AsyncMock

from fastapi import HTTPException

from routers import routing as rr
from services import vapi as vapi_svc

TENANT = {"id": "t1", "vapi_assistant_id": "asst_123"}


@pytest.fixture(autouse=True)
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    monkeypatch.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value=dict(TENANT)))
    yield monkeypatch


def _http_status_error(status: int, body: str) -> httpx.HTTPStatusError:
    req = httpx.Request("PATCH", "https://api.vapi.ai/assistant/asst_123")
    resp = httpx.Response(status, text=body, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


@pytest.mark.asyncio
async def test_provider_400_becomes_controlled_502(admin):
    admin.setattr(vapi_svc, "patch_assistant_tools",
                  AsyncMock(side_effect=_http_status_error(400, "invalid transferPlan")))
    with pytest.raises(HTTPException) as e:
        await rr.admin_sync_assistant("t1", x_admin_key="secret-admin")
    assert e.value.status_code == 502
    # controlled message — the raw provider body is NOT echoed to the caller
    assert "invalid transferPlan" not in str(e.value.detail)


@pytest.mark.asyncio
async def test_provider_network_error_becomes_502(admin):
    admin.setattr(vapi_svc, "patch_assistant_tools",
                  AsyncMock(side_effect=httpx.ConnectError("boom")))
    with pytest.raises(HTTPException) as e:
        await rr.admin_sync_assistant("t1", x_admin_key="secret-admin")
    assert e.value.status_code == 502


@pytest.mark.asyncio
async def test_success_returns_synced(admin):
    admin.setattr(vapi_svc, "patch_assistant_tools", AsyncMock(return_value=None))
    out = await rr.admin_sync_assistant("t1", x_admin_key="secret-admin")
    assert out["status"] == "assistant synced" and out["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_bad_admin_key_forbidden(admin):
    with pytest.raises(HTTPException) as e:
        await rr.admin_sync_assistant("t1", x_admin_key="wrong")
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_missing_assistant_404(admin):
    admin.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value={"id": "t1"}))
    with pytest.raises(HTTPException) as e:
        await rr.admin_sync_assistant("t1", x_admin_key="secret-admin")
    assert e.value.status_code == 404
