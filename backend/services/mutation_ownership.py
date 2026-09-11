"""
W6A2-C3 — one destructive lifecycle operation owns an appointment at a time.

THE RACE THIS CLOSES
Appointment refs are CALL-scoped. Two simultaneous calls hold two different
call_appointment_refs rows pointing at the same appointment, and the ref CAS is
keyed on (vapi_call_id, appointment_ref) — so both claim successfully, both see
the appointment as 'confirmed', and both proceed. A cancel in one call and a
reschedule in the other could each reach Square for the same appointment.

WHAT OWNERSHIP IS, AND IS NOT
  appointment_ref   which appointment this caller selected, in this call
  mutation claim    which workflow may mutate it, globally, keyed on the
                    durable appointment id and outliving the call
They are different questions and neither substitutes for the other.

NO CROSS-TYPE STEALING
A caller that meets a held claim refuses; it never inspects the owner's type and
decides it deserves priority. Only a type-matched recovery worker may take over
an abandoned claim, and takeover never changes operation_type.
"""
from __future__ import annotations

import logging
import uuid

from db import mutation_claims as db_mc

logger = logging.getLogger(__name__)

ACQUIRED = "acquired"
BUSY = "busy"            # another mutation owns this appointment
ERROR = "error"


class Claim:
    """A held claim. Carries exactly the fields every CAS predicate needs."""

    __slots__ = ("appointment_id", "token", "claimed_at", "operation_type")

    def __init__(self, appointment_id: str, token: str, claimed_at: str,
                 operation_type: str):
        self.appointment_id = appointment_id
        self.token = token
        self.claimed_at = claimed_at
        self.operation_type = operation_type


async def acquire_for_cancel(appointment_id: str, tenant_id: str) -> tuple[str, Claim | None]:
    """Take global ownership for a cancellation. (status, claim)."""
    token = str(uuid.uuid4())
    try:
        row = await db_mc.acquire_cancel_claim(appointment_id, tenant_id, token)
    except Exception as e:
        logger.error("mutation_ownership: claim insert failed for %s: %s", appointment_id, e)
        return ERROR, None
    if not row:
        # Someone else owns it. We do not look at who, and we do not wait: a
        # caller is on the phone and the honest answer is "not right now".
        logger.info("mutation_ownership: appointment %s is already owned", appointment_id)
        return BUSY, None
    return ACQUIRED, Claim(appointment_id, row["claim_token"], row["claimed_at"],
                           row["operation_type"])


async def release(claim: Claim) -> bool:
    ok = await db_mc.release_claim(claim.appointment_id, claim.token, claim.claimed_at)
    if not ok:
        # Fenced: our claim was taken over. Nothing to undo — the new owner is
        # responsible now, and our DB writes would all have failed anyway.
        logger.warning("mutation_ownership: release fenced for %s (claim no longer ours)",
                       claim.appointment_id)
    return ok


async def to_reconcile(claim: Claim, reason: str) -> bool:
    """Hand the appointment to reconciliation WITHOUT releasing ownership."""
    ok = await db_mc.transition_cancel_to_reconcile(
        claim.appointment_id, claim.token, claim.claimed_at, reason)
    if ok:
        logger.error("mutation_ownership: RECONCILIATION REQUIRED for appointment %s (%s)",
                     claim.appointment_id, reason)
    else:
        logger.warning("mutation_ownership: reconcile transition fenced for %s",
                       claim.appointment_id)
    return ok
