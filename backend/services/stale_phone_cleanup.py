"""W9F.1 — clear dangling phone pointers from a tenant whose number we provably
no longer own.

THE SITUATION THIS EXISTS FOR. W9F's canonical backfill found one tenant whose
`tenants.twilio_phone_number` named a number that had been released at Twilio while
the scalar was never cleared. Nothing owns it, the Vapi resource behind
`vapi_phone_number_id` is gone too, and yet `get_tenant_by_phone()` still resolves
that number to the tenant via the legacy scalar fallback.

WHAT THIS DOES NOT DO. It calls no provider mutation -- no Twilio release, no Vapi
delete. There is nothing left to release or delete; that is the whole premise. It
removes two dangling references and nothing else:

    tenants.twilio_phone_number  -> NULL
    tenants.vapi_phone_number_id -> NULL

It deliberately leaves alone:

    number_released_at     -- no authoritative release timestamp is obtainable.
                              Twilio keeps no record of a released number, and
                              inventing a plausible date is exactly the fabrication
                              tpn_activated_source_chk exists to forbid.
    twilio_subaccount_sid  -- the sub-account still exists and is perfectly valid.
                              Owning no number does not make an account stale.
    is_active, subscription_*, country, business_country_code -- none of these are
                              phone state.

EVERY PRECONDITION IS A REFUSAL, NOT A WARNING. A provider we could not reach, a
number that turns out to exist after all, a canonical row, another tenant's claim, or
a Vapi resource that is still live all stop the cleanup. "We could not establish it"
is never treated as "it is gone".
"""
from __future__ import annotations

import logging

from db.supabase import get_client
from services import telephony, vapi

logger = logging.getLogger(__name__)

#: Refusal reasons, exhaustive.
NO_SCALAR = "no_scalar_number"
MISSING_CREDS = "missing_twilio_credentials"
PROVIDER_UNAVAILABLE = "provider_numbers_unavailable"
PROVIDER_OWNS_NUMBERS = "provider_account_owns_numbers"
ORG_SEARCH_INCOMPLETE = "org_search_incomplete"
NUMBER_FOUND_IN_ORG = "number_found_in_organisation"
CANONICAL_ROW_EXISTS = "canonical_row_exists"
CANONICAL_CLAIMS_E164 = "canonical_row_claims_e164"
OTHER_TENANT_CLAIMS = "other_tenant_claims_e164"
VAPI_RESOURCE_EXISTS = "vapi_resource_exists"
VAPI_STATE_UNKNOWN = "vapi_state_unknown"


def _mask(number: str) -> str:
    n = str(number or "")
    return f"{n[:5]}…{n[-3:]}" if len(n) > 8 else "-"


