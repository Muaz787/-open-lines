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
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    return (get_client().table("tenant_regulatory_profiles")
            .insert(payload).execute().data or [None])[0]


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
