"""
Server-side OAuth state nonces — CSRF / replay protection for provider connect
flows (Google Calendar, Microsoft Calendar, HubSpot, Slack).

Instead of using the guessable `state = tenant_id`, connect-init issues a random,
single-use, time-limited nonce bound to (tenant_id, provider) and stored in the
`oauth_states` table. The callback consumes it: the row is deleted on read, so a
state cannot be replayed, and we verify the provider matches and it hasn't expired.
The tenant_id is taken from the validated state row — never from attacker input —
so a forged/mismatched state can never resolve to another tenant.
"""
import logging
import secrets
from datetime import datetime, timezone, timedelta

from db import supabase as db

logger = logging.getLogger(__name__)

# How long a connect attempt stays valid. OAuth consent rarely takes more than a
# couple of minutes; 15 gives comfortable headroom without a large replay window.
STATE_TTL_MINUTES = 15

# Recognised providers — callbacks pass their own value and we require a match.
PROVIDERS = {"google_calendar", "microsoft_calendar", "hubspot", "slack"}


class OAuthStateError(Exception):
    """Raised when an OAuth state is missing, malformed, expired, reused,
    or bound to a different provider. Carries only a generic, user-safe reason."""


async def issue_state(tenant_id: str, provider: str) -> str:
    """Create and persist a fresh nonce for this tenant + provider. Returns the
    opaque state string to hand to the provider."""
    if provider not in PROVIDERS:
        raise OAuthStateError("unknown provider")
    if not tenant_id:
        raise OAuthStateError("missing tenant")
    nonce = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)
    await db.insert_oauth_state(nonce, tenant_id, provider, expires_at.isoformat())
    return nonce


async def consume_state(state: str | None, provider: str) -> str:
    """Validate and single-use-consume a state, returning the bound tenant_id.

    Raises OAuthStateError on missing / unknown / reused / expired / provider-
    mismatched state. Never echoes the raw state back.
    """
    if not state or not isinstance(state, str) or len(state) > 256:
        raise OAuthStateError("missing or malformed state")

    row = await db.consume_oauth_state(state)  # deletes the row if present
    if not row:
        raise OAuthStateError("unknown or already-used state")

    if row.get("provider") != provider:
        logger.warning("OAuth state provider mismatch: expected %s got %s", provider, row.get("provider"))
        raise OAuthStateError("provider mismatch")

    expires_at = row.get("expires_at")
    try:
        exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    except Exception:
        raise OAuthStateError("malformed state record")

    if datetime.now(timezone.utc) > exp_dt:
        raise OAuthStateError("state expired")

    tenant_id = row.get("tenant_id")
    if not tenant_id:
        raise OAuthStateError("state missing tenant")

    return str(tenant_id)
