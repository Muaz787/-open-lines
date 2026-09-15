"""
Local verification of Supabase access tokens (services/jwt_verify.py) and the
tenant checks built on it (services/security.py).

The rule under test: a token is accepted locally only when its signature checks
out against the project's published key, rejected locally only when it is
definitively bad, and everything else falls back to auth.get_user -- so a
misconfiguration costs speed, never access.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from services import jwt_verify, security

URL = "https://proj.supabase.co"
ISS = f"{URL}/auth/v1"
KID = "kid-1"

_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_OTHER_PRIVATE = ec.generate_private_key(ec.SECP256R1())


def _jwks(private=_PRIVATE, kid=KID) -> dict:
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}


def _token(*, tenant_id="t1", user_meta_tenant_id=None, private=_PRIVATE, kid=KID,
           alg="ES256", exp_in=3600, aud="authenticated", iss=ISS, secret=None) -> str:
    # tenant_id -> app_metadata (server-only, what authz trusts).
    # user_meta_tenant_id -> user_metadata (user-editable, must be ignored).
    claims = {"sub": "user-1", "email": "owner@example.com", "aud": aud, "iss": iss,
              "exp": int(time.time()) + exp_in, "role": "authenticated",
              "app_metadata": {"tenant_id": tenant_id} if tenant_id is not None else {},
              "user_metadata": {"tenant_id": user_meta_tenant_id} if user_meta_tenant_id else {}}
    key = secret if secret is not None else private
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setattr(jwt_verify, "_keys", {})
    monkeypatch.setattr(jwt_verify, "_fetched_at", None)


@pytest.fixture
def jwks(monkeypatch):
    fetch = AsyncMock(return_value=_jwks())
    monkeypatch.setattr(jwt_verify, "_fetch_jwks", fetch)
    return fetch


@pytest.fixture
def auth_server():
    """The network fallback. Local verification should leave it untouched."""
    client = MagicMock()
    user = MagicMock(id="user-1", email="owner@example.com",
                     app_metadata={"tenant_id": "t1"}, user_metadata={})
    client.auth.get_user.return_value = MagicMock(user=user)
    with patch("db.supabase.get_client", return_value=client):
        yield client.auth.get_user


class _Req:
    path_params = {"tenant_id": "t1"}


# ── accepted locally ─────────────────────────────────────────────────────────

async def test_a_valid_token_for_the_tenant_is_allowed_without_the_auth_server(jwks, auth_server):
    await security.verify_tenant_owner("t1", f"Bearer {_token()}")
    auth_server.assert_not_called()


async def test_keys_are_cached_between_requests(jwks, auth_server):
    for _ in range(3):
        await security.verify_tenant_owner("t1", f"Bearer {_token()}")
    assert jwks.await_count == 1


async def test_identity_comes_from_the_verified_claims(jwks, auth_server):
    who = await security.authenticated_tenant_user(_Req(), f"Bearer {_token()}")
    assert who == {"user_id": "user-1", "email": "owner@example.com", "tenant_id": "t1"}
    auth_server.assert_not_called()


# ── rejected locally ─────────────────────────────────────────────────────────

async def test_a_valid_token_for_another_tenant_is_403(jwks, auth_server):
    with pytest.raises(HTTPException) as exc:
        await security.verify_tenant_owner("t1", f"Bearer {_token(tenant_id='t-other')}")
    assert exc.value.status_code == 403
    auth_server.assert_not_called()


async def test_a_user_metadata_tenant_id_is_ignored(jwks, auth_server):
    """The vulnerability: user_metadata is user-editable. A token that names the
    target tenant ONLY in user_metadata (app_metadata absent) must be denied."""
    token = _token(tenant_id=None, user_meta_tenant_id="t1")
    with pytest.raises(HTTPException) as exc:
        await security.verify_tenant_owner("t1", f"Bearer {token}")
    assert exc.value.status_code == 403
    auth_server.assert_not_called()


async def test_app_metadata_wins_over_a_conflicting_user_metadata(jwks, auth_server):
    """app_metadata says t1 (correct); user_metadata forges t-other. Access to t1
    is allowed on app_metadata, and the forged user_metadata changes nothing."""
    token = _token(tenant_id="t1", user_meta_tenant_id="t-other")
    await security.verify_tenant_owner("t1", f"Bearer {token}")
    with pytest.raises(HTTPException) as exc:
        await security.verify_tenant_owner("t-other", f"Bearer {token}")
    assert exc.value.status_code == 403
    auth_server.assert_not_called()


@pytest.mark.parametrize("bad", [
    pytest.param({"exp_in": -3600}, id="expired"),
    pytest.param({"private": _OTHER_PRIVATE}, id="signed-by-another-key"),
    pytest.param({"aud": "anon"}, id="wrong-audience"),
])
async def test_a_definitively_bad_token_is_401_without_the_auth_server(jwks, auth_server, bad):
    with pytest.raises(HTTPException) as exc:
        await security.verify_tenant_owner("t1", f"Bearer {_token(**bad)}")
    assert exc.value.status_code == 401
    auth_server.assert_not_called()


# ── undecided: falls back to the auth server ─────────────────────────────────

async def test_a_legacy_hs256_token_falls_back(jwks, auth_server):
    token = _token(alg="HS256", secret="legacy-secret-at-least-32-bytes-long!!")
    await security.verify_tenant_owner("t1", f"Bearer {token}")
    auth_server.assert_called_once()
    jwks.assert_not_awaited()


async def test_an_unknown_key_id_refetches_once_then_falls_back(jwks, auth_server):
    await security.verify_tenant_owner("t1", f"Bearer {_token(kid='rotated')}")
    assert jwks.await_count == 1  # first load; the forced refetch is inside the cooldown
    auth_server.assert_called_once()


async def test_a_rotated_key_is_picked_up_by_the_refetch(monkeypatch, auth_server):
    fetch = AsyncMock(side_effect=[_jwks(), _jwks(kid="kid-2")])
    monkeypatch.setattr(jwt_verify, "_fetch_jwks", fetch)
    await security.verify_tenant_owner("t1", f"Bearer {_token()}")
    monkeypatch.setattr(jwt_verify, "_fetched_at", time.monotonic() - 60)  # past the cooldown
    await security.verify_tenant_owner("t1", f"Bearer {_token(kid='kid-2')}")
    assert fetch.await_count == 2
    auth_server.assert_not_called()


async def test_an_unreachable_jwks_falls_back(monkeypatch, auth_server):
    monkeypatch.setattr(jwt_verify, "_fetch_jwks", AsyncMock(side_effect=OSError("down")))
    await security.verify_tenant_owner("t1", f"Bearer {_token()}")
    auth_server.assert_called_once()


async def test_an_unrecognised_issuer_falls_back_rather_than_locking_out(jwks, auth_server):
    await security.verify_tenant_owner("t1", f"Bearer {_token(iss='https://auth.custom.example/auth/v1')}")
    auth_server.assert_called_once()


async def test_a_token_whose_header_lies_about_its_alg_is_rejected(jwks, auth_server):
    """An RS256 header on our ES256 key must not be accepted or downgraded."""
    token = _token()
    header, payload, sig = token.split(".")
    forged_header = jwt.utils.base64url_encode(b'{"alg":"RS256","kid":"kid-1","typ":"JWT"}').decode()
    with pytest.raises(HTTPException) as exc:
        await security.verify_tenant_owner("t1", f"Bearer {forged_header}.{payload}.{sig}")
    assert exc.value.status_code == 401
    auth_server.assert_not_called()
