"""
W6A2-C4 — a refund's cancellation intent survives not being able to act now.

THE HOLE THIS CLOSES
A refund arrives while a reschedule owns the appointment, so it cannot mutate
the provider and skips. The reschedule then ends in create_failed — the one
terminal state that deliberately leaves the source ACTIVE — and releases its
claim. The refund's intent has now vanished: the customer has their money back
and the appointment is still live, with nothing anywhere recording that anyone
wanted it cancelled.

"The current owner will subsume it" is true for owners that cancel, and false
for exactly the branch that doesn't.

So the intent is written down on webhook_events, which already provides
durability, retry with backoff, permanent-failure signalling and a consumer that
runs continuously. Migration 023 keeps at most one PENDING intent per
appointment; correctness does not depend on that index — it comes from global
ownership plus terminal convergence, and the index only stops the churn.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import db.supabase as db
from db import mutation_claims as db_mc
from services import appointment_cancellation as cancel_svc
from services import mutation_ownership

logger = logging.getLogger(__name__)

EVENT_TYPE = "appointment.cancel_requested"

ENQUEUED = "enqueued"
ALREADY_PENDING = "already_pending"
ENQUEUE_FAILED = "enqueue_failed"


async def enqueue(*, tenant_id: str, appointment_id: str,
                  provider_booking_id: str, reason: str = "refund") -> str:
    """Record that this appointment should be cancelled when it can be.

    The payload is a locator, never an authority: the worker re-reads the
    appointment and asks the provider, because by the time it runs everything in
    here may be stale.
    """
    payload = {
        "tenant_id": tenant_id,
        "appointment_id": appointment_id,
        "provider_booking_id": provider_booking_id,
        "reason": reason,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        created = await db.enqueue_webhook_event(EVENT_TYPE, None, payload)
    except Exception as e:
        # Distinct from "already queued". The refund may already be irreversible,
        # so failing to record the intent is an operator-visible inconsistency,
        # not a deferral.
        logger.error("CONSISTENCY INCIDENT: could not persist a cancellation intent for "
                     "appointment %s (tenant %s) after a refund: %s",
                     appointment_id, tenant_id, e)
        return ENQUEUE_FAILED
    if not created:
        # Migration 023's partial unique index: an outstanding intent already
        # exists, so the work is already durable.
        logger.info("cancel intent: one is already pending for appointment %s", appointment_id)
        return ALREADY_PENDING
    logger.info("cancel intent: queued for appointment %s (reason=%s)", appointment_id, reason)
    return ENQUEUED


async def handle(payload: dict) -> None:
    """Process one queued intent. Raises to make the queue retry.

    An ordinary owner, not a privileged bypass: it acquires the same global claim
    every other destructive workflow must hold, and obeys the same C1/C3 rules
    about what may be written down.
    """
    appointment_id = (payload or {}).get("appointment_id") or ""
    if not appointment_id:
        # Malformed beyond use. Raising lets the queue's own retry/permanent-fail
        # policy handle it rather than inventing a second one here.
        raise ValueError("appointment.cancel_requested: payload has no appointment_id")

    # --- terminal convergence BEFORE taking ownership -----------------------
    appt = await db.get_appointment_by_id(appointment_id)
    if not appt:
        logger.info("cancel intent: appointment %s no longer exists — nothing to do",
                    appointment_id)
        return
    if (appt.get("status") or "") == "cancelled":
        logger.info("cancel intent: appointment %s is already cancelled", appointment_id)
        return

    tenant_id = str(appt.get("tenant_id") or "")
    own_status, claim = await mutation_ownership.acquire_for_cancel(appointment_id, tenant_id)
    if own_status == mutation_ownership.BUSY:
        # Someone else owns it right now. Retry later — marking the event done
        # here is exactly how the intent would be lost a second time.
        raise RuntimeError(f"appointment {appointment_id} is owned by another mutation; retrying")
    if own_status != mutation_ownership.ACQUIRED or claim is None:
        raise RuntimeError(f"could not acquire ownership of appointment {appointment_id}")

    try:
        # --- authoritative re-read UNDER ownership --------------------------
        appt = await db.get_appointment_by_id(appointment_id)
        if not appt or (appt.get("status") or "") == "cancelled":
            await mutation_ownership.release(claim)
            return

        tenant = await db.get_tenant_by_id(tenant_id) or {}
        outcome = await cancel_svc.cancel_at_provider(tenant, appt, tenant_id)

        if outcome == cancel_svc.UNKNOWN:
            # Ownership is RETAINED and handed to C3 reconciliation, which now
            # owns convergence. The event is done precisely so the queue and the
            # reconciler do not both chase the same appointment.
            await mutation_ownership.to_reconcile(claim, db_mc.REASON_PROVIDER_UNKNOWN)
            return

        if outcome != cancel_svc.OK:
            # Definitive rejection or a location mismatch: nothing was cancelled,
            # so release and let the queue try again later.
            await mutation_ownership.release(claim)
            raise RuntimeError(
                f"provider refused cancellation of appointment {appointment_id} ({outcome})")

        try:
            await db.update_appointment(appointment_id, {"status": "cancelled"})
        except Exception:
            await mutation_ownership.to_reconcile(claim, db_mc.REASON_LOCAL_WRITE_FAILED)
            logger.error("cancel intent: provider cancelled appointment %s but the local "
                         "write failed — handed to reconciliation", appointment_id)
            return

        await mutation_ownership.release(claim)
        logger.info("cancel intent: appointment %s cancelled", appointment_id)
    except Exception:
        raise
