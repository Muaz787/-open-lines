"""
W6A2-D3 — the presentation layer for moving an appointment.

WHAT THIS IS, AND IS NOT
It is the ONLY thing that turns a caller's two opaque references into a run of the
D1/D2 engine, and the only thing that decides what the assistant is allowed to say
about the result. It contains no lifecycle logic of its own: D1 freezes, D2
mutates, and this module chooses words.

WHY THE WORDS ARE THE SAFETY BOUNDARY HERE
Every failure mode of a reschedule is a sentence the caller believes. "Your
appointment is moved" is a claim about two provider mutations, and it is false in
five of the outcomes below. So each outcome maps to exactly one message, the
messages are asserted by tests, and success wording exists in exactly one branch.

THE OTHER HALF IS WHAT THE MODEL MUST NOT DO
When the outcome is uncertain, the assistant must not improvise a recovery —
not another reschedule, not a booking, not a cancellation. Durable server-side
recovery owns those states and is already running. An improvised second mutation
is precisely how one uncertain booking becomes two certain ones, so every
uncertain branch says so in the tool result itself, not only in the prompt.
"""
from __future__ import annotations

import logging

from services import appointment_refs, reschedule, reschedule_execute as rx
from services import slot_offers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# THE PRODUCT DECISION, MADE EXPLICITLY (D3 §5)
#
# D1 does not compare the source appointment's service to the target slot's
# service. Left alone, "move my consultation to 3pm" could return a Dress Fitting
# slot and the engine would move the caller onto a different service entirely --
# a different appointment, silently.
#
# W6A2 is a TIME reschedule, not a "change my appointment" feature, so equality is
# enforced here, before ownership is taken and before any provider call. This is a
# policy gate in the presentation layer; the engine is unchanged.
#
# To deliberately allow service changes later, flip this to False and the product
# becomes "change appointment" -- which needs its own spoken confirmation flow,
# because the caller must agree to the new service out loud.
# ---------------------------------------------------------------------------
REQUIRE_SAME_SERVICE = True

# Assistant-facing outcomes. Deliberately smaller than the engine's own vocabulary:
# the model needs to know what it may SAY, not which internal state was reached.
COMPLETED = "completed"
BUSY = "busy"
CREATE_FAILED = "create_failed"
UNRESOLVED = "unresolved"            # provider outcome unknown / still settling
SOURCE_CHANGED = "source_changed"    # replacement may exist; original was edited
CANCEL_FAILED = "cancel_failed"      # replacement exists; original still live
INVALID_REF = "invalid_ref"
EXPIRED_REF = "expired_ref"
SLOT_TAKEN = "slot_taken"
CROSS_LOCATION = "cross_location"
SERVICE_MISMATCH = "service_mismatch"
NOT_ELIGIBLE = "not_eligible"
ALREADY_CANCELLED = "already_cancelled"
TEMPORARY = "temporary"

# Outcomes after which the assistant must not attempt any further mutation.
NO_RETRY = frozenset({BUSY, UNRESOLVED, SOURCE_CHANGED, CANCEL_FAILED})

_DO_NOT_RETRY = ("Do NOT call reschedule_appointment, book_appointment or "
                 "cancel_appointment again for this caller in this call.")

