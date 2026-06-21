"""
Zapier integration core: API-key generation/hashing and the REST Hook
event fan-out (emit). Triggers call emit(tenant_id, event, payload); every
Zapier subscription registered for that (tenant, event) receives a POST.

emit() is strictly best-effort — it never raises into the calling flow
(a call/payment must never fail because a Zap endpoint is down).
"""
import os
import json
import hmac
import hashlib
import secrets
import logging

import httpx

from db import supabase as db

logger = logging.getLogger(__name__)

# Master switch for the whole Zapier integration. Off by default — the feature
# is paused. Set ZAPIER_ENABLED=true (Railway) to bring it back. When off, the
# /zapier/* routes are not registered and emit() is a no-op.
ENABLED = os.getenv("ZAPIER_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

# Supported REST Hook events (kept in sync with the Zapier app triggers)
EVENTS = (
    "call_completed",
    "new_lead",
    "hot_lead",
    "appointment_booked",
    "appointment_cancelled",
    "deposit_paid",
    "deposit_refunded",
)

_KEY_PREFIX = "ol_live_"
_SIGNING_SECRET = os.getenv("ZAPIER_SIGNING_SECRET", "")

# Representative payloads Zapier uses to set up field mapping before live data
# exists. Shapes must match what emit() actually sends per event.
SAMPLES: dict[str, dict] = {
    "call_completed": {
        "call_id": "c_sample_123", "caller_name": "Jordan Lee", "caller_phone": "+14165550123",
        "duration_secs": 142, "urgency": "hot", "summary": "Caller wants a 3-bed condo viewing this weekend.",
        "suggested_next_step": "Book a Saturday viewing and confirm budget.",
        "key_details": {"budget": "$650k", "timeline": "30 days", "pre_approved": "yes"},
        "transcript": "AI: Thanks for calling… You: Hi, I'm looking for…",
    },
    "new_lead": {
        "lead_id": "l_sample_123", "name": "Jordan Lee", "phone": "+14165550123", "status": "new",
    },
    "hot_lead": {
        "lead_id": "l_sample_123", "name": "Jordan Lee", "phone": "+14165550123", "urgency": "hot",
        "summary": "Ready to buy within 30 days, pre-approved.",
        "key_details": {"budget": "$650k", "timeline": "30 days"},
    },
    "appointment_booked": {
        "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing",
        "datetime": "2026-07-02T14:00:00+00:00", "duration_minutes": 30, "status": "confirmed",
    },
    "appointment_cancelled": {
        "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing",
        "datetime": "2026-07-02T14:00:00+00:00", "refunded": True, "refund_amount": 20.0, "currency": "CAD",
    },
    "deposit_paid": {
        "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing",
        "amount": 20.0, "currency": "CAD", "provider": "square",
    },
    "deposit_refunded": {
        "caller_name": "Jordan Lee", "caller_phone": "+14165550123", "service": "Property viewing",
        "amount": 20.0, "currency": "CAD", "provider": "square",
    },
}


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def generate_api_key() -> tuple[str, str, str]:
    """Return (raw_key, key_hash, key_prefix). Only the hash is persisted;
    the raw key is shown to the owner exactly once."""
    raw = _KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw), raw[:16]


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Event fan-out
# ---------------------------------------------------------------------------

def _sign(body: bytes) -> str | None:
    if not _SIGNING_SECRET:
        return None
    return "sha256=" + hmac.new(_SIGNING_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def emit(tenant_id: str, event: str, payload: dict) -> None:
    """POST `payload` to every Zapier subscription for (tenant_id, event).
    Best-effort: logs and swallows all errors. No-op while the integration is
    paused (ENABLED is false)."""
    if not ENABLED:
        return
    try:
        subs = await db.get_zapier_subscriptions(tenant_id, event)
    except Exception as e:
        logger.warning("zapier.emit: subscription lookup failed for %s/%s: %s", tenant_id, event, e)
        return
    if not subs:
        return

    # Flat payload (fields at top level) so Zapier field-mapping matches the
    # /triggers/{event}/sample shape. _event / _tenant_id carry the envelope.
    body = json.dumps({**payload, "_event": event, "_tenant_id": tenant_id}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    sig = _sign(body)
    if sig:
        headers["X-OpenLines-Signature"] = sig

    async with httpx.AsyncClient(timeout=10.0) as client:
        for sub in subs:
            url = sub.get("target_url", "")
            if not url:
                continue
            try:
                await client.post(url, content=body, headers=headers)
            except Exception as e:
                logger.warning("zapier.emit: POST to %s failed (%s/%s): %s", url, tenant_id, event, e)

    logger.info("zapier.emit: %s delivered to %d subscriber(s) for tenant %s", event, len(subs), tenant_id)
