"""Data access for the regulatory tables (migration 027, W9G).

Thin wrappers over the service-role client, matching db/locations.py and
db/phone_numbers.py. Every query is tenant-scoped at the query level, defence in
depth on top of the ownership checks in the route layer and the composite foreign
keys in the database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── tenant_regulatory_addresses ────────────────────────────────────────────

async def get_address(tenant_id: str, address_row_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_addresses").select("*")
           .eq("tenant_id", tenant_id).eq("id", address_row_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_address(tenant_id: str, iso_country: str,
                       tenant_location_id: str | None) -> dict | None:
    """The tenant's address row for this country and location, if any.

    Mirrors the two partial unique indexes: a location-scoped row when a location is
    named, the tenant-level row when not.
    """
    q = (get_client().table("tenant_regulatory_addresses").select("*")
         .eq("tenant_id", tenant_id).eq("iso_country", iso_country))
    q = (q.eq("tenant_location_id", tenant_location_id) if tenant_location_id
         else q.is_("tenant_location_id", "null"))
    return (q.limit(1).execute().data or [None])[0]


async def insert_address(row: dict) -> dict | None:
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_addresses")
            .insert(payload).execute().data or [None])[0]


# ── the address creation claim (W9H-QA.3) ──────────────────────────────────
#
# W9H-QA.2 raced two processes through ensure_address and measured the result:
# BOTH crossed Twilio's Address.create before either owned the database row, so
# two provider Addresses existed, one INSERT won, the loser raised a raw 23505 out
# of the request, and the loser's Address was orphaned at Twilio with nothing
# pointing at it. Twilio does not deduplicate identical Address.create calls, so
# nothing upstream was going to save us.
#
# The fix is ordering: take the uniqueness claim in the database FIRST, and let the
# partial unique indexes from migration 027 decide the winner, before anyone is
# allowed to spend a provider resource.

# A claim whose attempt has not been touched for this long is presumed abandoned --
# its worker crashed, was redeployed, or lost its container. Comfortably longer than
# a Twilio Address.create round-trip (~0.5s measured) so a live attempt is never
# stolen, short enough that a crash does not strand a customer.
CLAIM_STALE_SECONDS = 120


def claim_marker(address_row_id: str) -> str:
    """The provider-side ownership marker for one claim.

    Twilio's Address list filters on FriendlyName server-side, so writing the claim
    row's id here makes "did anyone already create an Address for this claim?" an
    exact question with an exact answer -- not a heuristic match on street text.
    That is what lets a taking-over worker ADOPT a crashed worker's Address instead
    of creating a second one, and what makes a delete provably safe: we only ever
    remove an Address whose FriendlyName names the claim we hold.

    Twilio caps FriendlyName at 64 characters and rejects a longer FILTER with
    twilio_code 20400 -- measured live in W9H-QA.3, where a 65-character marker made
    the reconciliation lookup fail before it could do any good. This is 54; the
    length is asserted in the tests so the budget cannot be spent by accident.
    """
    return f"OpenLines regaddr {address_row_id}"


async def claim_address(row: dict) -> dict | None:
    """Take the creation claim for one address scope, or return None if we lost.

    Returns the claim row on success. None means another request holds the claim --
    NOT an error, and specifically not something the caller may treat as permission
    to call the provider.

    23505 is caught HERE rather than in the engine because losing a race is a normal
    outcome of this function, not an exception to it. W9H-QA.2's defect was exactly
    this error escaping as an unhandled 500.
    """
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    try:
        res = (get_client().table("tenant_regulatory_addresses")
               .insert(payload).execute())
    except Exception as e:
        if _is_unique_violation(e):
            return None
        raise
    return (res.data or [None])[0]


def _is_unique_violation(e: Exception) -> bool:
    """Is this PostgreSQL 23505 arriving through PostgREST?

    Matched on the SQLSTATE rather than the message: the message names the
    constraint and echoes the conflicting key, which is exactly the sort of text
    that gets reworded between PostgREST versions.
    """
    code = getattr(e, "code", None)
    if code is None:
        code = (getattr(e, "args", None) or [{}])[0]
        code = code.get("code") if isinstance(code, dict) else None
    if str(code) == "23505":
        return True
    # Fall back to the serialised body only when no structured code reached us.
    return "23505" in str(e)


async def attach_address_sid(address_row_id: str, patch: dict) -> dict | None:
    """FENCED finalisation: write the provider SID only while nobody else has.

    The fence is `address_sid is null`. It is a real invariant rather than a version
    counter -- an address row acquires its provider identity exactly once -- so a
    worker that crashed, was taken over, and then woke up cannot overwrite the
    identity the new owner already attached. It gets None back and learns it lost.

    One row updated proves we won; zero proves we did not.
    """
    res = (get_client().table("tenant_regulatory_addresses")
           .update({**patch, "updated_at": _now_iso()})
           .eq("id", address_row_id).is_("address_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None


async def take_over_address_claim(address_row_id: str) -> dict | None:
    """Atomically take over a claim that is abandoned or terminally failed.

    Two separate compare-and-sets rather than one OR'd predicate, because each
    answers a different question and PostgREST expresses them far more legibly
    apart:

      1. The previous attempt ended in a provider REJECTION. There is no live worker
         to displace, so a corrected retry may proceed immediately -- waiting out a
         stale timer would make every address correction take two minutes.
      2. The previous attempt simply stopped touching the row. Presumed crashed.

    Both are guarded by `address_sid is null`: a claim that already reached the
    provider is never up for grabs. Winning renews updated_at, which is what stops a
    second waiting worker from also taking over -- the renewal moves the row out of
    the stale window in the same statement that awards it.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - CLAIM_STALE_SECONDS
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    base = {"updated_at": _now_iso(), "validation_error": None}

    res = (get_client().table("tenant_regulatory_addresses").update(base)
           .eq("id", address_row_id).is_("address_sid", "null")
           .not_.is_("validation_error", "null").execute())
    if len(res.data or []) == 1:
        return res.data[0]

    res = (get_client().table("tenant_regulatory_addresses").update(base)
           .eq("id", address_row_id).is_("address_sid", "null")
           .is_("validation_error", "null")
           .lt("updated_at", cutoff_iso).execute())
    return res.data[0] if len(res.data or []) == 1 else None


