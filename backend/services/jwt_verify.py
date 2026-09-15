"""
Verify Supabase access tokens locally, without a network round-trip.

verify_tenant_owner used to call auth.get_user(token) on every dashboard
request: an HTTP call to Supabase Auth before any data was even fetched. This
project signs user tokens with an asymmetric key (ES256) whose public half is
published at /auth/v1/.well-known/jwks.json, so the signature, expiry and
audience can be checked here instead.

FAIL-SAFE BY CONSTRUCTION
Local verification only ever ACCEPTS a token whose signature checks out
against the project's published key, or REJECTS one that is definitively bad
(bad signature, expired, wrong audience). Anything it cannot decide -- a legacy
HS256 token, an unknown key id, an issuer we don't recognise, the JWKS being
unreachable -- raises Undecided, and the caller falls back to auth.get_user
exactly as before. So a misconfiguration costs speed, never access.

TRADE-OFF ACCEPTED
A signed-out session's token stays usable until it expires (Supabase default:
one hour), because nothing here asks the auth server whether the session still
exists. That is the same trade-off as supabase-js's getClaims().
"""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

import httpx
import jwt

logger = logging.getLogger(__name__)

# Re-exported so callers can catch "definitively invalid" without importing jwt.
InvalidToken = jwt.InvalidTokenError

AUDIENCE = "authenticated"
ASYMMETRIC_ALGS = {"ES256", "RS256"}
JWKS_TTL_SECONDS = 600
# On an unknown kid (key rotation) we refetch, but not more often than this, so
# a stream of forged kids cannot turn every request into a JWKS fetch.
REFETCH_COOLDOWN_SECONDS = 30
LEEWAY_SECONDS = 30

_keys: dict[str, jwt.PyJWK] = {}
_fetched_at: float | None = None


class Undecided(Exception):
    """Local verification cannot decide; ask the auth server."""


def _auth_base() -> str:
    u = urlparse(os.getenv("SUPABASE_URL", ""))
    if not u.scheme or not u.netloc:
        raise Undecided("SUPABASE_URL is not set")
    return f"{u.scheme}://{u.netloc}/auth/v1"


async def _fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.get(f"{_auth_base()}/.well-known/jwks.json")
        res.raise_for_status()
        return res.json()


async def _refresh_keys(*, force: bool = False) -> None:
    global _keys, _fetched_at
    now = time.monotonic()
    if _fetched_at is not None:
        age = now - _fetched_at
        if age < (REFETCH_COOLDOWN_SECONDS if force else JWKS_TTL_SECONDS):
            return
    # Stamp before fetching: a failing JWKS endpoint is retried after the
    # cooldown, not on every request.
    _fetched_at = now
    try:
        jwks = await _fetch_jwks()
    except Exception as e:
        logger.warning("JWKS fetch failed; tokens fall back to auth.get_user: %s", e)
        return
    keys: dict[str, jwt.PyJWK] = {}
    for raw in jwks.get("keys", []):
        try:
            key = jwt.PyJWK(raw)
        except Exception:
            continue
        if raw.get("kid") and key.algorithm_name in ASYMMETRIC_ALGS:
            keys[raw["kid"]] = key
    _keys = keys


async def verify(token: str) -> dict:
    """The claims of a locally verified access token.

    Raises InvalidToken when the token is definitively invalid, and Undecided
    when only the auth server can say.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as e:
        raise Undecided("not a JWT") from e
    alg, kid = header.get("alg"), header.get("kid")
    if alg not in ASYMMETRIC_ALGS or not kid:
        raise Undecided(f"alg {alg!r} cannot be verified locally")

    await _refresh_keys()
    key = _keys.get(kid)
    if key is None:
        await _refresh_keys(force=True)  # the signing key may have rotated
        key = _keys.get(kid)
    if key is None:
        raise Undecided("unknown signing key")
    if key.algorithm_name != alg:
        raise InvalidToken(f"token alg {alg} does not match key alg {key.algorithm_name}")

    issuer = _auth_base()
    try:
        return jwt.decode(
            token,
            key=key,
            algorithms=[key.algorithm_name],
            audience=AUDIENCE,
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
    except jwt.InvalidIssuerError as e:
        # The signature already proved it is our project's token; an issuer we
        # don't recognise (a custom auth domain) is a config question, not a
        # forgery. Let the auth server decide rather than lock everyone out.
        logger.warning("JWT issuer is not %s; falling back to auth.get_user", issuer)
        raise Undecided("unrecognised issuer") from e
