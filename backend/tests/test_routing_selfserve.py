"""Self-serve GA: Pro/Business can CONFIGURE routing before opting in (plan-gated),
and opting in (activate) is what turns it on for their calls (opt-in-gated runtime)."""
import pytest
import httpx
from unittest.mock import AsyncMock
from fastapi import HTTPException

from routers import routing as rr
from services import entitlements as ent
from services import vapi as vapi_svc


# ── entitlements: config access (plan) vs active (opt-in) ────────────────────
def test_can_configure_pro_without_optin(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    t = {"subscription_plan": "pro", "subscription_status": "active", "routing_enabled": False}
    assert ent.can_configure(t) is True          # can set it up
    assert ent.has_feature(t, "routing") is False  # but NOT active on calls yet
    assert ent.config_limit_for(t, "max_destinations") == 2
    assert ent.config_limit_for(t, "max_routing_rules") == 5


def test_business_config_caps(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    t = {"subscription_plan": "business", "subscription_status": "active", "routing_enabled": False}
    assert ent.config_limit_for(t, "max_destinations") == 50
    assert ent.config_limit_for(t, "max_routing_rules") == 50


def test_can_configure_false_for_starter(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    assert ent.can_configure({"subscription_plan": "starter", "subscription_status": "active"}) is False


def test_can_configure_false_when_master_off(monkeypatch):
    monkeypatch.delenv("ROUTING_ENABLED", raising=False)
    assert ent.can_configure(
        {"subscription_plan": "pro", "subscription_status": "active", "routing_enabled": True}) is False


def test_build_routing_tools_empty_until_activated(monkeypatch):
    # Runtime stays opt-in-gated: a Pro tenant that can configure but hasn't activated
    # gets NO routing tools on their calls.
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    t = {"id": "t1", "subscription_plan": "pro", "subscription_status": "active", "routing_enabled": False}
    assert vapi_svc.build_routing_tools(t) == []


# ── owner API: config surface + self-serve activation ────────────────────────
PRO_OFF = {"id": "t1", "subscription_plan": "pro", "subscription_status": "active",
           "routing_enabled": False, "twilio_phone_number": "+14380000000", "vapi_assistant_id": "a1"}


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value=dict(PRO_OFF)))
    yield monkeypatch


@pytest.mark.asyncio
async def test_config_accessible_before_optin(base):
    base.setattr(rr.rdb, "get_profile", AsyncMock(return_value={"id": "p1", "mode": "ai_first"}))
    out = await rr.get_profile("t1")   # would have 403'd under the old opt-in gate
    assert out["id"] == "p1"


@pytest.mark.asyncio
async def test_status_reports_inactive_but_can_activate(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[{"id": "d1", "enabled": True}]))
    out = await rr.get_status("t1")
    assert out["routing_active"] is False           # not opted in
    assert out["can_activate"] is True and out["active_destination_count"] == 1
    assert out["tier"] == "pro" and out["max_destinations"] == 2


@pytest.mark.asyncio
async def test_activate_requires_a_destination(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as e:
        await rr.activate_routing("t1")
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_activate_sets_flag_and_syncs(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[{"id": "d1", "enabled": True}]))
    setflag = AsyncMock()
    base.setattr(rr.rdb, "set_routing_enabled", setflag)
    base.setattr(vapi_svc, "patch_assistant_tools", AsyncMock())
    out = await rr.activate_routing("t1")
    assert out == {"routing_active": True, "assistant_synced": True}
    setflag.assert_awaited_once_with("t1", True)


@pytest.mark.asyncio
async def test_activate_soft_warns_when_sync_fails(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[{"id": "d1", "enabled": True}]))
    base.setattr(rr.rdb, "set_routing_enabled", AsyncMock())
    req = httpx.Request("PATCH", "https://api.vapi.ai/assistant/a1")
    resp = httpx.Response(400, text="bad", request=req)
    base.setattr(vapi_svc, "patch_assistant_tools",
                 AsyncMock(side_effect=httpx.HTTPStatusError("400", request=req, response=resp)))
    out = await rr.activate_routing("t1")
    # routing is still ON (DB is source of truth; per-call override re-attaches tools)
    assert out["routing_active"] is True and out["assistant_synced"] is False


@pytest.mark.asyncio
async def test_deactivate_clears_flag(base):
    setflag = AsyncMock()
    base.setattr(rr.rdb, "set_routing_enabled", setflag)
    base.setattr(vapi_svc, "patch_assistant_tools", AsyncMock())
    out = await rr.deactivate_routing("t1")
    assert out["routing_active"] is False
    setflag.assert_awaited_once_with("t1", False)


@pytest.mark.asyncio
async def test_starter_still_locked(base):
    base.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value={
        "id": "t1", "subscription_plan": "starter", "subscription_status": "active"}))
    with pytest.raises(HTTPException) as e:
        await rr.get_status("t1")
    assert e.value.status_code == 403
