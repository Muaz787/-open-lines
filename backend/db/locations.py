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

async def refresh_derived_timezone(tenant_id: str, location_id: str, *,
                                   was: str | None, now: str) -> bool:
    """Advance a tenant location's timezone ONLY if it still equals `was`.

    Compare-and-swap, in the UPDATE's own predicate. Returns True only if we
    made the change -- `len(res.data) == 1` is the proof, the same shape W7D
    uses for provider_version fencing.

    WHY IT MUST BE CONDITIONAL (W8.2)
    tenant_locations.timezone means "operator override, else the provider value
    derived at adoption" (see location_adoption.location_payload). There is no
    column recording which, so the only safe evidence that a value is still
    tracking the provider is that it EQUALS the provider timezone we last
    stored. A read-then-write would lose that: an operator changing the timezone
    between our read and our write would be silently overwritten. Putting the
    old value in the predicate means a race can only ever make us lose, never
    make us clobber.

    `was=None` handles the other direction: a location with no timezone, whose
    binding had none either, may be populated the first time the provider
    reports one. A location that has a value while the binding had none cannot
    be provider-derived, so it is left alone.
    """
    if not (tenant_id and location_id and now):
        return False
    q = (get_client().table("tenant_locations").update({"timezone": now, "updated_at": _now_iso()})
         .eq("tenant_id", tenant_id).eq("id", location_id))
    q = q.is_("timezone", "null") if was is None else q.eq("timezone", was)
    res = q.execute()
    return len(res.data or []) == 1


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


# ---------------------------------------------------------------------------
# call_location_state (migration 014) — authoritative per-call location
# ---------------------------------------------------------------------------

async def get_call_state(vapi_call_id: str) -> dict | None:
    if not vapi_call_id:
        return None
    res = (get_client().table("call_location_state").select("*")
           .eq("vapi_call_id", vapi_call_id).limit(1).execute())
    return (res.data or [None])[0]


async def insert_call_state(data: dict) -> dict:
    res = get_client().table("call_location_state").insert(
        {**data, "created_at": _now_iso(), "updated_at": _now_iso()}).execute()
    return (res.data or [{}])[0]


async def update_call_state(vapi_call_id: str, tenant_id: str, data: dict) -> dict:
    """Tenant-scoped on purpose: a call id from one tenant must never be able to
    mutate another tenant's state, even if an id were guessed."""
    res = (get_client().table("call_location_state")
           .update({**data, "updated_at": _now_iso()})
           .eq("vapi_call_id", vapi_call_id).eq("tenant_id", tenant_id).execute())
    return (res.data or [{}])[0]


async def delete_call_state(vapi_call_id: str) -> None:
    if not vapi_call_id:
        return
    (get_client().table("call_location_state").delete()
     .eq("vapi_call_id", vapi_call_id).execute())


async def purge_expired_call_state(now_iso: str) -> int:
    res = (get_client().table("call_location_state").delete()
           .lt("expires_at", now_iso).execute())
    return len(res.data or [])


# ---------------------------------------------------------------------------
# Bindings by location (W4 availability needs the provider id for one location)
# ---------------------------------------------------------------------------

async def get_binding_for_location(tenant_id: str, tenant_location_id: str,
                                   provider: str = "square") -> dict | None:
    res = (get_client().table("location_provider_bindings").select("*")
           .eq("tenant_id", tenant_id)
           .eq("tenant_location_id", tenant_location_id)
           .eq("provider", provider).limit(1).execute())
    return (res.data or [None])[0]


# ---------------------------------------------------------------------------
# call_slot_offers (migration 016) — what availability actually offered
# ---------------------------------------------------------------------------

async def insert_slot_offers(rows: list[dict]) -> list:
    if not rows:
        return []
    res = get_client().table("call_slot_offers").insert(rows).execute()
    return res.data or []


async def get_slot_offer(vapi_call_id: str, slot_ref: str, tenant_id: str) -> dict | None:
    """Tenant-scoped as well as call-scoped: a slot ref is only meaningful inside
    the call that issued it, and only for the tenant that owns that call."""
    if not (vapi_call_id and slot_ref and tenant_id):
        return None
    res = (get_client().table("call_slot_offers").select("*")
           .eq("vapi_call_id", vapi_call_id).eq("slot_ref", slot_ref)
           .eq("tenant_id", tenant_id).limit(1).execute())
    return (res.data or [None])[0]


async def count_slot_offers(vapi_call_id: str) -> int:
    res = (get_client().table("call_slot_offers").select("slot_ref", count="exact")
           .eq("vapi_call_id", vapi_call_id).execute())
    return res.count or 0


async def claim_slot_offer(vapi_call_id: str, slot_ref: str, tenant_id: str) -> bool:
    """Take a slot for a booking attempt. True only if WE took it.

    `consumed_at IS NULL` is in the predicate, so this is the destructive
    boundary: two concurrent tool calls holding the same slot_ref compete here and
    only one can pass. Before this existed the pair was read-then-act — both saw
    NULL, both reached CreateBooking, and the random idempotency key meant Square
    made two bookings.

    booking_id stays NULL, which is what distinguishes "claimed, in flight" from
    "booked" without needing another column.
    """
    res = (get_client().table("call_slot_offers")
           .update({"consumed_at": _now_iso()})
           .eq("vapi_call_id", vapi_call_id).eq("slot_ref", slot_ref)
           .eq("tenant_id", tenant_id).is_("consumed_at", "null").execute())
    return len(res.data or []) == 1


async def release_slot_offer(vapi_call_id: str, slot_ref: str) -> None:
    """Hand a claimed slot back after a DEFINITIVE provider rejection.

    Guarded on booking_id IS NULL so a successful booking can never be un-consumed
    by a late release.
    """
    (get_client().table("call_slot_offers").update({"consumed_at": None})
     .eq("vapi_call_id", vapi_call_id).eq("slot_ref", slot_ref)
     .is_("booking_id", "null").execute())


async def consume_slot_offer(vapi_call_id: str, slot_ref: str, booking_id: str) -> dict:
    """Finalize a claimed slot with the booking Square actually made.

    Conditional on booking_id IS NULL so a retry cannot overwrite the id of an
    existing booking with a different one.
    """
    res = (get_client().table("call_slot_offers")
           .update({"consumed_at": _now_iso(), "booking_id": booking_id})
           .eq("vapi_call_id", vapi_call_id).eq("slot_ref", slot_ref)
           .is_("booking_id", "null").execute())
    return (res.data or [{}])[0]


async def delete_slot_offers(vapi_call_id: str) -> None:
    if not vapi_call_id:
        return
    get_client().table("call_slot_offers").delete().eq("vapi_call_id", vapi_call_id).execute()


async def purge_expired_slot_offers(now_iso: str) -> int:
    res = get_client().table("call_slot_offers").delete().lt("expires_at", now_iso).execute()
    return len(res.data or [])
