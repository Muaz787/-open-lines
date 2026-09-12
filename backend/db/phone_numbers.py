"""Data access for tenant_phone_numbers (migration 027, W9D).

Thin wrappers over the Supabase service-role client, matching db/locations.py.

MOSTLY DARK. The only production read path that uses this table in W9D is
db.supabase.get_tenant_by_phone(), and it falls back to the legacy
tenants.twilio_phone_number scalar — so while this table is empty, inbound routing
behaves exactly as it did before. The write helpers exist so the backfill and the
W9E provisioning path have somewhere to write.

FAILS OPEN ON READ, NEVER GUESSES ON AMBIGUITY. A missing table (migration not yet
applied) must not take inbound calls down, so the lookup swallows errors and
returns nothing, letting the scalar answer. But two tenants claiming one number is
corruption, not a preference, and is surfaced rather than resolved.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client
from services import phone_lifecycle as lifecycle

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PhoneNumberIdentityConflict(Exception):
    """One E.164 resolves to more than one tenant. Never resolved by guessing."""


async def find_routable_by_e164(e164: str) -> dict | None:
    """The row that should receive a call to `e164`, or None.

    Matches only ROUTABLE_STATUSES — a 'provisioning' row has no webhook
    configured yet, and 'released'/'failed' rows are history.

    Raises PhoneNumberIdentityConflict if more than one TENANT matches. The
    tpn_owned_e164_key index makes that impossible while the index exists; this
    check is what turns "impossible" into "detected" if it ever is not.
    """
    number = str(e164 or "").strip()
    if not number:
        return None
    try:
        res = (get_client().table("tenant_phone_numbers").select("*")
               .eq("e164", number)
               .in_("status", list(lifecycle.ROUTABLE_STATUSES))
               .execute())
        rows = res.data or []
    except Exception as e:
        # Migration not applied, or a transport blip. The scalar fallback in
        # get_tenant_by_phone still answers, so a call is never dropped for this.
        logger.warning("tenant_phone_numbers lookup failed for a number: %s", e)
        return None

    if not rows:
        return None
    tenants = {str(r.get("tenant_id") or "") for r in rows}
    if len(tenants) > 1:
        raise PhoneNumberIdentityConflict(
            f"{len(tenants)} tenants claim one routable number "
            f"(rows={[str(r.get('id')) for r in rows]})")
    if len(rows) > 1:
        # Same tenant, two routable rows for one number: a data error, but not an
        # identity ambiguity — the tenant is unambiguous, so routing may proceed.
        logger.error("tenant_phone_numbers: %d routable rows for one number on "
                     "tenant %s", len(rows), next(iter(tenants)))
    return rows[0]


async def find_owned_by_e164(e164: str) -> dict | None:
    """The row for a number we currently HOLD, routable or not.

    Distinct from find_routable_by_e164 on purpose. Routing must not reach a
    number whose webhook is unconfigured, so that lookup excludes
    `provisioning` -- but OWNERSHIP has to include it, or a retried provisioning
    attempt would not find the row it just created and would try to insert a
    second one. The status set is exactly `tpn_owned_e164_key`'s index predicate
    (phone_lifecycle.OWNED_E164_STATUSES), so this answers the same question the
    database would.
    """
    res = (get_client().table("tenant_phone_numbers").select("*")
           .eq("e164", e164)
           .in_("status", list(lifecycle.OWNED_E164_STATUSES))
           .limit(2).execute())
    rows = res.data or []
    if len(rows) > 1:
        logger.error("tenant_phone_numbers: %d owned rows for one number — the "
                     "tpn_owned_e164_key index should have made this impossible",
                     len(rows))
    return rows[0] if rows else None


async def list_for_tenant(tenant_id: str, *, purpose: str = "",
                          statuses: tuple[str, ...] = ()) -> list[dict]:
    q = (get_client().table("tenant_phone_numbers").select("*")
         .eq("tenant_id", tenant_id))
    if purpose:
        q = q.eq("purpose", purpose)
    if statuses:
        q = q.in_("status", list(statuses))
    return (q.order("created_at").execute().data or [])


async def get_current_permanent(tenant_id: str) -> dict | None:
    rows = await list_for_tenant(
        tenant_id, purpose=lifecycle.PURPOSE_PERMANENT,
        statuses=lifecycle.CURRENT_PERMANENT_STATUSES)
    return rows[0] if rows else None


async def insert_number(row: dict) -> dict | None:
    """Insert one row. The caller is expected to have checked
    lifecycle.live_conflict() first; the partial unique indexes remain the
    enforcer of last resort and a 23505 here is a real error, not a no-op."""
    payload = {**row, "created_at": _now_iso(), "updated_at": _now_iso()}
    res = get_client().table("tenant_phone_numbers").insert(payload).execute()
    return (res.data or [None])[0]


async def update_number(number_id: str, patch: dict) -> dict | None:
    res = (get_client().table("tenant_phone_numbers")
           .update({**patch, "updated_at": _now_iso()})
           .eq("id", number_id).execute())
    return (res.data or [None])[0]


async def release_number_cas(*, number_id: str, tenant_id: str, e164: str,
                             provider_sid: str, provider_account_sid: str,
                             last_error: str = "") -> list[dict]:
    """Fenced transition of ONE row to 'released'. Returns the rows it changed.

    EVERY identity field is part of the WHERE clause, not just the row id. The
    failure this prevents is specific and was observed in W9H-QA.5: a worker that
    began releasing number A, stalled, and woke up after the tenant had already
    been reprovisioned onto number B. Fenced on the row id alone it would still
    match — the id is stable — and would retire B, taking a live customer's line
    down. Fenced on the provider identity it matches nothing, which is the
    correct outcome for a worker holding a stale view of the world.

    The status predicate is RELEASABLE_STATUSES, so a row that is already
    'released' matches zero rows here rather than being stamped twice with a new
    released_at. The caller distinguishes "already done" from "moved underneath
    me" by re-reading; a zero-row result alone does not say which.

    provider_sid is deliberately NOT cleared. The regulatory claim retirement in
    migration 030 has to null its SID because a claim scope is reusable, but a
    Twilio IncomingPhoneNumber SID is never reissued: keeping it is what makes
    tpn_provider_object_key a permanent, truthful record of which provider object
    this row was, and it cannot collide with any future purchase.
    """
    patch = {"status": lifecycle.STATUS_RELEASED,
             "released_at": _now_iso(),
             "updated_at": _now_iso()}
    if last_error:
        patch["last_error"] = last_error[:500]
    q = (get_client().table("tenant_phone_numbers").update(patch)
         .eq("id", number_id)
         .eq("tenant_id", tenant_id)
         .eq("e164", e164)
         .eq("provider_account_sid", provider_account_sid)
         .eq("provider_sid", provider_sid)
         .in_("status", list(lifecycle.RELEASABLE_STATUSES)))
    return q.execute().data or []


async def get_by_id(number_id: str) -> dict | None:
    res = (get_client().table("tenant_phone_numbers").select("*")
           .eq("id", number_id).limit(1).execute())
    return (res.data or [None])[0]
