"""
Move a Square appointment that has a deposit, in place (issue #179).

The W6A2 engine moves a Square appointment by booking a replacement and cancelling
the original. Our deposits are linked to the appointment ROW, so that would leave a
paid (or still-owed) deposit on a cancelled row. Square's UpdateBooking instead
moves the booking and keeps its id; the appointment row stays as well, and so
does every payment linked to it. Only start_at changes.

A move happens only when it can be proven safe:
  * the appointment was chosen from a list and the new time from a recorded offer;
  * same location, same service, same team member, same length — Square is asked
    for the target time for THAT team member;
  * a paid deposit already inside the business's non-refundable window is not
    moved: a later time would reopen a refund the policy had closed. Refund
    eligibility itself is unchanged (services.refunds.refund_eligible). A deposit
    confirmation being written owns the appointment, so a move can't overlap it;
  * the booking is still exactly what we have on record (status, location,
    start, team member, service) when we read it under ownership.
Anything else is the team's, as before. Nothing is charged, refunded, voided or
re-linked, and payment status is never written here.

Durability, verification and recovery are shared with Google/Outlook moves
(services.calendar_reschedule, migrations 046/047): the operation is frozen
before Square is called, success needs the booking read back at the new time with
the same parts, and our row is written only by the atomic finish.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import calendar_moves as db_cm
from db import supabase as db
from services import appointment_refs, calendar_reschedule as cr, mutation_ownership
from services import relative_dates, reschedule, slot_offers, square_booking, square_inplace_scope

logger = logging.getLogger(__name__)

HANDOFF = "handoff"            # can't be proven safe automatically: the team moves it
POLICY_WINDOW = "policy_window"
STAFF_UNAVAILABLE = "staff_unavailable"
SLOT_TAKEN = "slot_taken"

_ACTIVE = ("confirmed", "pending_payment")
_NO_RETRY = cr._NO_RETRY

_HANDOFF_MSG = ("I can't move that appointment automatically, so nothing has changed. Take a "
                "message and tell the caller the team will move it and keep their deposit with it.")
_MESSAGES = {
    HANDOFF: _HANDOFF_MSG,
    POLICY_WINDOW: ("That appointment's deposit is already inside the business's cancellation "
                    "window, so I can't move it on this call. Nothing has changed. Take a message "
                    "and tell the caller the team will get back to them about it."),
    STAFF_UNAVAILABLE: ("That time isn't free with the same team member, so nothing has been "
                        "moved. Call check_availability again and offer another time."),
    SLOT_TAKEN: ("That time has just been taken, so nothing has been moved. Call "
                 "check_availability again and offer the caller the open times."),
}


def _when(value) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _payment(appt_id: str) -> dict | None:
    """The paid deposit, if any. Raises if it can't be read: unknown is not 'none'."""
    return await db.get_payment_by_appointment_id(appt_id)


