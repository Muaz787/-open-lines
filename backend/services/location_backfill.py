"""
W1 backfill: give every existing tenant exactly one default business location, and
record the Square location they already use as a provider binding.

WHAT THIS DOES NOT DO, DELIBERATELY:
  * It never calls Square. Every value written comes from a column that already
    exists on the tenant row. Fields we cannot know without a provider round-trip
    (the location's name at Square, its status) stay NULL rather than being guessed.
  * It never writes to `tenants`. tenants.square_location_id keeps its current
    value and keeps being authoritative; this records it, it does not repoint it.
  * It never picks a location. There is no locations[0] here — the only Square id
    it can write is the one already stored on the tenant.
  * It changes no behaviour. Nothing reads these rows as of W1.

IDEMPOTENCY is by natural key, checked before every insert, and backed by unique
indexes in migration 012 so a race loses at the database rather than duplicating:
  * one default per tenant   -> tenant_locations_one_default_idx (partial unique)
  * one slug per tenant      -> tenant_locations_tenant_slug_idx
  * one provider location    -> lpb_tenant_provider_location_idx
Running it a hundred times leaves the same rows as running it once.
"""
from __future__ import annotations

import logging
import re

from db import locations as db_loc

logger = logging.getLogger(__name__)

# The default location's slug. Constant rather than derived from the business name:
# it must be stable for the life of the tenant, and a name-derived slug would invite
# a rename to change it. Multi-location tenants get real slugs (cork, dublin, …) in
# W2 when a human names them.
DEFAULT_SLUG = "main"

SQUARE = "square"


def _slugify(name: str) -> str:
    """Same rules as services.provisioning._slugify — kept local so the backfill has
    no import dependency on the provisioning module."""
    slug = (name or "").lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug


def default_location_payload(tenant: dict) -> dict:
    """The row we would create for a tenant that has none.

    Every field is either carried from an existing column or a safe constant.
    Nothing is invented:
      * name       <- business_name (what a caller would be told)
      * country    <- tenants.country
      * timezone   <- tenants.calendar_timezone
      * address    <- omitted entirely; tenants has no structured address
      * hours      <- omitted; null means "inherit the tenant", so there is exactly
                      one source of truth for hours until W4 changes that
      * booking_enabled = True. This location IS the tenant's current working
        single-location setup, so it must stay bookable. Defaulting it to False
        would make W4's fail-closed rule silently break every existing tenant the
        day it ships.
    """
    name = (tenant.get("business_name") or "").strip() or "Main location"
    return {
        "slug": DEFAULT_SLUG,
        "name": name,
        "aliases": [],
        "country": tenant.get("country") or None,
        "timezone": tenant.get("calendar_timezone") or None,
        "booking_enabled": True,
        "is_default": True,
        "active": True,
    }


def square_binding_payload(tenant: dict, tenant_location_id: str) -> dict | None:
    """The Square binding for a tenant that already has a square_location_id.

    Returns None when the tenant has no Square location — no tenant ever gets a
    fabricated binding.

    provider_timezone and provider_currency are carried from the columns Square
    populated at connect time (square_location_timezone / square_currency), so they
    are known facts, not guesses. provider_location_name and provider_status are
    left NULL: they genuinely cannot be known without calling Square, and W2's sync
    is what fills them.
    """
    square_location_id = (tenant.get("square_location_id") or "").strip()
    if not square_location_id:
        return None
    return {
        "tenant_location_id": tenant_location_id,
        "provider": SQUARE,
        "provider_location_id": square_location_id,
        "provider_location_name": None,     # unknown without calling Square
        "provider_timezone": tenant.get("square_location_timezone") or None,
        "provider_currency": tenant.get("square_currency") or None,
        "provider_status": None,            # unknown without calling Square
        "capabilities": None,
        "raw": None,
        "last_seen_at": None,               # never confirmed against the provider
    }


async def backfill_tenant(tenant: dict, dry_run: bool = True) -> dict:
    """Backfill one tenant. Safe to call repeatedly.

    Returns a summary of what was (or would be) done:
        {"tenant_id", "location": created|exists|would_create,
         "binding": created|exists|skipped_no_square|would_create}
    """
    tenant_id = str(tenant.get("id") or "")
    out = {"tenant_id": tenant_id, "location": "", "binding": ""}
    if not tenant_id:
        out["location"] = "skipped_no_id"
        out["binding"] = "skipped_no_id"
        return out

    # --- 1. exactly one default location -----------------------------------
    existing = await db_loc.get_default_location(tenant_id)
    if existing:
        location = existing
        out["location"] = "exists"
    else:
        payload = default_location_payload(tenant)
        if dry_run:
            out["location"] = "would_create"
            # Ask the same question the real path asks, so a whitespace-only
            # square_location_id is reported as "no square" here too. A dry run
            # that predicts something different from what --apply does is worse
            # than no dry run at all.
            has_square = square_binding_payload(tenant, "pending") is not None
            out["binding"] = "would_create" if has_square else "skipped_no_square"
            return out
        location = await db_loc.insert_location(tenant_id, payload)
        out["location"] = "created"
        logger.info("location_backfill: created default location for tenant %s", tenant_id)

    location_id = str(location.get("id") or "")
    if not location_id:
        # Insert returned nothing usable; do not attempt a binding that would be
        # orphaned. Reported rather than swallowed.
        out["binding"] = "skipped_no_location_id"
        return out

    # --- 2. the Square binding, only if the tenant already has one ----------
    binding_payload = square_binding_payload(tenant, location_id)
    if binding_payload is None:
        out["binding"] = "skipped_no_square"
        return out

    already = await db_loc.get_binding(
        tenant_id, SQUARE, binding_payload["provider_location_id"])
    if already:
        out["binding"] = "exists"
        return out

    if dry_run:
        out["binding"] = "would_create"
        return out

    await db_loc.insert_binding(tenant_id, binding_payload)
    out["binding"] = "created"
    logger.info("location_backfill: created square binding for tenant %s", tenant_id)
    return out


async def backfill_all(dry_run: bool = True) -> dict:
    """Backfill every tenant. Idempotent; dry_run reports without writing."""
    tenants = await db_loc.list_all_tenants_for_backfill()
    results = []
    for tenant in tenants:
        try:
            results.append(await backfill_tenant(tenant, dry_run=dry_run))
        except Exception as e:
            # One bad tenant must not abort the run. Re-running picks it up again.
            logger.error("location_backfill: tenant %s failed: %s", tenant.get("id"), e)
            results.append({"tenant_id": str(tenant.get("id") or ""),
                            "location": "error", "binding": "error", "error": str(e)[:200]})

    def _count(key: str, value: str) -> int:
        return sum(1 for r in results if r.get(key) == value)

    summary = {
        "dry_run": dry_run,
        "tenants": len(tenants),
        "locations_created": _count("location", "created"),
        "locations_existing": _count("location", "exists"),
        "locations_would_create": _count("location", "would_create"),
        "bindings_created": _count("binding", "created"),
        "bindings_existing": _count("binding", "exists"),
        "bindings_would_create": _count("binding", "would_create"),
        "bindings_skipped_no_square": _count("binding", "skipped_no_square"),
        "errors": _count("location", "error"),
        "results": results,
    }
    logger.info("location_backfill: %s", {k: v for k, v in summary.items() if k != "results"})
    return summary
