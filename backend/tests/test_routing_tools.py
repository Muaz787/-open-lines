"""Mid-call routing tools: decision -> AI directive, transfer-execution gating,
audit recording, and callback creation. Logic helpers are called directly."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from routers import tools

PRO_TENANT = {"id": "t1", "subscription_plan": "pro", "subscription_status": "active",
              "routing_enabled": True, "twilio_phone_number": "+14380000000"}


def _body(name, args, caller="+16475551234", call_id="call1"):
    return {"message": {
        "toolCallList": [{"id": "tc1", "function": {"name": name, "arguments": json.dumps(args)}}],
        "call": {"id": call_id, "customer": {"number": caller}},
    }}


def _text(res):
    return res["results"][0]["result"]


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.delenv("ROUTING_TRANSFER_ENABLED", raising=False)   # execution off by default
    monkeypatch.setattr(tools.db, "get_tenant_by_id", AsyncMock(return_value=dict(PRO_TENANT)))
    monkeypatch.setattr(tools.db, "get_lead_by_phone", AsyncMock(return_value=None))
    monkeypatch.setattr(tools.rdb, "get_profile", AsyncMock(return_value={
        "id": "p1", "default_destination_id": "reg", "confidence_threshold": 0.6}))
    monkeypatch.setattr(tools.rdb, "list_rules", AsyncMock(return_value=[]))
    monkeypatch.setattr(tools.rdb, "list_destinations", AsyncMock(return_value=[
        {"id": "reg", "type": "phone", "enabled": True}]))
    monkeypatch.setattr(tools.rdb, "insert_routing_decision", AsyncMock(return_value={"id": "dec1"}))
    monkeypatch.setattr(tools.rdb, "create_callback", AsyncMock(return_value={"id": "cb1"}))
    monkeypatch.setattr(tools.analytics, "capture", MagicMock())
    yield monkeypatch


@pytest.mark.asyncio
async def test_not_entitled_just_handles(base):
    base.setattr(tools.db, "get_tenant_by_id", AsyncMock(return_value={
        "id": "t1", "subscription_plan": "starter", "subscription_status": "active", "routing_enabled": True}))
    res = await tools._do_classify_and_route("t1", _body("classify_and_route", {"intent": "sales"}))
    assert "handle this yourself" in _text(res).lower()


@pytest.mark.asyncio
async def test_transfer_decision_degrades_to_callback_when_execution_off(base):
    # default profile -> transfer to 'reg'; execution disabled -> safe callback fallback
    res = await tools._do_classify_and_route("t1", _body("classify_and_route", {"intent": "sales", "confidence": 0.9}))
    assert "call them back" in _text(res).lower()
    tools.rdb.insert_routing_decision.assert_awaited()          # decision still recorded
    rec = tools.rdb.insert_routing_decision.await_args.args[0]
    assert rec["decision"] == "transfer" and rec["chosen_destination_id"] == "reg"


@pytest.mark.asyncio
async def test_transfer_executes_when_enabled(base):
    base.setenv("ROUTING_TRANSFER_ENABLED", "true")
    res = await tools._do_classify_and_route("t1", _body("classify_and_route", {"intent": "sales", "confidence": 0.9}))
    assert "connecting them to the team" in _text(res).lower()


@pytest.mark.asyncio
async def test_public_emergency_never_transfers(base):
    base.setenv("ROUTING_TRANSFER_ENABLED", "true")
    res = await tools._do_classify_and_route("t1", _body("classify_and_route", {"intent": "public_emergency"}))
    assert "handle this yourself" in _text(res).lower()
    rec = tools.rdb.insert_routing_decision.await_args.args[0]
    assert rec["decision"] == "handled_ai"


@pytest.mark.asyncio
async def test_create_callback_records_and_confirms(base):
    res = await tools._do_create_callback("t1", _body("create_callback", {"caller_name": "Sam", "reason": "quote"}))
    assert "call you back" in _text(res).lower()
    tools.rdb.create_callback.assert_awaited_once()
    tid, data = tools.rdb.create_callback.await_args.args
    assert tid == "t1" and data["caller_phone"] == "+16475551234" and data["status"] == "open"


@pytest.mark.asyncio
async def test_decision_records_source(base):
    body = _body("classify_and_route", {"intent": "sales", "confidence": 0.9})
    body["message"]["call"]["forwardedFrom"] = "+15550000000"
    await tools._do_classify_and_route("t1", body)
    rec = tools.rdb.insert_routing_decision.await_args.args[0]
    assert rec["source"] == "forwarded"
