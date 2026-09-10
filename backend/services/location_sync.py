"""
W2 — discover and persist EVERY Square location a merchant has.

Runs on both Square entry points, because both already funnel through
square_booking.sync(): the OAuth callback fires it as a background task, and
POST /square-connect/appointments/sync/{tid} awaits it.

DARK. Nothing reads what this writes. tenants.square_location_id remains the
authoritative pointer for every runtime path — availability, booking, deposits,
prompts and phone routing are untouched by W2.

THREE RULES THIS MODULE WILL NOT BREAK
--------------------------------------
1. Identity is the Square location id. Never the name, never the address. Names
   are recorded as last-seen facts for drift detection and nothing else.

2. It never creates a tenant_location. Discovered locations are persisted as
   bindings with tenant_location_id = NULL — the nullable FK exists for exactly
   this state. Deciding that a Square location is a new *business* location, and
   what to call it, is a human judgement: Square's names are the merchant's own
   labels, and adopting them automatically is how a tenant called "Shahid Real
   Estate" silently acquires a showroom called "Dani Cork". The one exception is
   not an exception at all — see LEGACY LINK below.

3. It never writes to the tenants table and never touches tenant_locations.name.
   A user-facing name may have been customised; provider drift is reported, not
   applied.

LEGACY LINK
-----------
The binding whose provider_location_id equals tenants.square_location_id is
attached to the tenant's existing default location. That is not a new decision —
it is following the pointer runtime already uses, so the model agrees with
production rather than inventing a second opinion. It is deliberately the ONLY
automatic mapping, and it depends on the stored pointer, never on list order:
there is no locations[0] anywhere in this module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import locations as db_loc

logger = logging.getLogger(__name__)

SQUARE = "square"

# Our own marker for a binding whose Square location stopped being returned.
# Square itself only ever reports ACTIVE or INACTIVE, so this cannot collide.
# History is never deleted — a booking may reference it.
STATUS_MISSING = "MISSING"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def binding_metadata(location: dict) -> dict:
    """Provider facts for one Square location. Everything here is descriptive;
    none of it is identity."""
    return {
        "provider_location_name": location.get("name") or None,
        "provider_timezone": location.get("timezone") or None,
        "provider_currency": location.get("currency") or None,
        "provider_status": location.get("status") or None,
        "capabilities": location.get("capabilities") or None,
        "raw": location or None,
        "last_seen_at": _now_iso(),
    }


async def sync_square_locations(
    tenant: dict, locations: list[dict], dry_run: bool = False,
) -> dict:
    """Persist every Square location as a provider binding. Idempotent.

    `locations` is passed in rather than fetched here so the caller can reuse the
    list it already has — one Square round trip, not two.
    """
    tenant_id = str(tenant.get("id") or "")
    result = {
        "tenant_id": tenant_id, "dry_run": dry_run,
        "returned": len(locations or []),
        "created": [], "updated": [], "unmapped": [], "missing": [],
        "attached_to_default": None, "name_mismatch": None, "errors": [],
    }
    if not tenant_id:
        result["errors"].append("no_tenant_id")
        return result

    legacy_id = (tenant.get("square_location_id") or "").strip()

    default_loc = await db_loc.get_default_location(tenant_id)
    default_loc_id = str((default_loc or {}).get("id") or "")

    existing = {b.get("provider_location_id"): b
                for b in await db_loc.list_bindings(tenant_id, provider=SQUARE)}

    seen: set[str] = set()
    # Which Square location is bound to the default tenant_location once this sync
    # finishes — whether we attached it just now or W1 already did. Drift detection
    # must key off this, not off "did I attach it during this run": in production the
    # attachment already exists, so the narrower test silently reported no drift.
    bound_to_default: str | None = None

    for location in (locations or []):
        # Identity, and the only thing we key on.
        provider_location_id = (location.get("id") or "").strip()
        if not provider_location_id:
            result["errors"].append("location_without_id")
            continue
        seen.add(provider_location_id)

        meta = binding_metadata(location)
        prior = existing.get(provider_location_id)

        # The legacy link: this is the location runtime already uses.
        is_legacy = bool(legacy_id) and provider_location_id == legacy_id

        if prior:
            update = dict(meta)
            if default_loc_id and prior.get("tenant_location_id") == default_loc_id:
                # Already mapped to the default by W1 or an earlier sync.
                bound_to_default = provider_location_id
            # Attach to the default only if the binding is still unmapped AND it
            # is the one the tenant row points at. An existing mapping is never
            # re-pointed here — remapping is an explicit human action.
            if (not prior.get("tenant_location_id")) and is_legacy and default_loc_id:
                update["tenant_location_id"] = default_loc_id
                result["attached_to_default"] = provider_location_id
                bound_to_default = provider_location_id
            if not dry_run:
                await db_loc.update_binding(tenant_id, prior["id"], update)
            result["updated"].append(provider_location_id)
        else:
            payload = {
                "tenant_location_id": default_loc_id if (is_legacy and default_loc_id) else None,
                "provider": SQUARE,
                "provider_location_id": provider_location_id,
                **meta,
            }
            if is_legacy and default_loc_id:
                result["attached_to_default"] = provider_location_id
                bound_to_default = provider_location_id
            if not dry_run:
                await db_loc.insert_binding(tenant_id, payload)
            result["created"].append(provider_location_id)

        # Anything not on the legacy pointer stays unmapped: discovered, recorded,
        # and deliberately not turned into a business location by a machine.
        if not (is_legacy and default_loc_id):
            if not (prior and prior.get("tenant_location_id")):
                result["unmapped"].append(provider_location_id)

    # --- locations that stopped coming back -------------------------------
    for provider_location_id, prior in existing.items():
        if provider_location_id in seen:
            continue
        if prior.get("provider_status") == STATUS_MISSING:
            result["missing"].append(provider_location_id)
            continue
        # Mark, never delete. last_seen_at is left alone on purpose: it should keep
        # saying when we last actually saw it, which is the useful fact.
        if not dry_run:
            await db_loc.update_binding(
                tenant_id, prior["id"], {"provider_status": STATUS_MISSING})
        result["missing"].append(provider_location_id)
        logger.warning(
            "location_sync: square location %s no longer returned for tenant %s — "
            "marked %s, binding retained", provider_location_id, tenant_id, STATUS_MISSING)

    # --- drift report: provider name vs the name we show the caller --------
    # Reported, never applied. The tenant-facing name may have been customised,
    # and Square's label is the merchant's own, not a business identity.
    result["bound_to_default"] = bound_to_default
    if default_loc and bound_to_default:
        provider_name = next(
            (l.get("name") for l in (locations or [])
             if (l.get("id") or "").strip() == bound_to_default), None)
        our_name = (default_loc.get("name") or "").strip()
        if provider_name and our_name and provider_name.strip().lower() != our_name.lower():
            result["name_mismatch"] = {
                "tenant_location_id": default_loc_id,
                "openlines_name": our_name,
                "square_name": provider_name,
            }
            logger.info(
                "location_sync: tenant %s default location is named %r while Square "
                "calls it %r — recording the provider name only, tenant-facing name "
                "left unchanged", tenant_id, our_name, provider_name)

    logger.info(
        "location_sync: tenant %s — %d returned, %d created, %d updated, "
        "%d unmapped, %d missing%s",
        tenant_id, result["returned"], len(result["created"]), len(result["updated"]),
        len(result["unmapped"]), len(result["missing"]),
        " (dry run)" if dry_run else "")
    return result