async def release_address_claim(address_row_id: str) -> dict | None:
    """Give up an address creation lease after an UNKNOWN provider outcome.

    W9H-QA.3 shipped without this and it is a real, if mild, defect: after a
    transport failure the claim stayed fresh, so every retry inside the stale
    window was told the address was already being created. Same reasoning as
    release_provider_claim -- safe because the next attempt reconciles by marker
    before creating anything.
    """
    res = (get_client().table("tenant_regulatory_addresses")
           .update({"updated_at": _EPOCH})
           .eq("id", address_row_id).is_("address_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None


async def record_address_failure(address_row_id: str, error: str) -> dict | None:
    """Record a provider rejection on a claim we still hold.

    Fenced the same way as attachment: if we no longer hold the claim, our failure
    is stale news and must not overwrite a newer owner's state.
    """
    res = (get_client().table("tenant_regulatory_addresses")
           .update({"validated": False, "validation_error": error,
                    "updated_at": _now_iso()})
           .eq("id", address_row_id).is_("address_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None


async def update_address(address_row_id: str, patch: dict) -> dict | None:
    return (get_client().table("tenant_regulatory_addresses")
            .update({**patch, "updated_at": _now_iso()})
            .eq("id", address_row_id).execute().data or [None])[0]


# ── tenant_regulatory_profiles ─────────────────────────────────────────────

async def list_profiles(tenant_id: str) -> list[dict]:
    return (get_client().table("tenant_regulatory_profiles").select("*")
            .eq("tenant_id", tenant_id).order("created_at").execute().data or [])


async def get_profile(tenant_id: str, profile_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("tenant_id", tenant_id).eq("id", profile_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_profile_for_address(tenant_id: str, iso_country: str, number_type: str,
                                   end_user_type: str,
                                   regulatory_address_id: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("tenant_id", tenant_id).eq("iso_country", iso_country)
           .eq("number_type", number_type).eq("end_user_type", end_user_type)
           .eq("regulatory_address_id", regulatory_address_id).limit(1).execute())
    return (res.data or [None])[0]


async def find_profile_by_bundle(bundle_sid: str) -> dict | None:
    """The profile a Bundle SID belongs to. THIS IS THE CALLBACK'S ONLY ROUTE IN.

    trp_bundle_sid_key makes the answer unique, so a callback never has to be
    believed about which tenant it concerns.
    """
    sid = str(bundle_sid or "").strip()
    if not sid:
        return None
    res = (get_client().table("tenant_regulatory_profiles").select("*")
           .eq("bundle_sid", sid).limit(2).execute())
    rows = res.data or []
    if len(rows) > 1:
        logger.error("REGULATORY IDENTITY CONFLICT: %d profiles share a bundle sid",
                     len(rows))
        return None
    return rows[0] if rows else None


async def list_nonterminal_profiles(states: tuple[str, ...], limit: int = 200) -> list[dict]:
    return (get_client().table("tenant_regulatory_profiles").select("*")
            .in_("state", list(states)).order("last_synced_at", desc=False)
            .limit(limit).execute().data or [])


async def insert_profile(row: dict) -> dict | None:
    """Insert a profile, or return None if another request already created it.

    None means the partial unique indexes from migration 027
    (trp_country_scope_key / trp_address_scope_key) refused a second profile for
    the same scope. That is a NORMAL outcome of two concurrent requests, so the
    23505 is caught here and the caller re-reads the canonical row -- W9H.1A found
    it escaping as a raw PostgreSQL error, constraint name and all, to the API.
    """
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    try:
        res = (get_client().table("tenant_regulatory_profiles")
               .insert(payload).execute())
    except Exception as e:
        if _is_unique_violation(e):
            return None
        raise
    return (res.data or [None])[0]


async def update_profile(profile_id: str, patch: dict) -> dict | None:
    return (get_client().table("tenant_regulatory_profiles")
            .update({**patch, "updated_at": _now_iso()})
            .eq("id", profile_id).execute().data or [None])[0]


async def transition_profile(profile_id: str, *, expected_state: str,
                             new_state: str, patch: dict | None = None) -> bool:
    """Compare-and-set a profile's state. True only if we won.

    Fenced on the state we believed the profile was in, so a callback and a
    reconciliation sweep racing on the same profile cannot both apply a transition.
    len(data) == 1 proves we were the one that moved it.
    """
    res = (get_client().table("tenant_regulatory_profiles")
           .update({**(patch or {}), "state": new_state, "updated_at": _now_iso()})
           .eq("id", profile_id).eq("state", expected_state).execute())
    return len(res.data or []) == 1


# ── tenant_regulatory_events ───────────────────────────────────────────────

async def latest_event(bundle_sid: str) -> dict | None:
    res = (get_client().table("tenant_regulatory_events").select("*")
           .eq("bundle_sid", bundle_sid).order("last_received_at", desc=True)
           .limit(1).execute())
    return (res.data or [None])[0]


async def count_events_with_fingerprint(bundle_sid: str, fingerprint: str) -> int:
    res = (get_client().table("tenant_regulatory_events").select("id", count="exact")
           .eq("bundle_sid", bundle_sid).eq("fingerprint", fingerprint).execute())
    return res.count or 0


async def insert_event(row: dict) -> dict | None:
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_events")
            .insert(payload).execute().data or [None])[0]


async def bump_event_delivery(event_id: str, delivery_count: int) -> dict | None:
    return (get_client().table("tenant_regulatory_events")
            .update({"delivery_count": delivery_count,
                     "last_received_at": _now_iso(), "updated_at": _now_iso()})
            .eq("id", event_id).execute().data or [None])[0]


# ── tenant_regulatory_business_details (migration 028) ─────────────────────
#
# The answers a customer gave, kept so a failed create can be retried, a rejected
# filing corrected, and a lost provider object rebuilt -- without asking them to
# retype. Named columns only; never a provider blob.

#: The columns a caller may write. Anything else is refused rather than dropped
#: silently, so a new provider requirement cannot quietly go unstored.
BUSINESS_DETAIL_COLUMNS = (
    "business_name", "business_website", "business_registration_number",
    "authorized_rep_first_name", "authorized_rep_last_name", "authorized_rep_email",
    "business_identity", "is_subassigned", "comments",
    "requirements_fingerprint", "collected_at",
)


async def get_business_details(tenant_id: str, iso_country: str,
                              end_user_type: str = "business") -> dict | None:
    res = (get_client().table("tenant_regulatory_business_details").select("*")
           .eq("tenant_id", tenant_id).eq("iso_country", iso_country)
           .eq("end_user_type", end_user_type).limit(1).execute())
    return (res.data or [None])[0]


async def upsert_business_details(tenant_id: str, iso_country: str, *,
                                  end_user_type: str = "business",
                                  values: dict) -> dict | None:
    """Merge the supplied answers into the tenant's stored set.

    MERGE, NOT REPLACE. A correction after a rejection changes one field; wiping
    the rest would turn a one-field edit into a full retype, which is the problem
    this table exists to solve. Only non-empty values overwrite, so an omitted
    field keeps what was there.
    """
    patch = {k: v for k, v in (values or {}).items()
             if k in BUSINESS_DETAIL_COLUMNS
             and str(v if v is not None else "").strip() != ""}
    existing = await get_business_details(tenant_id, iso_country, end_user_type)
    if existing:
        if not patch:
            return existing
        return (get_client().table("tenant_regulatory_business_details")
                .update({**patch, "updated_at": _now_iso()})
                .eq("id", existing["id"]).execute().data or [None])[0]
    return (get_client().table("tenant_regulatory_business_details").insert({
        "tenant_id": tenant_id, "iso_country": iso_country,
        "end_user_type": end_user_type, **patch,
        "created_at": _now_iso(), "updated_at": _now_iso()}).execute().data
            or [None])[0]


def attributes_from_details(details: dict | None, field_names) -> dict:
    """Stored details -> the provider attribute bag, for exactly the fields asked.

    The column names are ours (authorized_rep_first_name reads better in a database
    than first_name); the provider's are its own. This is the single place that
    mapping lives.
    """
    if not details:
        return {}
    mapped = {
        "business_name": details.get("business_name"),
        "business_website": details.get("business_website"),
        "business_registration_number": details.get("business_registration_number"),
        "first_name": details.get("authorized_rep_first_name"),
        "last_name": details.get("authorized_rep_last_name"),
        "email": details.get("authorized_rep_email"),
        "business_identity": details.get("business_identity"),
        "is_subassigned": details.get("is_subassigned"),
        "comments": details.get("comments"),
    }
    return {k: v for k, v in mapped.items()
            if k in set(field_names) and str(v if v is not None else "").strip() != ""}


def details_from_attributes(attributes: dict) -> dict:
    """The inverse: a provider attribute bag -> our column names."""
    a = attributes or {}
    out = {
        "business_name": a.get("business_name"),
        "business_website": a.get("business_website"),
        "business_registration_number": a.get("business_registration_number"),
        "authorized_rep_first_name": a.get("first_name"),
        "authorized_rep_last_name": a.get("last_name"),
        "authorized_rep_email": a.get("email"),
        "business_identity": a.get("business_identity"),
        "is_subassigned": a.get("is_subassigned"),
        "comments": a.get("comments"),
    }
    return {k: v for k, v in out.items()
            if str(v if v is not None else "").strip() != ""}


def unstorable_fields(field_names) -> list[str]:
    """Provider-required fields this schema has no column for.

    A new required field must stop the workflow, not land in an untyped blob:
    personal data is exactly what should not accumulate unreviewed. Same discipline
    as an unexpected document requirement.
    """
    known = {"business_name", "business_website", "business_registration_number",
             "first_name", "last_name", "email", "business_identity",
             "is_subassigned", "comments"}
    return [f for f in field_names if f not in known]


# ── tenant_regulatory_provider_claims (migration 030, W9H-QA.4) ────────────
#
# Creation ownership for EndUser, SupportingDocument and Bundle. Same discipline
# the Address fix proved in W9H-QA.3: claim in the database BEFORE the provider is
# called, carry the claim id to the provider in FriendlyName, attach through a
# fenced compare-and-set. The difference is only that Addresses already had a row
# to claim and these three do not -- see migration 030 for why none of the existing
# tables was a safe home.

CLAIM_TABLE = "tenant_regulatory_provider_claims"
# Any timestamp guaranteed older than every stale window.
_EPOCH = "1970-01-01T00:00:00+00:00"


async def claim_provider_resource(*, tenant_id: str, resource: str, scope_key: str,
                                  provider_account_sid: str,
                                  provider: str = "twilio") -> dict | None:
    """Take creation ownership of one logical provider resource, or None if lost.

    None means another request holds the claim. NOT an error, and specifically not
    permission to call the provider anyway.
    """
    payload = {"tenant_id": tenant_id, "provider": provider, "resource": resource,
               "scope_key": scope_key, "provider_account_sid": provider_account_sid,
               "claimed_at": _now_iso(), "created_at": _now_iso(),
               "updated_at": _now_iso()}
    try:
        res = get_client().table(CLAIM_TABLE).insert(payload).execute()
    except Exception as e:
        if _is_unique_violation(e):
            return None
        raise
    return (res.data or [None])[0]


async def find_provider_claim(*, tenant_id: str, resource: str, scope_key: str,
                              provider: str = "twilio") -> dict | None:
    res = (get_client().table(CLAIM_TABLE).select("*")
           .eq("tenant_id", tenant_id).eq("provider", provider)
           .eq("resource", resource).eq("scope_key", scope_key).limit(1).execute())
    return (res.data or [None])[0]


async def attach_provider_sid(claim_id: str, provider_sid: str,
                              provider_account_sid: str) -> dict | None:
    """FENCED finalisation: write the provider SID only while nobody else has.

    The fence is `provider_sid is null` -- a real invariant, since a claim acquires
    its provider resource exactly once. A worker that was taken over and then woke
    up gets None back and learns it lost, instead of overwriting the new owner.
    """
    res = (get_client().table(CLAIM_TABLE)
           .update({"provider_sid": provider_sid,
                    "provider_account_sid": provider_account_sid,
                    "failure": None, "updated_at": _now_iso()})
           .eq("id", claim_id).is_("provider_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None


async def take_over_provider_claim(claim_id: str) -> dict | None:
    """Atomically take over a claim that is abandoned or terminally failed.

    Two compare-and-sets rather than one OR'd predicate, because they answer
    different questions:

      1. The previous attempt ended in a provider REFUSAL. No live worker to
         displace, so a corrected retry proceeds at once -- waiting out a stale
         timer would make every correction take minutes.
      2. The previous attempt simply stopped touching the claim. Presumed crashed.

    Both guarded by `provider_sid is null`: a claim that already reached the
    provider is never up for grabs. Winning renews claimed_at in the same statement
    that awards the claim, so a second waiting worker cannot also take over.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=CLAIM_STALE_SECONDS)).isoformat()
    base = {"claimed_at": _now_iso(), "failure": None, "updated_at": _now_iso()}

    res = (get_client().table(CLAIM_TABLE).update(base)
           .eq("id", claim_id).is_("provider_sid", "null")
           .not_.is_("failure", "null").execute())
    if len(res.data or []) == 1:
        return res.data[0]

    res = (get_client().table(CLAIM_TABLE).update(base)
           .eq("id", claim_id).is_("provider_sid", "null")
           .is_("failure", "null").lt("claimed_at", cutoff).execute())
    return res.data[0] if len(res.data or []) == 1 else None


async def release_provider_claim(claim_id: str) -> dict | None:
    """Give up the lease without recording a verdict.

    Used when a provider call ends in an UNKNOWN outcome. Holding the lease would
    be worse than useless: nothing is in flight any more, but for a whole stale
    window every retry would be told "another request is creating it" -- so a
    two-second outage would cost the customer two minutes.

    Releasing is safe precisely because reconciliation-by-marker happens BEFORE any
    create: whoever takes the claim next asks the provider what exists, so a
    resource this attempt may have created is adopted rather than duplicated.
    Fenced on provider_sid IS NULL so a claim that already succeeded is untouched.
    """
    res = (get_client().table(CLAIM_TABLE)
           .update({"claimed_at": _EPOCH, "updated_at": _now_iso()})
           .eq("id", claim_id).is_("provider_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None


async def record_provider_claim_failure(claim_id: str, failure: str) -> dict | None:
    """Record a provider refusal on a claim we still hold. Fenced like attachment:
    if we no longer hold it, our failure is stale news."""
    res = (get_client().table(CLAIM_TABLE)
           .update({"failure": failure, "updated_at": _now_iso()})
           .eq("id", claim_id).is_("provider_sid", "null").execute())
    return (res.data or [None])[0] if len(res.data or []) == 1 else None
