"""THE ONE PLACE a provisioned number is recorded (W9I-B).

WHY THIS MODULE EXISTS
W9I-A found that signup wrote the number ONLY to the legacy
`tenants.twilio_phone_number` scalar. `tenant_phone_numbers` -- the canonical
model migration 027 built, that routing prefers, and that the whole two-number
Irish migration depends on -- was populated exclusively by the W9F backfill. So
every signup since W9D has quietly added a tenant the canonical model does not
know about. Production happens to be clean (11 tenants, 7 numbers, an exact 1:1
match) only because no signup has happened since that backfill ran.

Two writers with different semantics is how that drift happened, so there is now
one:

    register_permanent()   the number exists at the provider -> record it
    mark_active()          the number is configured and answers -> make it routable

BOTH THE CANONICAL ROW AND THE LEGACY SCALAR ARE WRITTEN HERE, TOGETHER. The
scalar is not deprecated yet -- `get_tenant_by_phone` still falls back to it and
several call sites still read it -- so leaving it unwritten would break routing,
and letting some other code write it independently would recreate exactly the
divergence this module exists to end.

STATUS LIFECYCLE, AND WHY IT IS TWO STEPS
A row is inserted `provisioning` and only becomes `active` once the voice path is
configured. `provisioning` is deliberately excluded from
phone_lifecycle.ROUTABLE_STATUSES, so between the two calls an inbound caller
cannot be routed to a number whose webhook is not wired -- they would reach
silence. The legacy scalar is mirrored at the SAME moment the row becomes
routable, for the same reason: the scalar is a routing source.

NOTHING HERE TOUCHES THE PROVIDER. It records what the provider already did.
"""
from __future__ import annotations

import logging

from db import phone_numbers as db_phones
from db import supabase as db
from services import phone_lifecycle as lifecycle

logger = logging.getLogger(__name__)

OK = "ok"
CONFLICT = "live_conflict"


async def register_permanent(*, tenant_id: str, e164: str, provider_account_sid: str,
                             provider_sid: str, iso_country: str,
                             tenant_location_id: str | None = None,
                             regulatory_profile_id: str | None = None) -> dict:
    """Record a permanent number that now exists at the provider.

    Inserted as `provisioning`: it is ours, but it is not yet routable. Returns
    the existing row unchanged when this number is already recorded, so a retried
    provisioning attempt resumes instead of tripping the partial unique indexes.
    """
    existing = await db_phones.find_owned_by_e164(e164)
    if existing and str(existing.get("tenant_id")) == str(tenant_id):
        return {"status": OK, "row": existing, "created": False}
    if existing:
        # Another tenant holds this E.164. The index would refuse it anyway; say
        # so as a conflict rather than letting a 23505 escape.
        logger.error("Number already owned by a different tenant — refusing to "
                     "register it for tenant %s", tenant_id)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": "number_owned_by_another_tenant"}

    rows = await db_phones.list_for_tenant(tenant_id)
    candidate = {"purpose": lifecycle.PURPOSE_PERMANENT,
                 "status": lifecycle.STATUS_PROVISIONING}
    conflict = lifecycle.live_conflict(rows, candidate)
    if conflict:
        logger.error("Tenant %s already holds a live permanent number — refusing "
                     "a second (%s)", tenant_id, conflict)
        return {"status": CONFLICT, "row": None, "created": False,
                "detail": conflict}

    row = await db_phones.insert_number({
        "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
        "regulatory_profile_id": regulatory_profile_id,
        "e164": e164, "purpose": lifecycle.PURPOSE_PERMANENT,
        "status": lifecycle.STATUS_PROVISIONING,
        "provider": "twilio", "provider_account_sid": provider_account_sid,
        "provider_sid": provider_sid, "iso_country": iso_country})
    return {"status": OK, "row": row, "created": True}


async def mark_active(*, tenant_id: str, number_row_id: str, e164: str) -> dict:
    """The voice path is configured: make the number routable and mirror the scalar.

    The scalar is written HERE and nowhere else in the provisioning path, so the
    canonical row and the legacy pointer can never describe different numbers.
    """
    row = await db_phones.update_number(number_row_id,
                                       {"status": lifecycle.STATUS_ACTIVE})
    await db.update_tenant(tenant_id, {"twilio_phone_number": e164})
    return {"status": OK, "row": row}
