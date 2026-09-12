"""Confirming a tenant's compliance country (W9G Stage B).

`tenants.business_country_code` is the ONLY compliance-country authority. It exists
because nothing else in the row qualifies: `tenants.country` is derived by the website
analyzer and is NULL for several production tenants, the billing country describes who
pays, Square's country describes a payment processor's account, and a phone prefix
describes a number we may be about to replace. A regulator's question -- who is this
business and where is it established -- cannot be answered by a scrape.

So this module only ever writes a value that arrived from an explicit human action,
and it will not infer one from anything already on the row.

CHANGING A CONFIRMED COUNTRY IS NOT AN UPDATE. Once regulatory resources exist, the
country is baked into a filing with a regulator and into provider resources that live
in the tenant's sub-account. Changing the column would leave the filing describing a
different country from the tenant, so it fails closed and asks for a separate
workflow -- there is deliberately no cascade.
"""
from __future__ import annotations

import logging
import re

from db.supabase import get_client

logger = logging.getLogger(__name__)

OK = "ok"
UNCHANGED = "unchanged"
INVALID = "invalid_country_code"
BLOCKED_REGULATORY = "blocked_regulatory_resources_exist"
BLOCKED_REGULATED_NUMBER = "blocked_regulated_number_exists"
NOT_FOUND = "tenant_not_found"

_ISO = re.compile(r"^[A-Za-z]{2}$")


def normalize(code: str) -> str:
    """'ie' -> 'IE'. Returns '' when the input is not a two-letter code.

    The database CHECK requires uppercase, so normalising here is what lets a UI
    accept what a person actually types without the column's rule being relaxed.
    """
    value = str(code or "").strip()
    return value.upper() if _ISO.match(value) else ""


async def confirm(tenant_id: str, iso_country: str) -> dict:
    """Record an explicitly confirmed compliance country.

    Idempotent: confirming the value already stored is UNCHANGED, not a conflict, so
    a UI that re-posts the same answer does not need special handling.
    """
    code = normalize(iso_country)
    if not code:
        return {"status": INVALID, "business_country_code": None,
                "detail": "expected a two-letter ISO 3166-1 alpha-2 code"}

    client = get_client()
    rows = (client.table("tenants").select("id, business_country_code")
            .eq("id", tenant_id).limit(1).execute().data or [])
    if not rows:
        return {"status": NOT_FOUND, "business_country_code": None}
    current = rows[0].get("business_country_code")

    if current == code:
        return {"status": UNCHANGED, "business_country_code": code}

    if current:
        # A change, not a first confirmation. Anything already filed pins it.
        profiles = (client.table("tenant_regulatory_profiles").select("id")
                    .eq("tenant_id", tenant_id).limit(1).execute().data or [])
        addresses = (client.table("tenant_regulatory_addresses").select("id")
                     .eq("tenant_id", tenant_id).limit(1).execute().data or [])
        if profiles or addresses:
            logger.warning("Refused business_country_code change for tenant %s: "
                           "regulatory resources exist", tenant_id)
            return {"status": BLOCKED_REGULATORY, "business_country_code": current,
                    "detail": "a regulatory address or profile already exists"}
        numbers = (client.table("tenant_phone_numbers")
                   .select("id").eq("tenant_id", tenant_id)
                   .not_.is_("regulatory_profile_id", "null").limit(1)
                   .execute().data or [])
        if numbers:
            return {"status": BLOCKED_REGULATED_NUMBER,
                    "business_country_code": current,
                    "detail": "a regulated number is bound to this tenant"}

    client.table("tenants").update({"business_country_code": code}) \
        .eq("id", tenant_id).execute()
    # Country is not sensitive, and recording the transition is what makes an
    # explicit confirmation auditable.
    logger.info("business_country_code confirmed for tenant %s: %s -> %s",
                tenant_id, current or "NULL", code)
    return {"status": OK, "business_country_code": code, "previous": current}


async def get_confirmed(tenant_id: str) -> str | None:
    rows = (get_client().table("tenants").select("business_country_code")
            .eq("id", tenant_id).limit(1).execute().data or [])
    return (rows[0].get("business_country_code") if rows else None) or None
