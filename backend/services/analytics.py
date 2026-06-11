"""Fire-and-forget server-side PostHog event capture.

No-ops entirely when POSTHOG_API_KEY is unset, and never raises — analytics
must never break a product flow (Vapi webhooks, Stripe webhooks, bookings).

PRIVACY: callers must never pass full call transcripts, caller phone numbers,
uploaded knowledge-base content, calendar event details, or summaries as
properties. Stick to ids, counts, durations, statuses, and plan names.
"""

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")


async def _send(payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(f"{POSTHOG_HOST}/i/v0/e/", json=payload)
    except Exception as e:  # noqa: BLE001 — analytics is strictly best-effort
        logger.debug("PostHog capture failed: %s", e)


def capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Schedule an event capture on the running loop. Safe to call anywhere."""
    if not POSTHOG_API_KEY or not distinct_id:
        return
    payload = {
        "api_key": POSTHOG_API_KEY,
        "event": event,
        "distinct_id": str(distinct_id),
        "properties": {**(properties or {}), "source": "backend"},
    }
    try:
        asyncio.get_running_loop()
        asyncio.create_task(_send(payload))
    except RuntimeError:
        # No running event loop (sync/test context) — drop silently
        pass


def distinct_id_for(tenant: dict | None, fallback: str = "") -> str:
    """Prefer the Supabase auth user id; fall back to tenant id."""
    if tenant:
        return tenant.get("user_id") or tenant.get("id") or fallback
    return fallback
