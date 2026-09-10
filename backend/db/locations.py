"""
Data-access helpers for the multi-location foundation (migration 012).

Thin wrappers over the Supabase service-role client, matching the style in
db/routing.py and db/supabase.py. Every query is tenant-scoped at the query level,
defence in depth on top of the owner-auth check in the API layer.

DARK AS OF W1. Nothing in the call path, booking path, OAuth flow, provisioning or
prompt build reads any of this. tenants.square_location_id remains authoritative.
These helpers exist so the backfill and the W2+ sync have somewhere to write.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db.supabase import get_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# tenant_locations
# ---------------------------------------------------------------------------

async def list_locations(tenant_id: str, active_only: bool = False) -> list:
    q = (get_client().table("tenant_locations").select("*")
         .eq("tenant_id", tenant_id))
    if active_only:
        q = q.eq("active", True)
    res = q.order("created_at").execute()
    return res.data or []


async def get_default_location(tenant_id: str) -> dict | None:
    res = (get_client().table("tenant_locations").select("*")
           .eq("tenant_id", tenant_id).eq("is_default", True).limit(1).execute())
    return (res.data or [None])[0]


async def get_location_by_slug(tenant_id: str, slug: str) -> dict | None:
    res = (get_client().table("tenant_locations").select("*")
           .eq("tenant_id", tenant_id).eq("slug", slug).limit(1).execute())
    return (res.data or [None])[0]


async def get_location_by_id(tenant_id: str, location_id: str) -> dict | None:
    res = (get_client().table("tenant_locations").select("*")
           .eq("tenant_id", tenant_id).eq("id", location_id).limit(1).execute())
    return (res.data or [None])[0]


async def delete_location(tenant_id: str, location_id: str) -> None:
    """Only for the compensating rollback in services/location_adoption when a
    location was created but its binding could not be attached. Normal removal is
    deactivation (active=false) — a location may be referenced by history."""
    (get_client().table("tenant_locations").delete()
     .eq("tenant_id", tenant_id).eq("id", location_id).execute())


async def insert_location(tenant_id: str, data: dict) -> dict:
    row = {**data, "tenant_id": tenant_id,
           "created_at": _now_iso(), "updated_at": _now_iso()}
    res = get_client().table("tenant_locations").insert(row).execute()
    return (res.data or [{}])[0]


async def update_location(tenant_id: str, location_id: str, data: dict) -> dict:
    res = (get_client().table("tenant_locations")
           .update({**data, "updated_at": _now_iso()})
           .eq("tenant_id", tenant_id).eq("id", location_id).execute())
    return (res.data or [{}])[0]


# ---------------------------------------------------------------------------
# location_provider_bindings
# ---------------------------------------------------------------------------

async def list_bindings(tenant_id: str, provider: str | None = None) -> list:
    q = (get_client().table("location_provider_bindings").select("*")
         .eq("tenant_id", tenant_id))
    if provider is not None:
        q = q.eq("provider", provider)
    res = q.order("created_at").execute()
    return res.data or []


async def get_binding(tenant_id: str, provider: str, provider_location_id: str) -> dict | None:
    """Look up by the provider's own immutable id — the natural key that makes
    every sync idempotent."""
    res = (get_client().table("location_provider_bindings").select("*")
           .eq("tenant_id", tenant_id)
           .eq("provider", provider)
           .eq("provider_location_id", provider_location_id)
           .limit(1).execute())
    return (res.data or [None])[0]


async def insert_binding(tenant_id: str, data: dict) -> dict:
    row = {**data, "tenant_id": tenant_id,
           "created_at": _now_iso(), "updated_at": _now_iso()}
    res = get_client().table("location_provider_bindings").insert(row).execute()
    return (res.data or [{}])[0]


async def update_binding(tenant_id: str, binding_id: str, data: dict) -> dict:
    res = (get_client().table("location_provider_bindings")
           .update({**data, "updated_at": _now_iso()})
           .eq("tenant_id", tenant_id).eq("id", binding_id).execute())
    return (res.data or [{}])[0]


# ---------------------------------------------------------------------------
# Backfill support
# ---------------------------------------------------------------------------

async def list_all_tenants_for_backfill() -> list:
    """Every tenant, with only the columns the backfill reads.

    Deliberately narrow: the backfill must not be able to touch a column it has no
    business reading, and a narrow select keeps credentials (tokens, auth keys)
    out of the process entirely.
    """
    res = (get_client().table("tenants")
           .select("id, business_name, country, calendar_timezone, "
                   "square_location_id, square_location_timezone, square_currency")
           .order("created_at").execute())
    return res.data or []
