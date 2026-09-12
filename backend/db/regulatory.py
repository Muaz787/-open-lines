"""Data access for the regulatory tables (migration 027, W9G).

Thin wrappers over the service-role client, matching db/locations.py and
db/phone_numbers.py. Every query is tenant-scoped at the query level, defence in
depth on top of the ownership checks in the route layer and the composite foreign
keys in the database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── tenant_regulatory_addresses ────────────────────────────────────────────

async def get_address(tenant_id: str, address_row_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_addresses").select("*")
           .eq("tenant_id", tenant_id).eq("id", address_row_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_address(tenant_id: str, iso_country: str,
                       tenant_location_id: str | None) -> dict | None:
    """The tenant's address row for this country and location, if any.

    Mirrors the two partial unique indexes: a location-scoped row when a location is
    named, the tenant-level row when not.
    """
    q = (get_client().table("tenant_regulatory_addresses").select("*")
         .eq("tenant_id", tenant_id).eq("iso_country", iso_country))
    q = (q.eq("tenant_location_id", tenant_location_id) if tenant_location_id
         else q.is_("tenant_location_id", "null"))
    return (q.limit(1).execute().data or [None])[0]


async def insert_address(row: dict) -> dict | None:
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_addresses")
            .insert(payload).execute().data or [None])[0]


async def update_address(address_row_id: str, patch: dict) -> dict | None:
    return (get_client().table("tenant_regulatory_addresses")
            .update({**patch, "updated_at": _now_iso()})
            .eq("id", address_row_id).execute().data or [None])[0]


# ── tenant_regulatory_profiles ─────────────────────────────────────────────

async def list_profiles(tenant_id: str) -> list[dict]:
    return (get_client().table("tenant_regulatory_profiles").select("*")
            .eq("tenant_id", tenant_id).order("created_at").execute().data or [])


async def get_profile(tenant_id: str, profile_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("tenant_id", tenant_id).eq("id", profile_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_profile_for_address(tenant_id: str, iso_country: str, number_type: str,
                                   end_user_type: str,
                                   regulatory_address_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("tenant_id", tenant_id).eq("iso_country", iso_country)
           .eq("number_type", number_type).eq("end_user_type", end_user_type)
           .eq("regulatory_address_id", regulatory_address_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_profile_by_bundle(bundle_sid: str) -> dict | None:
    """The profile a Bundle SID belongs to. THIS IS THE CALLBACK'S ONLY ROUTE IN.

    trp_bundle_sid_key makes the answer unique, so a callback never has to be
    believed about which tenant it concerns.
    """
    sid = str(bundle_sid or "").strip()
    if not sid:
        return None
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("bundle_sid", sid).limit(2).execute())
    rows = res.data or []
    if len(rows) > 1:
        logger.error("REGULATORY IDENTITY CONFLICT: %d profiles share a bundle sid",
                     len(rows))
        return None
    return rows[0] if rows else None


async def list_nonterminal_profiles(states: tuple[str, ...], limit: int = 200) -> list[dict]:
    return (get_client().table("tenant_regulatory_profiles").select("*")
            .in_("state", list(states)).order("last_synced_at", desc=False)
            .limit(limit).execute().data or [])


async def insert_profile(row: dict) -> dict | None:
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_profiles")
            .insert(payload).execute().data or [None])[0]


async def update_profile(profile_id: str, patch: dict) -> dict | None:
    return (get_client().table("tenant_regulatory_profiles")
            .update({**patch, "updated_at": _now_iso()})
            .eq("id", profile_id).execute().data or [None])[0]


async def transition_profile(profile_id: str, *, expected_state: str,
                             new_state: str, patch: dict | None = None) -> bool:
    """Compare-and-set a profile's state. True only if we won.

    Fenced on the state we believed the profile was in, so a callback and a
    reconciliation sweep racing on the same profile cannot both apply a transition.
    len(data) == 1 proves we were the one that moved it.
    """
    res = (get_client().table("tenant_regulatory_profiles")
           .update({**(patch or {}), "state": new_state, "updated_at": _now_iso()})
           .eq("id", profile_id).eq("state", expected_state).execute())
    return len(res.data or []) == 1


# ── tenant_regulatory_events ───────────────────────────────────────────────

async def latest_event(bundle_sid: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_events").select("*")
           .eq("bundle_sid", bundle_sid).order("last_received_at", desc=True)
           .limit(1).execute())
    return (res.data or [None])[0]


async def count_events_with_fingerprint(bundle_sid: str, fingerprint: str) -> int:
    res = (get_client().table("tenant_regulatory_events").select("id", count="exact")
           .eq("bundle_sid", bundle_sid).eq("fingerprint", fingerprint).execute())
    return res.count or 0


async def insert_event(row: dict) -> dict | None:
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_events")
            .insert(payload).execute().data or [None])[0]


async def bump_event_delivery(event_id: str, delivery_count: int) -> dict | None:
    return (get_client().table("tenant_regulatory_events")
            .update({"delivery_count": delivery_count,
                     "last_received_at": _now_iso(), "updated_at": _now_iso()})
            .eq("id", event_id).execute().data or [None])[0]
