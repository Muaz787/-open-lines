"""
Deferred Twilio operator-leg reconciliation for AI Call Routing transfers.

Why this exists: a warm transfer's real duration is the post-hand-off
caller<->operator talk-time, which runs on the Twilio operator leg. Vapi's call
ends at the hand-off (endedReason="assistant-forwarded-call"), so that talk-time
is NOT in Vapi's durationSeconds and can't be read at end-of-call (the leg is
still in progress). This job runs later (daily cron) and backfills
transfer_attempts.duration_secs from Twilio for VISIBILITY only — it is never fed
into usage/billing (post-hand-off time is not charged to the customer; see
services/transfer.py pricing note and the routing_overflow memory).

Linkage: Vapi's call.phoneCallProviderId is the INBOUND Twilio Call SID. The
operator leg Vapi dials is an outbound-dial child whose ParentCallSid == that
inbound SID, so we can attribute it exactly (no time-window guessing).
"""
import logging
import httpx

from db import routing as rdb
from db import supabase as db
from services.vapi import get_call_details, get_tenant_vapi_key

logger = logging.getLogger(__name__)

_TWILIO_API = "https://api.twilio.com/2010-04-01"


def sum_completed_child_seconds(calls: list[dict]) -> int:
    """Sum the duration (seconds) of COMPLETED child legs. Twilio returns duration
    as a string; non-numeric / missing / still-in-progress legs contribute 0."""
    total = 0
    for c in calls or []:
        if (c or {}).get("status") != "completed":
            continue
        try:
            total += int(c.get("duration"))
        except (TypeError, ValueError):
            continue
    return total


async def _fetch_child_legs(subaccount_sid: str, auth_token: str, parent_call_sid: str) -> list[dict]:
    """Twilio calls whose ParentCallSid == the inbound leg — i.e. the operator
    leg(s) Vapi dialed for the warm transfer. Read-only."""
    url = f"{_TWILIO_API}/Accounts/{subaccount_sid}/Calls.json"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            url,
            params={"ParentCallSid": parent_call_sid, "PageSize": 20},
            auth=(subaccount_sid, auth_token),
        )
        r.raise_for_status()
        return r.json().get("calls", [])


async def reconcile_pending(lookback_hours: int = 48, limit: int = 200) -> dict:
    """Backfill duration_secs for recent transfer attempts that don't have it yet.
    Best-effort and per-attempt isolated: one failure never aborts the batch. Returns
    a summary count dict. Store-only — never touches usage/billing."""
    attempts = await rdb.list_attempts_needing_duration(lookback_hours, limit)
    updated = skipped = failed = 0
    tenants: dict[str, dict] = {}

    for a in attempts:
        try:
            tid = a.get("tenant_id")
            vci = a.get("vapi_call_id")
            if not (tid and vci):
                skipped += 1
                continue

            tenant = tenants.get(tid)
            if tenant is None:
                tenant = await db.get_tenant_by_id(tid) or {}
                tenants[tid] = tenant

            sub_sid = tenant.get("twilio_subaccount_sid")
            sub_tok = tenant.get("twilio_auth_token")
            if not (sub_sid and sub_tok):
                skipped += 1
                continue

            details = await get_call_details(vci, api_key=get_tenant_vapi_key(tenant))
            inbound_sid = (details or {}).get("phoneCallProviderId")
            if not inbound_sid:
                skipped += 1
                continue

            legs = await _fetch_child_legs(sub_sid, sub_tok, inbound_sid)
            secs = sum_completed_child_seconds(legs)
            if secs > 0:
                await rdb.set_attempt_duration(a["id"], secs)
                updated += 1
            else:
                # legs not completed yet (call still live) — leave null; a later run gets it
                skipped += 1
        except Exception as e:
            logger.warning("transfer reconcile: attempt %s failed: %s", a.get("id"), e)
            failed += 1

    result = {"candidates": len(attempts), "updated": updated, "skipped": skipped, "failed": failed}
    logger.info("transfer reconcile: %s", result)
    return result
