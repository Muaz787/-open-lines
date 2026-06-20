"""
Tests for Zapier foundation: API-key generation/hashing and the emit fan-out.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

from services import zapier


def test_generate_api_key_shape():
    raw, key_hash, prefix = zapier.generate_api_key()
    assert raw.startswith("ol_live_")
    assert prefix == raw[:16]
    assert key_hash == zapier.hash_api_key(raw)
    assert len(key_hash) == 64  # sha256 hex


def test_hash_api_key_deterministic():
    assert zapier.hash_api_key("ol_live_abc") == zapier.hash_api_key("ol_live_abc")
    assert zapier.hash_api_key("a") != zapier.hash_api_key("b")


def test_keys_are_unique():
    keys = {zapier.generate_api_key()[0] for _ in range(50)}
    assert len(keys) == 50


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self):
        self.post = AsyncMock()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_emit_no_subscriptions_skips_post():
    fake = _FakeClient()
    with patch("services.zapier.db.get_zapier_subscriptions", AsyncMock(return_value=[])), \
         patch("services.zapier.httpx.AsyncClient", return_value=fake):
        await zapier.emit("tenant-1", "call_completed", {"x": 1})
    fake.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_posts_to_each_subscriber():
    fake = _FakeClient()
    subs = [{"id": "s1", "target_url": "https://hooks.zapier.com/a"},
            {"id": "s2", "target_url": "https://hooks.zapier.com/b"}]
    with patch("services.zapier.db.get_zapier_subscriptions", AsyncMock(return_value=subs)), \
         patch("services.zapier.httpx.AsyncClient", return_value=fake):
        await zapier.emit("tenant-1", "deposit_paid", {"amount": 2000})
    assert fake.post.await_count == 2
    urls = {c.args[0] for c in fake.post.await_args_list}
    assert urls == {"https://hooks.zapier.com/a", "https://hooks.zapier.com/b"}


@pytest.mark.asyncio
async def test_emit_swallows_lookup_errors():
    # Must never raise into the calling flow (a call/payment must not fail).
    with patch("services.zapier.db.get_zapier_subscriptions", AsyncMock(side_effect=Exception("db down"))):
        await zapier.emit("tenant-1", "new_lead", {})  # no exception = pass


@pytest.mark.asyncio
async def test_emit_swallows_post_errors():
    fake = _FakeClient()
    fake.post.side_effect = Exception("hook down")
    subs = [{"id": "s1", "target_url": "https://hooks.zapier.com/a"}]
    with patch("services.zapier.db.get_zapier_subscriptions", AsyncMock(return_value=subs)), \
         patch("services.zapier.httpx.AsyncClient", return_value=fake):
        await zapier.emit("tenant-1", "new_lead", {})  # no exception = pass


def test_signing_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(zapier, "_SIGNING_SECRET", "")
    assert zapier._sign(b"body") is None


def test_signing_enabled_returns_sha256(monkeypatch):
    monkeypatch.setattr(zapier, "_SIGNING_SECRET", "secret")
    sig = zapier._sign(b"body")
    assert sig and sig.startswith("sha256=")


def test_every_event_has_a_sample():
    # Zapier needs sample data for field mapping on every trigger.
    for event in zapier.EVENTS:
        assert event in zapier.SAMPLES, f"missing sample for {event}"
        assert isinstance(zapier.SAMPLES[event], dict) and zapier.SAMPLES[event]


# ---------------------------------------------------------------------------
# Actions / search endpoints
# ---------------------------------------------------------------------------

TENANT = {
    "id": "t-1", "business_name": "Acme",
    "twilio_subaccount_sid": "AC1", "twilio_auth_token": "tok", "twilio_phone_number": "+14165550100",
    "pinecone_namespace": "acme",
}


@pytest.mark.asyncio
async def test_send_sms_success():
    from routers import zapier as zr
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.telephony.send_sms", AsyncMock(return_value=True)) as send:
        res = await zr.action_send_sms(zr.SendSmsRequest(to="+14165559999", message="hi"), x_api_key="ol_live_x")
    assert res["status"] == "sent"
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_sms_no_phone_number_configured():
    from routers import zapier as zr
    from fastapi import HTTPException
    tenant = {**TENANT, "twilio_phone_number": ""}
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=tenant)):
        with pytest.raises(HTTPException) as exc:
            await zr.action_send_sms(zr.SendSmsRequest(to="+1416", message="hi"), x_api_key="ol_live_x")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_invalid_api_key_rejected():
    from routers import zapier as zr
    from fastapi import HTTPException
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await zr.me(x_api_key="ol_live_bad")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_upsert_lead_creates_when_absent():
    from routers import zapier as zr
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.get_lead_by_phone", AsyncMock(return_value=None)), \
         patch("routers.zapier.db.insert_lead", AsyncMock(return_value={"id": "l-1", "phone": "+1416"})) as ins:
        res = await zr.action_upsert_lead(zr.UpsertLeadRequest(phone="+1416", name="Jo"), x_api_key="ol_live_x")
    assert res["status"] == "created"
    ins.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_lead_updates_when_present():
    from routers import zapier as zr
    existing = {"id": "l-9", "phone": "+1416", "metadata": {}}
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.get_lead_by_phone", AsyncMock(return_value=existing)), \
         patch("routers.zapier.db.update_lead", AsyncMock(return_value={**existing, "name": "Jo"})) as upd:
        res = await zr.action_upsert_lead(zr.UpsertLeadRequest(phone="+1416", name="Jo"), x_api_key="ol_live_x")
    assert res["status"] == "updated" and res["lead_id"] == "l-9"
    upd.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_lead_returns_array():
    from routers import zapier as zr
    lead = {"id": "l-1", "phone": "+1416", "name": "Jo"}
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.get_lead_by_phone", AsyncMock(return_value=lead)):
        res = await zr.search_lead_by_phone(phone="+1416", x_api_key="ol_live_x")
    assert res == [lead]


@pytest.mark.asyncio
async def test_search_lead_empty_when_not_found():
    from routers import zapier as zr
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.get_lead_by_phone", AsyncMock(return_value=None)):
        res = await zr.search_lead_by_phone(phone="+1416", x_api_key="ol_live_x")
    assert res == []


# ---------------------------------------------------------------------------
# Subscribe — flexible body parsing (Zapier sends query/form/JSON inconsistently)
# ---------------------------------------------------------------------------

class _FakeReq:
    def __init__(self, query=None, json_data=None, form_data=None):
        self.query_params = query or {}
        self.headers = {}
        self._json = json_data
        self._form = form_data
    async def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json
    async def form(self):
        return self._form or {}
    async def body(self):
        return b""


@pytest.mark.asyncio
async def test_read_field_from_query():
    from routers import zapier as zr
    req = _FakeReq(query={"event": "call_completed"})
    assert await zr._read_field(req, "event") == "call_completed"


@pytest.mark.asyncio
async def test_read_field_from_json():
    from routers import zapier as zr
    req = _FakeReq(json_data={"target_url": "https://hooks.zapier.com/x"})
    assert await zr._read_field(req, "target_url") == "https://hooks.zapier.com/x"


@pytest.mark.asyncio
async def test_read_field_from_form():
    from routers import zapier as zr
    req = _FakeReq(form_data={"event": "new_lead"})
    assert await zr._read_field(req, "event") == "new_lead"


@pytest.mark.asyncio
async def test_subscribe_via_query_params():
    from routers import zapier as zr
    req = _FakeReq(query={"event": "call_completed", "target_url": "https://hooks.zapier.com/abc"})
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.insert_zapier_subscription", AsyncMock(return_value={"id": "sub-1"})) as ins:
        res = await zr.subscribe(req, x_api_key="ol_live_x")
    assert res == {"id": "sub-1"}
    ins.assert_awaited_once_with("t-1", "call_completed", "https://hooks.zapier.com/abc")


@pytest.mark.asyncio
async def test_subscribe_strips_key_whitespace_and_hookurl_fallback():
    # Real Zapier payload: "event " key had trailing spaces; target via hookUrl.
    from routers import zapier as zr
    req = _FakeReq(json_data={
        "event  ": "call_completed ",
        "hookUrl": "https://hooks.zapier.com/hooks/standard/x/y/",
    })
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))), \
         patch("routers.zapier.db.insert_zapier_subscription", AsyncMock(return_value={"id": "sub-9"})) as ins:
        res = await zr.subscribe(req, x_api_key="ol_live_x")
    assert res == {"id": "sub-9"}
    ins.assert_awaited_once_with("t-1", "call_completed", "https://hooks.zapier.com/hooks/standard/x/y/")


@pytest.mark.asyncio
async def test_subscribe_missing_fields_400():
    from routers import zapier as zr
    from fastapi import HTTPException
    req = _FakeReq(query={"event": "call_completed"})  # no target_url
    with patch("routers.zapier.db.get_tenant_by_api_key_hash", AsyncMock(return_value=dict(TENANT))):
        with pytest.raises(HTTPException) as exc:
            await zr.subscribe(req, x_api_key="ol_live_x")
    assert exc.value.status_code == 400
