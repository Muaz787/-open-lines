"""transfer-destination-request handler: flag gating, decision resolution, attempt
recording, loop guard, and safe decline (never a phone number to the AI)."""
import pytest
from unittest.mock import AsyncMock

from routers import webhooks as wh

TENANT = {"id": "t1", "subscription_plan": "pro", "subscription_status": "active",
          "routing_enabled": True, "twilio_phone_number": "+14380000000"}


def _msg(call_id="call1", line="+14380000000"):
    return {"phoneNumber": {"number": line}, "call": {"id": call_id}}


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setenv("ROUTING_TRANSFER_ENABLED", "true")
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper")
    monkeypatch.setattr(wh.db, "get_tenant_by_phone", AsyncMock(return_value=dict(TENANT)))
    monkeypatch.setattr(wh.rdb, "get_latest_transfer_decision",
                        AsyncMock(return_value={"decision": "transfer", "chosen_destination_id": "reg"}))
    monkeypatch.setattr(wh.rdb, "get_destination",
                        AsyncMock(return_value={"id": "reg", "enabled": True, "e164_encrypted": "ENC"}))
    monkeypatch.setattr(wh.rdb, "record_transfer_attempt", AsyncMock(return_value={"id": "a1"}))
    monkeypatch.setattr(wh.rd, "reveal", lambda enc: "+16475551234")   # decrypt -> a non-own number
    yield monkeypatch


@pytest.mark.asyncio
async def test_flag_off_declines(base):
    base.delenv("ROUTING_TRANSFER_ENABLED", raising=False)
    out = await wh._handle_transfer_destination_request(_msg())
    assert out == {"error": "transfer_unavailable"}
    wh.rdb.record_transfer_attempt.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_destination_and_records_attempt(base):
    out = await wh._handle_transfer_destination_request(_msg())
    assert out["destination"]["number"] == "+16475551234"
    assert out["destination"]["transferPlan"]["sipVerb"] == "dial"      # metered-mode-only
    wh.rdb.record_transfer_attempt.assert_awaited_once()
    rec = wh.rdb.record_transfer_attempt.await_args.args[0]
    assert rec["vapi_call_id"] == "call1" and rec["destination_id"] == "reg" and rec["mode"] == "warm"


@pytest.mark.asyncio
async def test_no_decision_declines(base):
    base.setattr(wh.rdb, "get_latest_transfer_decision", AsyncMock(return_value=None))
    out = await wh._handle_transfer_destination_request(_msg())
    assert out == {"error": "transfer_unavailable"}


@pytest.mark.asyncio
async def test_disabled_destination_declines(base):
    base.setattr(wh.rdb, "get_destination",
                 AsyncMock(return_value={"id": "reg", "enabled": False, "e164_encrypted": "ENC"}))
    out = await wh._handle_transfer_destination_request(_msg())
    assert out == {"error": "transfer_unavailable"}


@pytest.mark.asyncio
async def test_loop_guard_declines_own_line(base):
    base.setattr(wh.rd, "reveal", lambda enc: "+14380000000")           # == tenant's own line
    out = await wh._handle_transfer_destination_request(_msg())
    assert out == {"error": "transfer_unavailable"}
    wh.rdb.record_transfer_attempt.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_entitled_declines(base):
    base.setattr(wh.db, "get_tenant_by_phone", AsyncMock(return_value={
        "id": "t1", "subscription_plan": "starter", "subscription_status": "active", "routing_enabled": True}))
    out = await wh._handle_transfer_destination_request(_msg())
    assert out == {"error": "transfer_unavailable"}
