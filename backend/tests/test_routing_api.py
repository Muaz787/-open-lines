"""Owner routing API handlers: entitlement gate, per-plan limits, loop/dedup
guards, and masked output. Handlers are called directly (router-level owner auth
is the shared, separately-tested dependency)."""
import pytest
from unittest.mock import AsyncMock

from fastapi import HTTPException

from routers import routing as rr
from routers.routing import DestinationCreate, RuleCreate, SimulateRequest, ProfileUpdate

PRO_TENANT = {
    "id": "t1", "subscription_plan": "pro", "subscription_status": "active",
    "routing_enabled": True, "twilio_phone_number": "+14380000000",
}


@pytest.fixture(autouse=True)
def base(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    monkeypatch.setenv("ROUTING_HASH_PEPPER", "pepper")
    monkeypatch.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value=dict(PRO_TENANT)))
    # avoid crypto: stub the encrypt+mask+hash builder
    monkeypatch.setattr(rr.rd, "secure_fields", lambda n: {
        "e164_encrypted": "ENC", "e164_masked": "+1•••1234", "e164_hash": "H", "country": "NANP"})
    yield monkeypatch


@pytest.mark.asyncio
async def test_gate_denies_starter(base):
    base.setattr(rr.db, "get_tenant_by_id", AsyncMock(return_value={
        "id": "t1", "subscription_plan": "starter", "subscription_status": "active", "routing_enabled": True}))
    with pytest.raises(HTTPException) as e:
        await rr.get_profile("t1")
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_denies_when_master_off(base):
    base.delenv("ROUTING_ENABLED", raising=False)          # dark launch off
    with pytest.raises(HTTPException) as e:
        await rr.get_profile("t1")
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_destination_limit_enforced(base):
    # pro max_destinations = 2; already two active
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[
        {"id": "d1", "enabled": True}, {"id": "d2", "enabled": True}]))
    with pytest.raises(HTTPException) as e:
        await rr.create_destination("t1", DestinationCreate(number="+16475551234"))
    assert e.value.status_code == 403 and "limit" in e.value.detail.lower()


@pytest.mark.asyncio
async def test_loop_guard_rejects_own_line(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as e:
        await rr.create_destination("t1", DestinationCreate(number="+14380000000"))  # == own line
    assert e.value.status_code == 400 and "loop" in e.value.detail.lower()


@pytest.mark.asyncio
async def test_emergency_number_rejected(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as e:
        await rr.create_destination("t1", DestinationCreate(number="911"))
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_destination_rejected(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[]))
    base.setattr(rr.rdb, "find_destination_by_hash", AsyncMock(return_value={"id": "dupe"}))
    with pytest.raises(HTTPException) as e:
        await rr.create_destination("t1", DestinationCreate(number="+16475551234"))
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_create_destination_masked_never_leaks_encrypted(base):
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[]))
    base.setattr(rr.rdb, "find_destination_by_hash", AsyncMock(return_value=None))
    base.setattr(rr.rdb, "create_destination", AsyncMock(return_value={
        "id": "d1", "type": "phone", "label": None, "e164_masked": "+1•••1234",
        "e164_encrypted": "ENC", "e164_hash": "H", "enabled": True}))
    out = await rr.create_destination("t1", DestinationCreate(number="+16475551234", label="Front desk"))
    assert out["number_masked"] == "+1•••1234"
    assert "e164_encrypted" not in out and "ENC" not in str(out)
    assert "e164_hash" not in out


@pytest.mark.asyncio
async def test_rule_limit_enforced(base):
    base.setattr(rr.rdb, "count_rules", AsyncMock(return_value=5))   # pro cap = 5
    with pytest.raises(HTTPException) as e:
        await rr.create_rule("t1", RuleCreate(profile_id="p1", destination_id=None))
    assert e.value.status_code == 403 and "limit" in e.value.detail.lower()


@pytest.mark.asyncio
async def test_rule_rejects_foreign_destination(base):
    base.setattr(rr.rdb, "count_rules", AsyncMock(return_value=0))
    base.setattr(rr.rdb, "get_destination", AsyncMock(return_value=None))   # not this tenant's
    with pytest.raises(HTTPException) as e:
        await rr.create_rule("t1", RuleCreate(profile_id="p1", destination_id="d_other"))
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_put_profile_empty_returns_existing_without_update(base):
    # Regression: an empty PUT (the "ensure a profile exists" call) must return the
    # existing profile as-is, never do an empty UPDATE (which returned no row and
    # blanked the client's default/urgent destinations + broke rule creation).
    base.setattr(rr.rdb, "get_profile", AsyncMock(return_value={"id": "p1", "mode": "ai_first",
                 "default_destination_id": "reg"}))
    upd = AsyncMock()
    base.setattr(rr.rdb, "update_profile", upd)
    out = await rr.put_profile("t1", ProfileUpdate())
    assert out["id"] == "p1" and out["default_destination_id"] == "reg"
    upd.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_profile_with_fields_updates(base):
    base.setattr(rr.rdb, "get_profile", AsyncMock(return_value={"id": "p1"}))
    base.setattr(rr.rdb, "update_profile", AsyncMock(return_value={"id": "p1", "default_destination_id": "reg"}))
    out = await rr.put_profile("t1", ProfileUpdate(default_destination_id="reg"))
    assert out["default_destination_id"] == "reg"


@pytest.mark.asyncio
async def test_simulate_returns_decision_with_masked_destination(base):
    base.setattr(rr.rdb, "get_profile", AsyncMock(return_value={
        "id": "p1", "default_destination_id": "reg", "urgent_destination_id": "urgent"}))
    base.setattr(rr.rdb, "list_rules", AsyncMock(return_value=[
        {"id": "r1", "priority": 1, "match": {"intent": "sales"}, "destination_id": "reg"}]))
    base.setattr(rr.rdb, "list_destinations", AsyncMock(return_value=[
        {"id": "reg", "type": "phone", "enabled": True}]))
    base.setattr(rr.rdb, "get_destination", AsyncMock(return_value={
        "id": "reg", "type": "phone", "e164_masked": "+1•••1111", "e164_encrypted": "X"}))
    out = await rr.simulate("t1", SimulateRequest(intent="sales", confidence=0.9))
    assert out["decision"] == "transfer" and out["destination_id"] == "reg"
    assert out["destination"]["number_masked"] == "+1•••1111"
    assert "e164_encrypted" not in out["destination"]