_MESSAGES = {
    COMPLETED: (
        "Done — the appointment has been moved. The old time is cancelled and the "
        "new one is confirmed. Tell the caller the new day and time."
    ),
    BUSY: (
        "That appointment is already being changed somewhere else right now, so "
        "nothing was done. Tell the caller you can't change it this moment and "
        "the team will confirm shortly. " + _DO_NOT_RETRY
    ),
    CREATE_FAILED: (
        "The new time could not be booked, so nothing changed — the caller's "
        "ORIGINAL appointment is still in place, exactly as it was. Say that "
        "clearly, then offer to check other times."
    ),
    UNRESOLVED: (
        "The calendar did not confirm the change, so I cannot tell you whether it "
        "went through. Do NOT say the appointment was moved and do NOT say it "
        "failed. Tell the caller the team will confirm the change shortly, and "
        "take a contact number. " + _DO_NOT_RETRY
    ),
    SOURCE_CHANGED: (
        "The original appointment was changed by the business since we looked at "
        "it, so it was NOT cancelled and the move could not be completed safely. "
        "Do NOT tell the caller their appointment was moved. Tell them the team "
        "needs to confirm this one and will be in touch. " + _DO_NOT_RETRY
    ),
    CANCEL_FAILED: (
        "The new time was booked but the original appointment could NOT be "
        "cancelled, so the caller may still have both. Do NOT say the appointment "
        "was moved. Tell them the team will confirm and sort the old one out. "
        + _DO_NOT_RETRY
    ),
    INVALID_REF: (
        "I couldn't match that to an appointment or to a time I offered. Call "
        "reschedule_appointment with no arguments to list the caller's "
        "appointments again, and check_availability again for the times."
    ),
    EXPIRED_REF: (
        "That list is out of date now. Call reschedule_appointment with no "
        "arguments to list the appointments again, and check_availability again "
        "for fresh times, before trying to move anything."
    ),
    SLOT_TAKEN: (
        "That time has just been taken, so nothing changed and the caller's "
        "original appointment is untouched. Call check_availability again and "
        "offer what comes back."
    ),
    CROSS_LOCATION: (
        "Moving an appointment to a DIFFERENT location isn't something I can do "
        "on this call — nothing was changed. Tell the caller their existing "
        "appointment is still in place, and that the team can move it between "
        "locations for them. Do NOT cancel it and do NOT book a new one instead."
    ),
    SERVICE_MISMATCH: (
        "That time is for a different service than the appointment being moved, "
        "so nothing was changed. Moving an appointment keeps the SAME service — "
        "call check_availability again for the same service the caller already "
        "has booked, and offer those times."
    ),
    NOT_ELIGIBLE: (
        "That appointment can't be moved. Tell the caller the team will follow up, "
        "and take a contact number."
    ),
    ALREADY_CANCELLED: (
        "That appointment is already cancelled, so there is nothing to move. Tell "
        "the caller, and offer to book a new appointment if they want one."
    ),
    TEMPORARY: (
        "I couldn't reach the calendar, so nothing was changed and the caller's "
        "appointment is exactly as it was. Tell them there was a brief technical "
        "issue and the team will confirm."
    ),
}

# D1 refused before taking ownership, so no provider mutation happened.
_FROM_D1 = {
    reschedule.BUSY: BUSY,
    reschedule.IN_PROGRESS: BUSY,
    reschedule.BAD_REF: INVALID_REF,
    reschedule.NOT_ELIGIBLE: NOT_ELIGIBLE,
    reschedule.CROSS_LOCATION: CROSS_LOCATION,
    reschedule.LEGACY_LOCATION: CROSS_LOCATION,
    reschedule.SOURCE_CANCELLED: ALREADY_CANCELLED,
    reschedule.SOURCE_UNKNOWN: TEMPORARY,
    reschedule.SLOT_TAKEN: SLOT_TAKEN,
    reschedule.FAILED: TEMPORARY,
}

# D2 ran, so the provider may already have been mutated. Nothing here is allowed
# to read as "nothing happened" unless the engine proved it.
_FROM_D2 = {
    rx.COMPLETED: COMPLETED,
    rx.CREATE_FAILED: CREATE_FAILED,
    rx.CREATE_UNKNOWN: UNRESOLVED,
    rx.CANCEL_RETRYABLE: CANCEL_FAILED,
    rx.CANCEL_UNKNOWN: CANCEL_FAILED,
    rx.SOURCE_CHANGED: SOURCE_CHANGED,
    rx.FENCED: UNRESOLVED,
    rx.INCIDENT: UNRESOLVED,
}


def message_for(outcome: str) -> str:
    return _MESSAGES.get(outcome, _MESSAGES[TEMPORARY])


def _same_service(ref: dict, offer: dict) -> bool:
    """Is the offered slot the SAME service the caller already has booked?

    Compared by the server's own service NAME, which is what both sides actually
    carry: call_appointment_refs.service is copied from the appointment, whose
    service was itself copied from a slot offer's service_name at booking time. No
    model-supplied text is involved on either side.

    An appointment with no recorded service cannot be PROVEN equal, so it fails
    closed. Every appointment booked through the multi-location path has one.
    """
    source = (ref.get("service") or "").strip().lower()
    target = (offer.get("service_name") or "").strip().lower()
    if not source or not target:
        return False
    return source == target


