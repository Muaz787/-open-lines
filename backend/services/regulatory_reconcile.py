"""Reconciliation for nonterminal regulatory profiles (W9G Stage R).

WHY CALLBACKS ARE NOT ENOUGH. Twilio documents that the status callback fires on
every Bundle status change EXCEPT pending-review -> in-review. So a bundle can sit
in review with our record still saying pending-review and no delivery ever coming.
Callbacks are the fast path; this is the recovery path.

DEPLOYMENT. This is a plain callable plus a CLI, not a daemon. The repository has no
in-process scheduler -- `recrawl_cron.py` is invoked by an external Railway cron -- so
inventing a background loop here would add infrastructure nobody asked for and
nothing supervises. `scripts/reconcile_regulatory_profiles.py` is dry-run by default
and is what a cron entry should call once the engine is live.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import regulatory as db_reg
from db.supabase import get_client
from services import regulatory_callback as cb
from services import regulatory_state as st
from services import telephony
from services.telephony import _safe_provider_error

logger = logging.getLogger(__name__)

CHECKED = "checked"
ADVANCED = "advanced"
UNCHANGED = "unchanged"
SKIPPED_TERMINAL = "skipped_terminal"
PROVIDER_UNAVAILABLE = "provider_unavailable"
OWNERSHIP_CONFLICT = "ownership_conflict"
MISSING_BUNDLE = "missing_bundle"
MISSING_CREDENTIALS = "missing_credentials"


async def reconcile_profile(profile: dict, *, dry_run: bool = True) -> dict:
    """Fetch one profile's Bundle and apply any legal transition.

    Read-only in dry run. Never advances a terminal profile, and never trusts a
    Bundle whose account is not the tenant's expected sub-account.
    """
    pid = str(profile.get("id") or "")
    out = {"profile_id": pid, "tenant_id": str(profile.get("tenant_id") or ""),
           "state": str(profile.get("state") or ""), "dry_run": dry_run}

    if st.is_terminal(out["state"]):
        # Approved and rejected profiles are not polled again -- that is the whole
        # point of having a terminal set.
        return {**out, "outcome": SKIPPED_TERMINAL}
    bundle_sid = str(profile.get("bundle_sid") or "")
    if not bundle_sid:
        return {**out, "outcome": MISSING_BUNDLE}

    rows = (get_client().table("tenants")
            .select("id, twilio_subaccount_sid, twilio_auth_token")
            .eq("id", profile.get("tenant_id")).limit(1).execute().data or [])
    if not rows:
        return {**out, "outcome": OWNERSHIP_CONFLICT, "detail": "tenant_missing"}
    sub_sid = str(rows[0].get("twilio_subaccount_sid") or "")
    tok = str(rows[0].get("twilio_auth_token") or "")
    if not sub_sid or not tok:
        return {**out, "outcome": MISSING_CREDENTIALS}
    if str(profile.get("provider_account_sid") or "") != sub_sid:
        logger.error("Reconciliation ownership conflict on profile %s", pid)
        return {**out, "outcome": OWNERSHIP_CONFLICT,
                "detail": "profile_account_is_not_tenant_subaccount"}

    try:
        live = telephony._sub_client(sub_sid, tok) \
            .numbers.v2.regulatory_compliance.bundles(bundle_sid).fetch()
    except Exception as e:
        # An outage is retryable; the profile is left exactly as it was.
        return {**out, "outcome": PROVIDER_UNAVAILABLE, "detail": _safe_provider_error(e)}

    provider_status = str(getattr(live, "status", "") or "")
    stored = str(profile.get("bundle_status") or "")
    target, note = st.state_for_provider_status(provider_status)
    result = {**out, "provider_status": provider_status, "stored_status": stored,
              "target_state": target, "note": note}

    if dry_run:
        would = (target and target != out["state"]
                 and st.transition(out["state"], target)[0] == st.APPLIED)
        return {**result, "outcome": ADVANCED if would else UNCHANGED,
                "would_change": bool(would)}

    applied = await cb.apply_status(profile=profile, provider_status=provider_status)
    if applied["outcome"] not in (st.APPLIED,):
        await db_reg.update_profile(pid, {
            "last_synced_at": datetime.now(timezone.utc).isoformat()})
    return {**result, "outcome": ADVANCED if applied["outcome"] == st.APPLIED else UNCHANGED,
            "transition": applied["outcome"], "state": applied["state"]}


async def reconcile_all(*, dry_run: bool = True, limit: int = 200) -> dict:
    profiles = await db_reg.list_nonterminal_profiles(st.NONTERMINAL_STATES, limit=limit)
    results = [await reconcile_profile(p, dry_run=dry_run) for p in profiles]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return {"dry_run": dry_run, "inspected": len(profiles), "counts": counts,
            "results": results}
