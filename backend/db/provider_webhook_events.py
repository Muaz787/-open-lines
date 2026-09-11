"""
W7B — data access for the provider webhook ledger (migration 024).

The record call goes through a SQL function rather than PostgREST's upsert
because PostgREST cannot express `delivery_count = delivery_count + 1`. A
read-then-write from here would lose increments under concurrent delivery, and
worse, could raise 23505 -- which the webhook endpoint would turn into a 500,
which would make Square retry, which would make the race more likely. One
statement with ON CONFLICT DO UPDATE removes it.
"""
from __future__ import annotations

import logging

from db.supabase import get_client

logger = logging.getLogger(__name__)

PROVIDER_SQUARE = "square"


async def record_delivery(
    *,
    provider: str,
    provider_event_id: str,
    event_type: str,
    merchant_id: str = "",
    object_type: str = "",
    object_id: str = "",
    provider_location_id: str = "",
    provider_version=None,
    provider_status: str = "",
    provider_updated_at: str = "",
    raw_envelope: dict | None = None,
) -> dict | None:
    """Insert this event, or count another delivery of it. Returns the row.

    The returned row's delivery_count is authoritative: 1 means this was the
    first time we saw the event, >1 means Square has sent it before.
    """
    if not (provider and provider_event_id and event_type):
        return None
    res = get_client().rpc("record_provider_webhook_event", {
        "p_provider": provider,
        "p_provider_event_id": provider_event_id,
        "p_event_type": event_type,
        "p_merchant_id": merchant_id or None,
        "p_object_type": object_type or None,
        "p_object_id": object_id or None,
        "p_provider_location_id": provider_location_id or None,
        "p_provider_version": provider_version,
        "p_provider_status": provider_status or None,
        "p_provider_updated_at": provider_updated_at or None,
        "p_raw_envelope": raw_envelope,
    }).execute()
    data = res.data
    if isinstance(data, list):
        return data[0] if data else None
    return data or None


async def set_shadow_resolution(
    row_id: str, *, resolution: str, resolution_detail: str = "",
    merchant_status: str = "", resolved_tenant_id: str = "",
    resolved_tenant_location_id: str = "",
) -> None:
    """Record what W7A's resolver WOULD have decided.

    Tenant/location are written only for a RESOLVED outcome -- a refusal that
    still named a tenant would be a lie in the ledger, and the ledger is what a
    later cutover will be judged against.
    """
    from datetime import datetime, timezone

    patch = {
        "resolution": resolution,
        "resolution_detail": (resolution_detail or "")[:500] or None,
        "merchant_status": merchant_status or None,
        "resolved_tenant_id": resolved_tenant_id or None,
        "resolved_tenant_location_id": resolved_tenant_location_id or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (get_client().table("provider_webhook_events").update(patch)
     .eq("id", row_id).execute())


async def set_legacy_result(row_id: str, result: str, error: str = "") -> None:
    """What the EXISTING handler did. Recorded after dispatch, never before."""
    from datetime import datetime, timezone

    (get_client().table("provider_webhook_events").update({
        "legacy_result": result,
        "last_error": (error or "")[:500] or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", row_id).execute())


async def get_by_event_id(provider: str, provider_event_id: str) -> dict | None:
    res = (get_client().table("provider_webhook_events").select("*")
           .eq("provider", provider).eq("provider_event_id", provider_event_id)
           .limit(1).execute())
    return (res.data or [None])[0]


async def clear_raw_envelopes() -> int:
    """Operator helper for after the envelope shape is confirmed. Not scheduled."""
    res = (get_client().table("provider_webhook_events")
           .update({"raw_envelope": None})
           .not_.is_("raw_envelope", "null").execute())
    return len(res.data or [])