async def _precheck(*, vapi_call_id: str, tenant_id: str, caller_phone: str,
                    appointment_ref: str, slot_ref: str) -> str | None:
    """Cheap read-only gates, BEFORE ownership is taken. None means proceed.

    These are prechecks, not authority: D1 re-resolves both references under
    global ownership and is the thing that actually decides. Their only job is to
    refuse the obviously-wrong combinations without locking an appointment first.
    """
    ref_status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=vapi_call_id, appointment_ref=appointment_ref,
        tenant_id=tenant_id, caller_phone=caller_phone)
    if ref_status == appointment_refs.EXPIRED:
        return EXPIRED_REF
    if ref_status == appointment_refs.ALREADY_CONSUMED:
        return ALREADY_CANCELLED
    if ref_status != appointment_refs.OK or not ref:
        return INVALID_REF

    offer_status, offer = await slot_offers.resolve_for_booking(
        vapi_call_id=vapi_call_id, slot_ref=slot_ref, tenant_id=tenant_id,
        active_location_id="")
    if offer_status == slot_offers.EXPIRED:
        return EXPIRED_REF
    if offer_status in (slot_offers.ALREADY_BOOKED, slot_offers.IN_PROGRESS):
        return SLOT_TAKEN
    if offer_status != slot_offers.OK or not offer:
        return INVALID_REF

    # Same-location is enforced authoritatively by D1 against the RE-READ source.
    # Refusing here too simply avoids taking ownership to say no.
    if str(offer.get("tenant_location_id") or "") != str(ref.get("tenant_location_id") or ""):
        return CROSS_LOCATION

    if REQUIRE_SAME_SERVICE and not _same_service(ref, offer):
        logger.info("reschedule_intent: refusing a service change (%r -> %r)",
                    ref.get("service"), offer.get("service_name"))
        return SERVICE_MISMATCH

    return None


async def move_appointment(*, vapi_call_id: str, tenant_id: str, caller_phone: str,
                           appointment_ref: str, slot_ref: str) -> tuple[str, str]:
    """Run the whole move. Returns (outcome, message_for_the_assistant).

    D1 then D2, in that order, with the claim and the frozen operation handed
    between them exactly as D2's tests exercise. Nothing here retries anything.
    """
    blocked = await _precheck(
        vapi_call_id=vapi_call_id, tenant_id=tenant_id, caller_phone=caller_phone,
        appointment_ref=appointment_ref, slot_ref=slot_ref)
    if blocked:
        return blocked, message_for(blocked)

    try:
        frozen = await reschedule.begin_reschedule(
            vapi_call_id=vapi_call_id, tenant_id=tenant_id, caller_phone=caller_phone,
            appointment_ref=appointment_ref, slot_ref=slot_ref)
    except Exception as e:
        logger.error("reschedule_intent: begin failed for tenant %s: %s", tenant_id, e)
        return TEMPORARY, message_for(TEMPORARY)

    if frozen.status != reschedule.OK or not frozen.operation_id:
        outcome = _FROM_D1.get(frozen.status, TEMPORARY)
        logger.info("reschedule_intent: D1 refused (%s) -> %s", frozen.status, outcome)
        return outcome, message_for(outcome)

    # D1 succeeded, so the claim and the frozen operation now exist and D2 owns
    # them. An exception from here is NOT "nothing happened": the operation is
    # durable and the recovery worker will finish or park it.
    try:
        token = await _claim_token_of(frozen.operation_id)
        if not token:
            # The row vanished between freezing and reading it back. Nothing may
            # touch the provider without a token that both halves agree on.
            logger.error("reschedule_intent: operation %s has no claim token",
                         frozen.operation_id)
            return UNRESOLVED, message_for(UNRESOLVED)
        result = await rx.run_operation(
            frozen.operation_id, token,
            vapi_call_id=vapi_call_id, slot_ref=slot_ref,
            appointment_ref=appointment_ref)
    except Exception as e:
        logger.error("reschedule_intent: execution raised for operation %s: %s — "
                     "leaving it to recovery", frozen.operation_id, e)
        return UNRESOLVED, message_for(UNRESOLVED)

    outcome = _FROM_D2.get(result, UNRESOLVED)
    logger.info("reschedule_intent: operation %s -> %s (%s)",
                frozen.operation_id, result, outcome)
    return outcome, message_for(outcome)


async def _claim_token_of(operation_id: str) -> str:
    """The claim token D1 wrote onto the operation it just froze.

    D1's Result carries the operation id, not the token, and D2's gate requires
    the claim row and the operation row to agree on one. Reading it back from the
    persisted operation is the only source that cannot drift from what was
    actually written -- and it keeps D1's return contract unchanged, which
    matters because D1 is frozen for this workstream.
    """
    from db import reschedule_ops as db_ops

    try:
        row = await db_ops.get_operation(operation_id)
    except Exception as e:
        logger.error("reschedule_intent: could not read operation %s: %s",
                     operation_id, e)
        return ""
    return str((row or {}).get("claim_token") or "")