async def move(*, tenant: dict, tenant_id: str, vapi_call_id: str, caller_phone: str,
               appointment_ref: str, slot_ref: str) -> tuple[str, str]:
    """Returns (outcome, what the assistant may say)."""
    tz = relative_dates.tenant_tz(tenant)

    ref_status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=vapi_call_id, appointment_ref=appointment_ref, tenant_id=tenant_id,
        caller_phone=caller_phone)
    consumed = ref_status == appointment_refs.ALREADY_CONSUMED and ref
    if ref_status != appointment_refs.OK and not consumed:
        return cr.INVALID_REF, ("I couldn't find that appointment among the ones I listed. List the "
                                "caller's appointments again and confirm which one they mean.")
    offer_status, offer = await slot_offers.resolve_for_booking(
        vapi_call_id=vapi_call_id, slot_ref=slot_ref, tenant_id=tenant_id, active_location_id="")
    appt = await db.get_appointment_by_id(ref["appointment_id"])
    if not appt or str(appt.get("tenant_id")) != str(tenant_id) \
            or str(appt.get("caller_phone") or "") != caller_phone:
        return cr.INVALID_REF, _HANDOFF_MSG
    if not await square_inplace_scope.allowed(tenant_id, appt["id"]):
        # The router only sends the named test appointment here; refuse anything else.
        return HANDOFF, _HANDOFF_MSG

    if consumed:
        # This reference already moved its appointment. Answer from the re-read row.
        if offer and _when(appt["appointment_datetime"]) == _when(offer["start_at_utc"]):
            return cr.ALREADY_THERE, (f"Already done, re-read just now: the "
                                      f"{appt.get('service') or 'appointment'} is on "
                                      f"{cr._spoken(_when(appt['appointment_datetime']), tz)}. "
                                      "Don't move it again.")
        return cr.CHANGED, ("That appointment was already changed in this call. Nothing more has "
                            "been moved. List the caller's appointments again before any other change.")
    if offer_status != slot_offers.OK or not offer:
        return SLOT_TAKEN, _MESSAGES[SLOT_TAKEN]

    # Anything left unfinished for this appointment is settled first, by reading.
    live = await db_cm.live_for_appointment(appt["id"])
    if live:
        if live["state"] == "in_progress" and cr._age_seconds(live) < cr.STALE_SECONDS:
            return cr.BUSY, ("That appointment is being changed right now, so nothing was done. "
                             "Ask the caller to give us a minute." + _NO_RETRY)
        outcome = await cr.settle(tenant, live)
        if outcome != cr.COMPLETED:
            return outcome, cr._message(outcome, tz, appt, None)
        appt = await db.get_appointment_by_id(appt["id"]) or appt

    if (appt.get("status") or "") not in _ACTIVE or not appt.get("google_event_id"):
        return cr.NOT_ELIGIBLE, _HANDOFF_MSG

    from services import reschedule_intent as ri
    if not ri._same_service(ref, offer):
        return ri.SERVICE_MISMATCH, ri.message_for(ri.SERVICE_MISMATCH)

    # Same place: a single-location business's own Square location, or the same
    # adopted location (with a live binding) for a multi-location business.
    src_loc = str(appt.get("tenant_location_id") or "")
    src_pid = str(appt.get("provider_location_id") or "")
    if src_loc:
        if (str(offer.get("tenant_location_id") or "") != src_loc
                or str(offer.get("provider_location_id") or "") != src_pid
                or not await reschedule._binding_is_live(tenant_id, src_loc, src_pid)):
            return ri.CROSS_LOCATION, ri.message_for(ri.CROSS_LOCATION)
    else:
        single = await reschedule._single_location_id(tenant, tenant_id)
        if not single or (src_pid and src_pid != single) or str(offer.get("tenant_location_id") or "") \
                or str(offer.get("provider_location_id") or "") != single:
            return ri.CROSS_LOCATION, ri.message_for(ri.CROSS_LOCATION)
        src_pid = single

    token = await square_booking.get_access_token(tenant)
    if not token:
        return HANDOFF, _HANDOFF_MSG

    # ── own it, then prove the booking is still what we have on record ──────
    op_id = str(uuid.uuid4())
    own, claim = await mutation_ownership.acquire_for_reschedule(appt["id"], tenant_id, op_id)
    if own == mutation_ownership.BUSY:
        return cr.BUSY, ("That appointment is being changed right now, so nothing was done. Ask "
                         "the caller to give us a minute." + _NO_RETRY)
    if own != mutation_ownership.ACQUIRED or claim is None:
        return cr.TEMPORARY, "I had trouble with that just now. Nothing has changed. Offer to try again."

    async def _give_up(outcome: str, message: str) -> tuple[str, str]:
        await mutation_ownership.release(claim)
        return outcome, message

    current = await db.get_appointment_by_id(appt["id"])
    if (not current or (current.get("status") or "") not in _ACTIVE
            or _when(current["appointment_datetime"]) != _when(appt["appointment_datetime"])
            or str(current.get("google_event_id") or "") != str(appt["google_event_id"])):
        return await _give_up(cr.CHANGED, "That appointment changed while I was moving it. Nothing "
                                          "has been moved. List the caller's appointments again.")

    # Policy, read under ownership: a paid deposit already inside the
    # non-refundable window stays put.
    try:
        paid = await _payment(current["id"])
    except Exception as e:
        logger.error("square_inplace: payment lookup failed for %s: %s", current["id"], e)
        return await _give_up(HANDOFF, _HANDOFF_MSG)
    if paid:
        hours = tenant.get("cancellation_refund_hours")
        hours = 24 if hours is None else int(hours)
        if _when(current["appointment_datetime"]) - relative_dates._utcnow() < timedelta(hours=hours):
            return await _give_up(POLICY_WINDOW, _MESSAGES[POLICY_WINDOW])

    fetch, booking = await square_booking.get_booking_detailed(token, current["google_event_id"])
    if fetch != square_booking.FETCH_FOUND:
        return await _give_up(HANDOFF, _HANDOFF_MSG)
    src = square_booking.booking_shape(booking)
    if (src["status"] not in ("ACCEPTED", "PENDING") or src["segments"] != 1
            or src["location_id"] != src_pid or not src["team_member_id"]
            or src["start"] is None or src["start"] != _when(current["appointment_datetime"])):
        logger.warning("square_inplace: booking %s isn't what we have on record (%s)",
                       current["google_event_id"], {k: src[k] for k in ("status", "segments")})
        return await _give_up(HANDOFF, _HANDOFF_MSG)
    if src["service_variation_id"] != str(offer.get("service_variation_id") or ""):
        return await _give_up(ri.SERVICE_MISMATCH, ri.message_for(ri.SERVICE_MISMATCH))

    # The new time, for the SAME team member, length and service.
    target = _when(offer["start_at_utc"])
    if target <= relative_dates._utcnow():
        return await _give_up(SLOT_TAKEN, _MESSAGES[SLOT_TAKEN])
    seg = await square_booking.resolve_slot(token, src_pid, src["service_variation_id"],
                                            [src["team_member_id"]], target)
    if (not seg or seg.get("team_member_id") != src["team_member_id"]
            or int(seg.get("duration_minutes") or 0) != src["minutes"]):
        return await _give_up(STAFF_UNAVAILABLE, _MESSAGES[STAFF_UNAVAILABLE])
    if not await slot_offers.claim(vapi_call_id, slot_ref, tenant_id):
        return await _give_up(SLOT_TAKEN, _MESSAGES[SLOT_TAKEN])

    op = await db_cm.insert({
        "id": op_id, "tenant_id": tenant_id, "appointment_id": current["id"],
        "vapi_call_id": vapi_call_id or None, "provider": "square",
        "provider_event_id": current["google_event_id"],
        "from_start_utc": src["start"].astimezone(timezone.utc).isoformat(),
        "to_start_utc": target.astimezone(timezone.utc).isoformat(),
        "duration_minutes": src["minutes"], "state": "in_progress",
        "claim_token": claim.token, "claimed_at": claim.claimed_at,
        "provider_version": src["version"], "team_member_id": src["team_member_id"],
        "service_variation_id": src["service_variation_id"], "slot_ref": slot_ref})
    if not op:
        await slot_offers.release(vapi_call_id, slot_ref)
        return await _give_up(cr.BUSY, "Another change to that appointment is still being settled. "
                                        "Nothing was done." + _NO_RETRY)

    status, _updated, code = await square_booking.update_booking_start(
        token, current["google_event_id"], version=src["version"], start_at_iso=_z(target),
        idempotency_key=op_id)
    if status == square_booking.UPDATE_OK:
        moved = await db_cm.transition(op, ("in_progress",), {"state": "provider_moved"})
        outcome = await cr._finish_local(tenant, moved) if moved else cr.UNKNOWN
    elif status == square_booking.UPDATE_FAILED:
        logger.warning("square_inplace: Square refused the move of %s (%s)", current["id"], code)
        if await db_cm.transition(op, ("in_progress",), {"state": "failed", "detail": code or "refused"}):
            await cr._release(op)
        await slot_offers.release(vapi_call_id, slot_ref)
        outcome = cr.FAILED
    else:
        await db_cm.transition(op, ("in_progress",), {"state": "unknown", "detail": "update outcome unknown"})
        outcome = await cr.settle(tenant, await db_cm.get(op_id) or op)

    final = await db.get_appointment_by_id(current["id"]) or current
    if outcome == cr.COMPLETED:
        await appointment_refs.claim(vapi_call_id, appointment_ref)
        await slot_offers.mark_consumed(vapi_call_id, slot_ref, current["google_event_id"])
    logger.info("square_inplace: appointment %s -> %s", current["id"], outcome)
    return outcome, cr._message(outcome, tz, final, target)
