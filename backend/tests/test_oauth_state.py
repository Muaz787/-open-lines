"""
OAuth state nonce tests — CSRF / replay protection for provider connect flows.

Covers the cases required for the connect/callback hardening:
  * valid state            -> resolves to the bound tenant_id
  * missing state          -> rejected
  * malformed state        -> rejected
  * expired state          -> rejected
  * unknown / reused state -> rejected (row deleted on first consume)
  * provider mismatch      -> rejected
  * tenant comes from the stored row, never from attacker input
"""
import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone, timedelta

from services.oauth_state import OAuthStateError, consume_state, issue_state


def _row(tenant_id="tenant-1", provider="google_calendar", minutes=10):
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return {"nonce": "n", "tenant_id": tenant_id, "provider": provider, "expires_at": exp.isoformat()}


@pytest.mark.asyncio
async def test_issue_state_persists_and_returns_opaque_nonce():
    with patch("db.supabase.insert_oauth_state", new=AsyncMock()) as ins:
        state = await issue_state("tenant-1", "google_calendar")
    assert isinstance(state, str) and len(state) > 20
    assert state != "tenant-1"            # never the raw tenant id
    ins.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_state_resolves_tenant():
    with patch("db.supabase.consume_oauth_state", new=AsyncMock(return_value=_row())):
        assert await consume_state("n", "google_calendar") == "tenant-1"


@pytest.mark.asyncio
async def test_missing_state_fails():
    with pytest.raises(OAuthStateError):
        await consume_state(None, "google_calendar")


@pytest.mark.asyncio
async def test_malformed_state_fails():
    with pytest.raises(OAuthStateError):
        await consume_state("x" * 300, "google_calendar")


@pytest.mark.asyncio
async def test_unknown_or_reused_state_fails():
    # consume returns None: either never existed or already consumed (single-use).
    with patch("db.supabase.consume_oauth_state", new=AsyncMock(return_value=None)):
        with pytest.raises(OAuthStateError):
            await consume_state("n", "google_calendar")


@pytest.mark.asyncio
async def test_expired_state_fails():
    with patch("db.supabase.consume_oauth_state", new=AsyncMock(return_value=_row(minutes=-1))):
        with pytest.raises(OAuthStateError):
            await consume_state("n", "google_calendar")


@pytest.mark.asyncio
async def test_provider_mismatch_fails():
    with patch("db.supabase.consume_oauth_state", new=AsyncMock(return_value=_row(provider="slack"))):
        with pytest.raises(OAuthStateError):
            await consume_state("n", "google_calendar")


@pytest.mark.asyncio
async def test_tenant_taken_from_state_not_input():
    with patch("db.supabase.consume_oauth_state", new=AsyncMock(return_value=_row(tenant_id="real-owner"))):
        assert await consume_state("n", "google_calendar") == "real-owner"
