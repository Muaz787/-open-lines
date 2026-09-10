"""
W2.5 — turn a discovered provider location into an intentional OpenLines location.

W2 records what Square has. This turns one of those records into a business
location, and only ever because an operator asked for that specific location by
its provider id. Nothing here runs automatically, on a schedule, or as a side
effect of a sync.

LEGACY-AUTHORITY SAFETY
-----------------------
`tenants.square_location_id` is still what every runtime path reads. So the
default location may ONLY ever be the provider location that pointer names.

That rule is enforced by construction rather than by validation: there is no
"make this the default" parameter anywhere in this module. Which adoption becomes
the default is *derived* from the legacy pointer, so an operator cannot choose a
different one — not with a flag, not with a payload field, not by ordering their
calls. Re-pointing the default is a runtime-cutover operation and belongs to the
phase that retires the legacy pointer.

This module never writes to `tenants`.

TWO STARTING STATES, BOTH SUPPORTED
-----------------------------------
A. W1-backfilled tenant — already has a default (`DANI / main`). Adopting the
   legacy location reshapes that existing row in place.
B. Tenant created after migration 012 — has zero locations, because
   `provision_tenant()` was never taught to make one. Adopting the legacy
   location creates the first one, as the default.

State B is not hypothetical: every tenant onboarded from now on starts there.
"""
from __future__ import annotations

import logging

from db import locations as db_loc
from services import location_normalization as norm
from services.location_sync import SQUARE, STATUS_MISSING

logger = logging.getLogger(__name__)


