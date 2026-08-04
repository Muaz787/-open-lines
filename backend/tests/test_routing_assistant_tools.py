"""Assistant tool-wiring: routing tools attach only for entitled tenants, and the
native transferCall attaches only when transfer execution is enabled."""
import pytest

from services import vapi


PRO = {"id": "t1", "subscription_plan": "pro", "subscription_status": "active", "routing_enabled": True}
STARTER = {"id": "t2", "subscription_plan": "starter", "subscription_status": "active", "routing_enabled": True}


def _names(tools):
    return [t.get("function", {}).get("name") or t.get("type") for t in tools]


def test_dark_when_master_off(monkeypatch):
    monkeypatch.delenv("ROUTING_ENABLED", raising=False)
    assert vapi.build_routing_tools(PRO) == []


def test_starter_gets_no_routing_tools(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    assert vapi.build_routing_tools(STARTER) == []


def test_decision_tools_without_transfer_execution(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.delenv("ROUTING_TRANSFER_ENABLED", raising=False)
    names = _names(vapi.build_routing_tools(PRO))
    assert "classify_and_route" in names and "create_callback" in names
    assert "transferCall" not in names          # transfer stays off


def test_transfer_tool_attaches_when_execution_enabled(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setenv("ROUTING_TRANSFER_ENABLED", "true")
    tools = vapi.build_routing_tools(PRO)
    names = _names(tools)
    assert "transferCall" in names
    tc = next(t for t in tools if t.get("type") == "transferCall")
    # Vapi compatibility: empty destinations (server supplies the number dynamically)
    # and NO tool-level transferPlan (the TransferCallTool schema rejects it -> 400).
    assert tc["destinations"] == []
    assert "transferPlan" not in tc


def test_transfer_tool_has_only_schema_valid_keys(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setenv("ROUTING_TRANSFER_ENABLED", "true")
    tc = vapi.build_transfer_call_tool()
    # TransferCallTool accepts only {type, destinations, messages, rejectionPlan}.
    assert set(tc.keys()) <= {"type", "destinations", "messages", "rejectionPlan"}
    assert tc["type"] == "transferCall"


def test_routing_server_messages_are_schema_valid():
    # Exactly the two currently valid, required routing server messages — and no
    # `assistant-request` (not a member of the assistant serverMessages enum -> 400).
    assert vapi.ROUTING_SERVER_MESSAGES == ["transfer-destination-request", "end-of-call-report"]
    assert "assistant-request" not in vapi.ROUTING_SERVER_MESSAGES


def test_tool_server_urls_point_to_routing_endpoints(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    tools = vapi.build_routing_tools(PRO)
    urls = [t.get("server", {}).get("url", "") for t in tools if "server" in t]
    assert any(u.endswith("/tools/t1/classify-and-route") for u in urls)
    assert any(u.endswith("/tools/t1/create-callback") for u in urls)


def test_build_all_tools_includes_routing_when_entitled(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    names = _names(vapi.build_all_tools(PRO))
    assert "classify_and_route" in names
    # starter tenant: no routing tools mixed in
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    assert "classify_and_route" not in _names(vapi.build_all_tools(STARTER))
