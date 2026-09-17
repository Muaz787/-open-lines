"""
OpenAI / ChatGPT Ads — server-side Conversions API.

The browser pixel (frontend root layout + onboarding) already reports
`trial_started`, but ad blockers and lost tabs drop client events. This sends
the same conversion from the backend the moment a trial subscription is created,
which is not blockable. The pixel and this call carry the SAME event id
(the tenant id), so OpenAI de-duplicates them into one conversion rather than
counting both.

Fail-safe by construction: no-ops when OPENAI_ADS_CONVERSION_KEY is unset (so it
does nothing until the key is configured), and never raises into the caller — a
conversion ping must not be able to fail a signup.

Env:
  OPENAI_ADS_CONVERSION_KEY  (secret) — the Conversions API key from the OpenAI
                             Ads dashboard ("Create conversion key"). Required for
                             this to send anything.
  OPENAI_ADS_PIXEL_ID        (optional) — defaults to the public pixel id already
                             used by the frontend.
"""
from __future__ import annotations

import os
import time
import logging

import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://bzr.openai.com/v1/events"
# Public pixel id (also inlined in the frontend root layout). Overridable by env.
DEFAULT_PIXEL_ID = "MuZXtrxLm9EAMNURQggmNL"


def _pixel_id() -> str:
    return (os.getenv("OPENAI_ADS_PIXEL_ID", "") or DEFAULT_PIXEL_ID).strip()


def _api_key() -> str:
    return os.getenv("OPENAI_ADS_CONVERSION_KEY", "").strip()


def is_configured() -> bool:
    return bool(_api_key())


async def send_conversion(
    event_type: str,
    *,
    event_id: str,
    data: dict | None = None,
    source_url: str | None = None,
    timestamp_ms: int | None = None,
) -> None:
    """Fire one server-side conversion. No-ops without a key; never raises.

    event_id MUST match the browser pixel's event id for the same conversion
    (we use the tenant id) so OpenAI de-duplicates the pixel + server events.
    """
    key = _api_key()
    if not key:
        return  # not configured — nothing to do
    if not event_id:
        logger.warning("OpenAI Ads: refusing to send %s without an event_id (dedup key)", event_type)
        return

    event: dict = {
        "id": str(event_id),
        "type": event_type,
        "timestamp_ms": int(timestamp_ms if timestamp_ms is not None else time.time() * 1000),
        "action_source": "web",
        "data": data or {},
    }
    src = source_url or (os.getenv("FRONTEND_URL", "").strip() or None)
    if src:
        event["source_url"] = src

    payload = {"validate_only": False, "events": [event]}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(
                f"{_ENDPOINT}?pid={_pixel_id()}",
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        if res.status_code >= 300:
            logger.warning("OpenAI Ads conversion %s rejected: HTTP %s %s",
                           event_type, res.status_code, res.text[:200])
        else:
            logger.info("OpenAI Ads conversion sent: %s id=%s", event_type, event_id)
    except Exception as e:
        logger.warning("OpenAI Ads conversion %s failed: %s", event_type, e)
