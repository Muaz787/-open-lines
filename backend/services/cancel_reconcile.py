"""
W6A2-C3 — settle cancellations whose truth was left unresolved.

W6A1 can now end a call holding a cancel_reconcile claim: either the provider
outcome was unknown, or the provider confirmed cancellation and our own write
failed. Both retain global ownership on purpose, which means nothing else may
mutate that appointment until somebody settles it. This is that somebody.

Square is the authority in every branch. Nothing here guesses: an unreadable
provider leaves the claim exactly as it is and tries again later, because an
unknown that resolves itself by assumption is the failure this whole workstream
exists to remove.
"""
from __future__ import annotations

import logging
import uuid

import db.supabase as db
from db import mutation_claims as db_mc
from services import square_booking

logger = logging.getLogger(__name__)

MAX_PER_RUN = 20


async def _provider_state(tenant: dict, booking_id: str) -> str:
    """'cancelled' | 'active' | 'unknown' — provider truth, or an honest refusal."""
    token = await square_booking.get_access_token(tenant)
    if not token:
        return "unknown"
    try:
        status, booking = await square_booking.get_booking_detailed(token, booking_id)
    except Exception as e:
        logger.warning("cancel_reconcile: provider read failed for %s: %s", booking_id, e)
        return "unknown"
    if status == square_booking.FETCH_NOT_FOUND:
        # Absence is terminal provider truth, the same reading the cancellation
        # path takes.
        return "cancelled"
    if status != square_booking.FETCH_FOUND:
        return "unknown"
    st = (booking.get("status") or "").upper()
    return "cancelled" if ("CANCELLED" in st or st == "DECLINED") else "active"


async def reconcile_one(claim_row: dict) -> str:
    """Settle a single cancel_reconcile claim. Returns a short outcome label."""
    appointment_id = claim_row["appointment_id"]
    reason = claim_row.get("reconcile_reason") or ""
    mine = str(uuid.uuid4())

    # Take over by CAS, type-matched. operation_type is in the predicate and is
    # never changed, so this can never become a route by which one operation type
    # acquires another's appointment.
    if not await db_mc.takeover_stale_reconcile(
            appointment_id, claim_row["claim_token"], claim_row["claimed_at"], mine):
        return "not_ours"

    fresh = await db_mc.get_claim(appointment_id)
    if not fresh:
        return "gone"
    claimed_at = fresh["claimed_at"]

    appt = await db.get_appointment_by_id(appointment_id)
    if not appt:
        # The appointment was erased; the claim would have cascaded with it.
        await db_mc.release_claim(appointment_id, mine, claimed_at)
        return "appointment_gone"

    tenant = await db.get_tenant_by_id(appt["tenant_id"]) or {}
    booking_id = appt.get("google_event_id") or ""
    if not booking_id:
        logger.error("cancel_reconcile: appointment %s has no provider booking id; "
                     "leaving the claim for operator review", appointment_id)
        return "needs_operator"

    state = await _provider_state(tenant, booking_id)

    if state == "unknown":
        # Retain the claim untouched. Trying again later is the only safe move.
        return "still_unknown"

    if state == "cancelled":
        if (appt.get("status") or "") != "cancelled":
            try:
                await db.update_appointment(appointment_id, {"status": "cancelled"})
            except Exception as e:
                logger.error("cancel_reconcile: local write failed again for %s: %s",
                             appointment_id, e)
                return "local_write_failed"
        await db_mc.release_claim(appointment_id, mine, claimed_at)
        return "reconciled"

    # state == "active"
    if reason == db_mc.REASON_LOCAL_WRITE_FAILED:
        # We recorded that the provider HAD cancelled it. Square now says it is
        # live. Those cannot both be true, so this is an integrity anomaly rather
        # than a retry opportunity — cancelling again would be acting on a
        # contradiction we have not explained.
        logger.error("cancel_reconcile: INTEGRITY ANOMALY for appointment %s — "
                     "local_write_failed implies the booking was cancelled, but "
                     "Square reports it ACTIVE. Claim retained for operator review.",
                     appointment_id)
        return "needs_operator"

    # provider_outcome_unknown + booking definitively active: the cancellation
    # never landed. A type-matched transition back to 'cancel' lets the ordinary
    # path retry, without any cross-type steal and without deleting the row.
    if await db_mc.transition_reconcile_to_cancel(
            appointment_id, mine, claimed_at, str(uuid.uuid4())):
        logger.info("cancel_reconcile: %s confirmed still active — returned to "
                    "cancel ownership for retry", appointment_id)
        return "retryable"
    return "fenced"


async def run_cancel_reconciliation(limit: int = MAX_PER_RUN) -> dict:
    """Settle whatever cancel_reconcile claims are due. Best-effort and idempotent."""
    try:
        rows = await db_mc.list_stale_reconcile_claims(limit=limit)
    except Exception as e:
        logger.error("cancel_reconcile: claim scan failed: %s", e)
        return {"scanned": 0, "error": str(e)[:200]}

    outcomes: dict[str, int] = {}
    for row in rows:
        try:
            result = await reconcile_one(row)
        except Exception as e:
            logger.error("cancel_reconcile: %s raised: %s", row.get("appointment_id"), e)
            result = "error"
        outcomes[result] = outcomes.get(result, 0) + 1
    if rows:
        logger.info("cancel_reconcile: processed %d claim(s): %s", len(rows), outcomes)
    return {"scanned": len(rows), "outcomes": outcomes}
