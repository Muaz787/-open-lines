"""
W7A — retrieval primitives for routing a Square webhook to ONE tenant location.

WHY THIS MODULE EXISTS SEPARATELY
The existing helper get_tenant_by_square_merchant_id() answers "which tenant owns
this merchant?" with `.limit(1)` and no ORDER BY. On a merchant that maps to more
than one tenant it returns whichever row Postgres hands back first, and the caller
then mutates that tenant. That is not a lookup, it is a coin toss with side
effects.

W7's rule is that a merchant identifies a CANDIDATE SET and the provider location
identifies the exact binding. So retrieval here never selects: it returns
everything that matched and lets the pure resolver decide, including deciding to
refuse.

These functions are RETRIEVAL ONLY. No filtering policy lives here beyond the
provider and id predicates that the database can express — eligibility is the
resolver's job, and keeping it there is what makes the whole decision testable
without a database.

Nothing in this module is wired into a webhook handler. W7A is deliberately
unused by production code paths.
"""
from __future__ import annotations

import logging

from db.supabase import get_client

logger = logging.getLogger(__name__)

PROVIDER_SQUARE = "square"


async def list_tenants_by_square_merchant_id(merchant_id: str) -> list[dict]:
    """EVERY tenant carrying this Square merchant id. Never one, never ordered.

    The empty list is a real answer, not an error: production currently has an
    appointment-enabled tenant whose square_merchant_id is NULL, so "no tenant
    claims this merchant" is an ordinary state the resolver has to handle rather
    than a fault.
    """
    if not merchant_id:
        return []
    res = (get_client().table("tenants").select("*")
           .eq("square_merchant_id", merchant_id).execute())
    return res.data or []


async def list_square_bindings_for_location(provider_location_id: str) -> list[dict]:
    """EVERY square binding pointing at this provider location id.

    Deliberately unfiltered beyond provider and id. A binding that is inactive,
    unbound or owned by a tenant with appointments switched off is still returned,
    because the resolver needs to distinguish "we have never heard of this
    location" from "we know it and it is switched off" -- those are different
    operator problems with different fixes.
    """
    if not provider_location_id:
        return []
    res = (get_client().table("location_provider_bindings").select("*")
           .eq("provider", PROVIDER_SQUARE)
           .eq("provider_location_id", provider_location_id).execute())
    return res.data or []


async def load_location_candidates(provider_location_id: str) -> list[dict]:
    """Bundle each binding with the location and tenant needed to judge it.

    Returns [{"binding": {...}, "location": {...} | None, "tenant": {...} | None}].

    The bundle exists so the resolver can be a pure function over complete
    evidence. A missing location or tenant is represented as None rather than
    dropped, because a binding pointing at a row that no longer exists is an
    integrity signal the resolver should see, not a record to quietly discard.
    """
    bindings = await list_square_bindings_for_location(provider_location_id)
    if not bindings:
        return []

    loc_ids = sorted({str(b.get("tenant_location_id")) for b in bindings
                      if b.get("tenant_location_id")})
    tenant_ids = sorted({str(b.get("tenant_id")) for b in bindings if b.get("tenant_id")})

    locations: dict[str, dict] = {}
    if loc_ids:
        res = (get_client().table("tenant_locations").select("*")
               .in_("id", loc_ids).execute())
        locations = {str(r["id"]): r for r in (res.data or [])}
        tenant_ids = sorted(set(tenant_ids) | {str(r["tenant_id"]) for r in (res.data or [])})

    tenants: dict[str, dict] = {}
    if tenant_ids:
        res = (get_client().table("tenants").select("*").in_("id", tenant_ids).execute())
        tenants = {str(r["id"]): r for r in (res.data or [])}

    out = []
    for b in bindings:
        loc = locations.get(str(b.get("tenant_location_id") or ""))
        # The tenant is taken from the LOCATION when one exists: the location is
        # what the appointment will be stamped with, so its owner is the one that
        # matters. binding.tenant_id is cross-checked by the resolver.
        owner = str((loc or {}).get("tenant_id") or b.get("tenant_id") or "")
        out.append({"binding": b, "location": loc, "tenant": tenants.get(owner)})
    return out
