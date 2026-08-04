"""What patch_assistant_tools actually PATCHes to Vapi in the two rollout states
(the sync checks): transfer-DISABLED sync vs transfer-ENABLED sync. Also the
provider-error log sanitizer."""
import pytest
from unittest.mock import AsyncMock

from services import vapi

PRO = {
    "id": "t1", "subscription_plan": "pro", "subscription_status": "active",
    "routing_enabled": True, "vapi_assistant_id": "asst_1",
    "twilio_phone_number": "+14380000000",
}
CURRENT_ASSISTANT = {"model": {"messages": [{"role": "system", "content": "You are a receptionist."}]}}


async def _capture_sync_payload(monkeypatch, tenant):
    """Run patch_assistant_tools with Vapi network calls stubbed, returning the
    exact PATCH payload that would be sent to the provider."""
    monkeypatch.setattr(vapi, "get_assistant", AsyncMock(return_value=dict(CURRENT_ASSISTANT)))
    captured = {}

    async def _upd(assistant_id, payload, api_key=None):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(vapi, "update_assistant", _upd)
    await vapi.patch_assistant_tools(tenant)
    return captured["payload"]


def _tool_names(payload):
    return [t.get("function", {}).get("name") or t.get("type") for t in payload["model"]["tools"]]


@pytest.mark.asyncio
async def test_transfer_disabled_sync_payload(monkeypatch):
    # First sync check: ROUTING_ENABLED on, transfer execution OFF.
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.delenv("ROUTING_TRANSFER_ENABLED", raising=False)
    payload = await _capture_sync_payload(monkeypatch, dict(PRO))
    names = _tool_names(payload)
    # decision tools present; transferCall NOT attached
    assert "classify_and_route" in names and "create_callback" in names
    assert "transferCall" not in names
    # corrected, schema-valid serverMessages (no assistant-request)
    assert payload["serverMessages"] == ["transfer-destination-request", "end-of-call-report"]
    assert "assistant-request" not in payload["serverMessages"]


@pytest.mark.asyncio
async def test_transfer_enabled_sync_payload(monkeypatch):
    # Second sync check: transfer execution ON — corrected transferCall now attached.
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setenv("ROUTING_TRANSFER_ENABLED", "true")
    payload = await _capture_sync_payload(monkeypatch, dict(PRO))
    tools = payload["model"]["tools"]
    assert "transferCall" in _tool_names(payload)
    tc = next(t for t in tools if t.get("type") == "transferCall")
    # empty destinations (server supplies number dynamically) + NO tool-level transferPlan
    assert tc["destinations"] == []
    assert "transferPlan" not in tc
    # only schema-valid keys on the tool
    assert set(tc.keys()) <= {"type", "destinations", "messages", "rejectionPlan"}
    assert payload["serverMessages"] == ["transfer-destination-request", "end-of-call-report"]


@pytest.mark.asyncio
async def test_non_routing_tenant_sync_sets_no_routing_server_messages(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    starter = {**PRO, "subscription_plan": "starter"}
    payload = await _capture_sync_payload(monkeypatch, starter)
    assert "classify_and_route" not in _tool_names(payload)
    assert "serverMessages" not in payload   # untouched for non-routing assistants


# ── provider-error log sanitizer ────────────────────────────────────────────
def test_redact_scrubs_credentials_and_phone():
    raw = ('{"authorization":"Bearer sk-secret-abc123","x-vapi-secret":"topsecretvalue",'
           '"message":"transfer to +14375551234 failed, call 416-555-0100"}')
    out = vapi.redact_provider_error(raw)
    assert "sk-secret-abc123" not in out
    assert "topsecretvalue" not in out
    assert "+14375551234" not in out and "416-555-0100" not in out
    assert "[REDACTED_PHONE]" in out


def test_redact_truncates_long_bodies():
    out = vapi.redact_provider_error("x" * 5000, limit=500)
    assert len(out) <= 540 and "truncated" in out


def test_redact_handles_empty():
    assert vapi.redact_provider_error(None) == ""
    assert vapi.redact_provider_error("") == ""