class AdoptionError(Exception):
    """Refused. `code` is a stable machine-readable reason for the API layer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def derive_slug(provider_name: str, business_name: str = "") -> str:
    """'Dani Cork' for a tenant called 'DANI' -> 'cork'.

    Delegates to services/location_normalization so adoption and the W4 resolver
    cannot drift apart on what a location name reduces to. Re-exported here because
    it is part of this module's public surface.
    """
    return norm.derive_slug(provider_name, business_name)


def location_payload(
    provider_name: str, *, business_name: str, provider_timezone: str | None,
    tenant_country: str | None, is_default: bool,
    name: str | None = None, slug: str | None = None,
    aliases: list[str] | None = None, timezone: str | None = None,
) -> dict:
    """The row an adoption would create. Operator overrides win over derivation.

    `country` comes from the TENANT, never from the provider's address: addresses
    are display data and may be placeholders, so deriving a country from one can
    stamp 'CA' on a location called Cork.
    """
    display = (name or provider_name or "").strip()
    return {
        "slug": (slug or derive_slug(provider_name, business_name)).strip(),
        "name": display,
        "aliases": aliases if aliases is not None else [],
        "country": tenant_country or None,
        "timezone": (timezone or provider_timezone) or None,
        "booking_enabled": False,   # W4 introduces activation; nothing enforces it yet
        "is_default": is_default,
        "active": True,
    }


async def _require_binding(tenant_id: str, provider_location_id: str) -> dict:
    binding = await db_loc.get_binding(tenant_id, SQUARE, provider_location_id)
    if not binding:
        raise AdoptionError(
            "binding_not_found",
            f"No {SQUARE} location {provider_location_id} has been discovered for this "
            "tenant. Run a Square sync first.")
    if binding.get("provider_status") == STATUS_MISSING:
        raise AdoptionError(
            "provider_location_missing",
            f"{provider_location_id} is no longer returned by Square. It cannot be "
            "adopted; the binding is retained for history.")
    return binding


async def adopt_location(
    tenant: dict, provider_location_id: str, *,
    name: str | None = None, slug: str | None = None,
    aliases: list[str] | None = None, timezone: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Adopt ONE discovered Square location. Idempotent.

    Whether this becomes the tenant's default is derived from
    tenants.square_location_id and is not selectable.
    """
    tenant_id = str(tenant.get("id") or "")
    if not tenant_id:
        raise AdoptionError("no_tenant_id", "Tenant has no id.")
    provider_location_id = (provider_location_id or "").strip()
    if not provider_location_id:
        raise AdoptionError("no_provider_location_id", "A Square location id is required.")

    binding = await _require_binding(tenant_id, provider_location_id)

    # Already adopted -> no-op. Returning the existing location keeps repeated
    # operator calls (and retries) harmless.
    if binding.get("tenant_location_id"):
        existing = await db_loc.get_location_by_id(tenant_id, binding["tenant_location_id"])
        return {"status": "already_adopted", "tenant_location": existing,
                "binding_id": binding["id"], "provider_location_id": provider_location_id}

    legacy_pointer = (tenant.get("square_location_id") or "").strip()
    is_legacy = bool(legacy_pointer) and provider_location_id == legacy_pointer
    default_loc = await db_loc.get_default_location(tenant_id)

    provider_name = binding.get("provider_location_name") or provider_location_id
    business_name = tenant.get("business_name") or ""

    # ---- reshape the existing default (state A) --------------------------
    if is_legacy and default_loc:
        payload = location_payload(
            provider_name, business_name=business_name,
            provider_timezone=binding.get("provider_timezone"),
            tenant_country=tenant.get("country"), is_default=True,
            name=name, slug=slug, aliases=aliases, timezone=timezone)
        await _assert_slug_free(tenant_id, payload["slug"], exclude_id=default_loc["id"])

        update = {k: v for k, v in payload.items() if k not in ("is_default",)}
        was_bookable = bool(default_loc.get("booking_enabled"))
        result = {
            "status": "adopted_into_default", "provider_location_id": provider_location_id,
            "binding_id": binding["id"], "tenant_location_id": default_loc["id"],
            "previous": {"name": default_loc.get("name"), "slug": default_loc.get("slug")},
            "payload": update, "dry_run": dry_run,
        }
        # W1 backfilled defaults are booking_enabled=true so existing single-location
        # tenants keep working. Adoption sets false per the approved W2.5 rule; that is
        # inert today but WILL matter once W4 enforces it, so it is surfaced loudly
        # rather than buried in a diff.
        if was_bookable:
            result["warning"] = (
                "booking_enabled changed true -> false. Harmless today (nothing reads "
                "it) but this location must be explicitly activated in W4.")
        if dry_run:
            return result
        await db_loc.update_location(tenant_id, default_loc["id"], update)
        await db_loc.update_binding(tenant_id, binding["id"],
                                    {"tenant_location_id": default_loc["id"]})
        logger.info("location_adoption: tenant %s default reshaped to %r (%s)",
                    tenant_id, update["name"], provider_location_id)
        return result

    # ---- create a location (state B default, or an additional location) ---
    becomes_default = bool(is_legacy and default_loc is None)
    payload = location_payload(
        provider_name, business_name=business_name,
        provider_timezone=binding.get("provider_timezone"),
        tenant_country=tenant.get("country"), is_default=becomes_default,
        name=name, slug=slug, aliases=aliases, timezone=timezone)
    await _assert_slug_free(tenant_id, payload["slug"])

    result = {
        "status": "adopted_as_default" if becomes_default else "adopted",
        "provider_location_id": provider_location_id, "binding_id": binding["id"],
        "payload": payload, "dry_run": dry_run,
    }
    if dry_run:
        return result

    created = await db_loc.insert_location(tenant_id, payload)
    location_id = str(created.get("id") or "")
    if not location_id:
        raise AdoptionError("location_insert_failed", "Location row was not created.")

    # Two writes, and PostgREST gives us no transaction. If the binding update
    # fails we must not leave a location that looks adoptable but is bound to
    # nothing — so undo the insert and report the failure honestly.
    try:
        await db_loc.update_binding(tenant_id, binding["id"],
                                    {"tenant_location_id": location_id})
    except Exception as e:
        logger.error("location_adoption: binding update failed for tenant %s (%s); "
                     "rolling back location %s: %s", tenant_id, provider_location_id,
                     location_id, e)
        try:
            await db_loc.delete_location(tenant_id, location_id)
        except Exception as cleanup_error:
            logger.error("location_adoption: ROLLBACK FAILED, orphan location %s on "
                         "tenant %s: %s", location_id, tenant_id, cleanup_error)
            raise AdoptionError(
                "rollback_failed",
                f"Binding update failed and the location {location_id} could not be "
                "removed. Manual cleanup required.") from e
        raise AdoptionError(
            "binding_update_failed",
            "Could not attach the binding; the new location was rolled back.") from e

    result["tenant_location_id"] = location_id
    result["tenant_location"] = created
    logger.info("location_adoption: tenant %s adopted %s as %r (default=%s)",
                tenant_id, provider_location_id, payload["name"], becomes_default)
    return result


