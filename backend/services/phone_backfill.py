"""W9D backfill — represent each tenant's existing Twilio number as a
tenant_phone_numbers row (migration 027).

DRY RUN BY DEFAULT, matching services/location_backfill.py and the
NUMBER_RECLAIM_DRY_RUN convention: seeing what a migration would do must never
require risking that it does it.

WHAT IT REFUSES TO INVENT
  * activated_at comes from the provider's IncomingPhoneNumber.date_created, or it
    is NULL. tenants.created_at is NOT an acceptable stand-in -- signing up is not
    activating a phone line, and a fabricated activation date would later be read
    as though it had been observed. The row records which of the two happened in
    activated_at_source.
  * iso_country comes from Twilio Lookup v2, never from tenants.country (analyzer
    derived, NULL for 3 of 11 tenants) and never from the +1 prefix, which is
    Canada and the United States both.
  * provider_sid comes from the provider. There is no local copy to fall back on.

Anything it cannot establish is a SKIP with a reason, never a guess. Every skip is
reported, because a silently skipped tenant is a number this model does not know
about while the application starts trusting the model.

Prerequisite: migration 027 must already be applied.
Never writes to the tenants table. Never calls Twilio in a way that mutates.
"""
from __future__ import annotations

import logging

from db import phone_numbers as db_phone
from db.supabase import get_client
from services import phone_lifecycle as lifecycle
from services import telephony

logger = logging.getLogger(__name__)


def _mask(number: str) -> str:
    n = str(number or "")
    return f"{n[:5]}…{n[-3:]}" if len(n) > 8 else "…"


async def list_tenants_for_backfill() -> list[dict]:
    res = (get_client().table("tenants")
           .select("id, business_name, twilio_phone_number, twilio_subaccount_sid, "
                   "twilio_auth_token, vapi_phone_number_id")
           .execute())
    return res.data or []


async def plan_tenant(tenant: dict) -> dict:
    """Decide what row (if any) this tenant needs. READ-ONLY -- writes nothing,
    calls only read-only provider endpoints. Returns a result dict whose "action"
    is one of: skip | exists | propose."""
    tenant_id = str(tenant.get("id") or "")
    number = str(tenant.get("twilio_phone_number") or "").strip()
    sub_sid = str(tenant.get("twilio_subaccount_sid") or "").strip()
    sub_token = str(tenant.get("twilio_auth_token") or "").strip()

    def out(action: str, reason: str = "", **extra) -> dict:
        return {"tenant_id": tenant_id, "number": _mask(number),
                "action": action, "reason": reason, **extra}

    if not number:
        return out("skip", "no_number")
    if not sub_sid or not sub_token:
        return out("skip", "missing_twilio_credentials")

    # Already represented? The natural-key check plus tpn_one_current_permanent
    # is what makes this whole script safe to re-run.
    existing = await db_phone.list_for_tenant(
        tenant_id, purpose=lifecycle.PURPOSE_PERMANENT,
        statuses=lifecycle.CURRENT_PERMANENT_STATUSES)
    if existing:
        return out("exists", "already_backfilled")

    listing = await telephony.fetch_subaccount_numbers(sub_sid, sub_token)
    if not listing.ok:
        # We did not learn anything. A live number must never be written off
        # because a list call failed, so this is retryable, not a verdict.
        return out("skip", "provider_numbers_unavailable",
                   provider_error=listing.error_detail)
    if listing.is_empty:
        # DIFFERENT FACT, DIFFERENT REASON. Twilio answered and the account holds
        # nothing, so the scalar points at a number we do not own. That is a
        # permanent data inconsistency for someone to look at, not an outage to
        # retry -- and W9E found a real tenant in exactly this state.
        return out("skip", "provider_account_empty")

    matches = [r for r in listing.numbers
               if str(r.get("phone_number") or "").strip() == number]
    if not matches:
        return out("skip", "no_provider_match")
    if len(matches) > 1:
        return out("skip", "ambiguous_provider_match", matched=len(matches))

    match = matches[0]
    provider_sid = str(match.get("sid") or "").strip()
    provider_account_sid = str(match.get("account_sid") or "").strip()
    if not provider_sid:
        return out("skip", "provider_sid_missing")
    if provider_account_sid and provider_account_sid != sub_sid:
        # The number exists, but not in the account we believe owns it. Writing
        # our belief would make the ownership invariant a lie.
        return out("skip", "account_mismatch")

    iso_country = await telephony.lookup_iso_country(number)
    if not iso_country:
        return out("skip", "country_unresolved")

    date_created = match.get("date_created")
    activated_at = None
    activated_at_source = None
    if date_created is not None:
        activated_at = (date_created.isoformat() if hasattr(date_created, "isoformat")
                        else str(date_created))
        activated_at_source = "provider_date_created"

    row = {
        "tenant_id": tenant_id,
        "tenant_location_id": None,
        "regulatory_profile_id": None,
        "e164": number,
        "purpose": lifecycle.PURPOSE_PERMANENT,
        "status": lifecycle.STATUS_ACTIVE,
        "provider": "twilio",
        "provider_account_sid": provider_account_sid or sub_sid,
        "provider_sid": provider_sid,
        "iso_country": iso_country,
        "vapi_phone_number_id": (str(tenant.get("vapi_phone_number_id") or "") or None),
        "activated_at": activated_at,
        "activated_at_source": activated_at_source,
    }

    # The application-side mirror of the partial unique indexes. Catching a clash
    # here turns a mid-backfill 23505 into a reported skip.
    siblings = await db_phone.list_for_tenant(tenant_id)
    clash = lifecycle.live_conflict(siblings, row)
    if clash:
        return out("skip", f"uniqueness_conflict:{clash}")

    return out("propose", "", row=row)


async def backfill_tenant(tenant: dict, *, dry_run: bool = True) -> dict:
    result = await plan_tenant(tenant)
    result["dry_run"] = dry_run
    if result["action"] != "propose":
        return result
    if dry_run:
        return result                      # NOTHING is written in a dry run.
    inserted = await db_phone.insert_number(result["row"])
    result["action"] = "inserted"
    result["inserted_id"] = str((inserted or {}).get("id") or "")
    return result


async def backfill_all(*, dry_run: bool = True) -> dict:
    tenants = await list_tenants_for_backfill()
    results = [await backfill_tenant(t, dry_run=dry_run) for t in tenants]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    skips: dict[str, int] = {}
    for r in results:
        if r["action"] == "skip":
            skips[r["reason"]] = skips.get(r["reason"], 0) + 1
    return {"dry_run": dry_run, "tenants": len(tenants), "counts": counts,
            "skip_reasons": skips, "results": results}
