"""
Tenant-ownership / IDOR protection tests for services.security.verify_tenant_owner.

These cover the four cases that matter for the dashboard API:
  * no token            -> 401
  * invalid/expired tok -> 401
  * valid token, wrong tenant -> 403
  * valid token, correct tenant -> allowed
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from services.security import verify_tenant_owner


def _client_for(metadata_tenant_id: str | None):
    """A fake Supabase client whose get_user returns a user with the given
    user_metadata.tenant_id."""
    client = MagicMock()
    user = MagicMock()
    user.user_metadata = {"tenant_id": metadata_tenant_id} if metadata_tenant_id is not None else {}
    client.auth.get_user.return_value = MagicMock(user=user)
    return client


@pytest.mark.asyncio
async def test_missing_authorization_returns_401():
    with pytest.raises(HTTPException) as exc:
        await verify_tenant_owner("tenant-1", None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_malformed_authorization_returns_401():
    with pytest.raises(HTTPException) as exc:
        await verify_tenant_owner("tenant-1", "not-a-bearer-token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    bad = MagicMock()
    bad.auth.get_user.side_effect = Exception("invalid token")
    with patch("db.supabase.get_client", return_value=bad):
        with pytest.raises(HTTPException) as exc:
            await verify_tenant_owner("tenant-1", "Bearer expired")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_tenant_returns_403():
    with patch("db.supabase.get_client", return_value=_client_for("tenant-OTHER")):
        with pytest.raises(HTTPException) as exc:
            await verify_tenant_owner("tenant-1", "Bearer valid")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_correct_owner_is_allowed():
    with patch("db.supabase.get_client", return_value=_client_for("tenant-1")):
        # Should not raise.
        await verify_tenant_owner("tenant-1", "Bearer valid")