async def _assert_slug_free(tenant_id: str, slug: str, exclude_id: str | None = None) -> None:
    """Refuse a collision loudly. A silent 'cork-2' would be a machine key nobody
    chose, quietly diverging from what the operator believes they created."""
    if not slug:
        raise AdoptionError("empty_slug", "Could not derive a slug; supply one explicitly.")
    clash = await db_loc.get_location_by_slug(tenant_id, slug)
    if clash and str(clash.get("id")) != str(exclude_id or ""):
        raise AdoptionError(
            "slug_conflict",
            f"This tenant already has a location with slug {slug!r}. Supply a "
            "different slug explicitly.")


async def detach_location(
    tenant: dict, provider_location_id: str, dry_run: bool = False,
) -> dict:
    """Undo an adoption: unbind, and deactivate the location.

    Never deletes. Once W6 lands, an appointment may reference this location, and a
    deleted row would orphan history. Deactivation is reversible; deletion is not.
    """
    tenant_id = str(tenant.get("id") or "")
    binding = await _require_binding(tenant_id, provider_location_id)
    location_id = binding.get("tenant_location_id")
    if not location_id:
        return {"status": "not_adopted", "provider_location_id": provider_location_id}

    location = await db_loc.get_location_by_id(tenant_id, location_id)
    if location and location.get("is_default"):
        raise AdoptionError(
            "cannot_detach_default",
            "The default location is what tenants.square_location_id points at. "
            "Detaching it belongs to the runtime-cutover phase.")

    result = {"status": "detached", "provider_location_id": provider_location_id,
              "tenant_location_id": location_id, "dry_run": dry_run}
    if dry_run:
        return result

    await db_loc.update_binding(tenant_id, binding["id"], {"tenant_location_id": None})
    await db_loc.update_location(tenant_id, location_id, {"active": False})
    logger.info("location_adoption: tenant %s detached %s (location %s deactivated)",
                tenant_id, provider_location_id, location_id)
    return result


async def review(tenant: dict) -> dict:
    """Everything an operator needs before deciding: adopted locations, discovered
    but unadopted bindings, and which one the legacy pointer names."""
    tenant_id = str(tenant.get("id") or "")
    legacy_pointer = (tenant.get("square_location_id") or "").strip()
    locs = await db_loc.list_locations(tenant_id)
    bindings = await db_loc.list_bindings(tenant_id, provider=SQUARE)
    by_id = {str(l["id"]): l for l in locs}

    discovered = []
    for b in bindings:
        loc = by_id.get(str(b.get("tenant_location_id") or ""))
        discovered.append({
            "provider_location_id": b.get("provider_location_id"),
            "provider_location_name": b.get("provider_location_name"),
            "provider_status": b.get("provider_status"),
            "adopted": bool(loc),
            "tenant_location_id": (loc or {}).get("id"),
            "openlines_name": (loc or {}).get("name"),
            "is_legacy_pointer": b.get("provider_location_id") == legacy_pointer,
            "adoptable": (not loc) and b.get("provider_status") != STATUS_MISSING,
        })
    return {
        "tenant_id": tenant_id,
        "legacy_square_location_id": legacy_pointer or None,
        "has_default_location": any(l.get("is_default") for l in locs),
        "locations": locs,
        "discovered": discovered,
    }
