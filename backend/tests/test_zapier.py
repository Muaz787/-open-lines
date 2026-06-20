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