async def evaluate_tenant(tenant: dict) -> dict:
    """Is this tenant's phone pointer conclusively stale? READ ONLY.

    Returns {"eligible": bool, "reason": str, "e164": str, "vapi_phone_number_id": str,
             "checks": {...}}. `reason` is "" only when eligible.
    """
    tid = str(tenant.get("id") or "")
    e164 = str(tenant.get("twilio_phone_number") or "").strip()
    vid = str(tenant.get("vapi_phone_number_id") or "").strip()
    sub = str(tenant.get("twilio_subaccount_sid") or "").strip()
    tok = str(tenant.get("twilio_auth_token") or "").strip()
    checks: dict[str, object] = {}

    def verdict(reason: str) -> dict:
        return {"eligible": not reason, "reason": reason, "tenant_id": tid,
                "e164": e164, "number": _mask(e164),
                "vapi_phone_number_id": vid, "checks": checks}

    if not e164:
        return verdict(NO_SCALAR)
    if not sub or not tok:
        return verdict(MISSING_CREDS)

    listing = await telephony.fetch_subaccount_numbers(sub, tok)
    checks["provider_query"] = "success" if listing.ok else f"error:{listing.error_detail}"
    checks["provider_numbers_held"] = len(listing.numbers) if listing.ok else None
    if not listing.ok:
        return verdict(PROVIDER_UNAVAILABLE)
    if not listing.is_empty:
        # The number may be back, or the account holds a different one. Either way
        # this is no longer an obviously stale pointer.
        return verdict(PROVIDER_OWNS_NUMBERS)

    search = await telephony.find_number_across_accounts(e164)
    checks["org_scanned"] = search.scanned
    checks["org_unreadable"] = search.unreadable
    checks["org_holders"] = len(search.accounts)
    if not search.ok or not search.complete:
        # A partial sweep cannot prove absence.
        return verdict(ORG_SEARCH_INCOMPLETE)
    if search.accounts:
        return verdict(NUMBER_FOUND_IN_ORG)

    client = get_client()
    own_rows = (client.table("tenant_phone_numbers").select("id")
                .eq("tenant_id", tid).execute().data or [])
    checks["canonical_rows_for_tenant"] = len(own_rows)
    if own_rows:
        return verdict(CANONICAL_ROW_EXISTS)
    by_num = (client.table("tenant_phone_numbers").select("id, tenant_id")
              .eq("e164", e164).execute().data or [])
    checks["canonical_rows_for_e164"] = len(by_num)
    if by_num:
        return verdict(CANONICAL_CLAIMS_E164)
    others = [r for r in (client.table("tenants").select("id, twilio_phone_number")
                          .eq("twilio_phone_number", e164).execute().data or [])
              if str(r.get("id")) != tid]
    checks["other_tenants_claiming_e164"] = len(others)
    if others:
        return verdict(OTHER_TENANT_CLAIMS)

    if vid:
        state = await vapi.phone_number_state(vid, vapi.get_tenant_vapi_key(tenant))
        checks["vapi_state"] = state
        if state == vapi.PHONE_EXISTS:
            # Still a real resource. Removing our only pointer to it would orphan it.
            return verdict(VAPI_RESOURCE_EXISTS)
        if state != vapi.PHONE_ABSENT:
            return verdict(VAPI_STATE_UNKNOWN)
    else:
        checks["vapi_state"] = "no_pointer"

    return verdict("")


async def clear_stale_pointers(tenant: dict, *, dry_run: bool = True) -> dict:
    """Clear the two dangling columns, under a precondition.

    The write is fenced on the values that were just proved stale, so a concurrent
    re-provision between evaluation and write cannot be overwritten: PostgREST
    returns the rows it changed, and anything other than exactly one row is a stop,
    not a retry.
    """
    result = await evaluate_tenant(tenant)
    result["dry_run"] = dry_run
    if not result["eligible"]:
        result["rows_changed"] = 0
        return result
    if dry_run:
        result["rows_changed"] = 0
        result["action"] = "would_clear"
        return result

    tid, e164, vid = result["tenant_id"], result["e164"], result["vapi_phone_number_id"]
    # EXACTLY TWO COLUMNS. No updated_at: the tenants table does not have one (it
    # carries created_at only), and a first attempt that included it failed closed
    # with PGRST204 having written nothing -- which is the behaviour you want from a
    # fenced write, but the column list should be right the first time.
    q = (get_client().table("tenants")
         .update({"twilio_phone_number": None, "vapi_phone_number_id": None})
         .eq("id", tid)
         .eq("twilio_phone_number", e164))
    # Fence on the Vapi id too when there is one. A NULL cannot be matched with .eq,
    # so a tenant with no pointer is fenced on the scalar alone.
    if vid:
        q = q.eq("vapi_phone_number_id", vid)
    changed = q.execute().data or []
    result["rows_changed"] = len(changed)
    result["action"] = "cleared" if len(changed) == 1 else "unexpected_row_count"
    if len(changed) != 1:
        logger.error("STALE PHONE CLEANUP changed %d rows for tenant %s -- expected 1",
                     len(changed), tid)
    return result
