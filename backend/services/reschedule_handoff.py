"""
When the assistant can't move an appointment and promises that the team will,
make that promise real: record a callback request and alert the owner.

On 7 Nov a caller asked to move a deposit appointment from Nov 11 to Nov 12 at
9 AM. The tool told the assistant to "take a message", the assistant told the
caller the team would reach out, and nothing recorded it. The only trace was
the end-of-call summary.

Now every reschedule outcome that hands the appointment to the team writes one
callback_requests row (appointment, current time, the time the caller wanted,
why it wasn't moved) and alerts the owner by email and SMS, following their
notification settings. It is best-effort and never raises. A failure is logged
and the call goes on as before.

Duplicates: one row per caller, appointment and requested time while it is
still open, and the email carries an idempotency key, so a retried tool call
doesn't page the owner twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Outcome values (strings shared by services.reschedule_intent,
# services.square_inplace_reschedule and services.calendar_reschedule) whose
# message tells the caller the team will follow up.
PLAN_NO_WRITES = "plan_no_writes"   # seller's Square plan refuses app writes

SQUARE_FOLLOW_UP = frozenset({
    PLAN_NO_WRITES, "payment_on_file", "handoff", "policy_window", "not_eligible", "unresolved",
    "source_changed", "cancel_failed", "cross_location", "temporary", "busy",
    "unknown", "local_pending",
})
CALENDAR_FOLLOW_UP = frozenset({"unknown", "local_pending", "not_eligible"})

_WHY = {
    PLAN_NO_WRITES: "the business's Square plan doesn't let the assistant change bookings",
    "payment_on_file": "it has a deposit and deposit moves are switched off",
    "handoff": "it couldn't be confirmed safe to move automatically",
    "policy_window": "its paid deposit is already inside your cancellation window",
    "not_eligible": "it isn't one the assistant can move",
    "unresolved": "the calendar didn't confirm whether the move went through",
    "unknown": "the calendar didn't confirm whether the move went through",
    "local_pending": "the calendar moved it but our record hasn't caught up",
    "source_changed": "it was changed by the business while the caller was on the line",
    "cancel_failed": "the new time was booked but the old one couldn't be cancelled",
    "cross_location": "the caller wants a different location",
    "temporary": "the calendar couldn't be reached",
    "busy": "it was already being changed elsewhere",
}


def _parse(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _spoken(dt: datetime | None, tz) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(tz)
    h = local.hour % 12 or 12
    return (f"{local.strftime('%a %b')} {local.day}, {h}:{local.minute:02d} "
            f"{'AM' if local.hour < 12 else 'PM'}")


def reason_text(appt: dict, requested: str, outcome: str, tz) -> str:
    """The line the owner reads: what, when, wanted when, why not."""
    service = appt.get("service") or "appointment"
    now_at = _spoken(_parse(appt.get("appointment_datetime")), tz) or "unknown time"
    wanted = f" to {requested}" if requested else ""
    why = _WHY.get(outcome, "the assistant couldn't complete it")
    return (f"Reschedule request: move {service} on {now_at}{wanted}. "
            f"Not moved on the call because {why}.")


async def _requested_time(*, call_id: str, tenant_id: str, slot_ref: str,
                          date_str: str, time_str: str, tz) -> str:
    if slot_ref:
        try:
            from services import slot_offers
            _status, offer = await slot_offers.resolve_for_booking(
                vapi_call_id=call_id, slot_ref=slot_ref, tenant_id=tenant_id,
                active_location_id="")
            if offer:
                return _spoken(_parse(offer.get("start_at_utc")), tz)
        except Exception as e:
            logger.warning("reschedule_handoff: offer lookup failed: %s", e)
        return ""
    return " ".join(p for p in (date_str, time_str) if p)


async def record(*, tenant: dict, tenant_id: str, call_id: str, caller_phone: str,
                 appointment_ref: str, outcome: str, slot_ref: str = "",
                 date_str: str = "", time_str: str = "") -> bool:
    """Record the handoff and alert the owner. True when a new request was stored."""
    try:
        return await _record(tenant=tenant, tenant_id=tenant_id, call_id=call_id,
                             caller_phone=caller_phone, appointment_ref=appointment_ref,
                             outcome=outcome, slot_ref=slot_ref, date_str=date_str,
                             time_str=time_str)
    except Exception as e:
        logger.error("reschedule_handoff: failed for tenant %s call %s: %s", tenant_id, call_id, e)
        return False


async def _record(*, tenant, tenant_id, call_id, caller_phone, appointment_ref, outcome,
                  slot_ref, date_str, time_str) -> bool:
    from db import routing as rdb
    from db import supabase as db
    from services import appointment_refs, relative_dates

    tz = relative_dates.tenant_tz(tenant)
    _status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=call_id, appointment_ref=appointment_ref, tenant_id=tenant_id,
        caller_phone=caller_phone)
    appt = {}
    if ref and ref.get("appointment_id"):
        appt = await db.get_appointment_by_id(ref["appointment_id"]) or {}
    if appt and (str(appt.get("tenant_id")) != str(tenant_id)
                 or str(appt.get("caller_phone") or "") != caller_phone):
        appt = {}
    requested = await _requested_time(call_id=call_id, tenant_id=tenant_id, slot_ref=slot_ref,
                                      date_str=date_str, time_str=time_str, tz=tz)
    reason = reason_text(appt or (ref or {}), requested, outcome, tz)
    caller_name = (appt or {}).get("caller_name") or ""

    open_rows = await rdb.list_callbacks(tenant_id, status="open")
    if any(r.get("reason") == reason and (r.get("caller_phone") or "") == caller_phone
           for r in open_rows):
        logger.info("reschedule_handoff: already recorded for tenant %s call %s", tenant_id, call_id)
        return False

    await rdb.create_callback(tenant_id, {
        "call_id": None, "caller_name": caller_name, "caller_phone": caller_phone,
        "reason": reason, "urgency": "normal", "status": "open",
    })
    logger.info("reschedule_handoff: recorded %s for tenant %s call %s", outcome, tenant_id, call_id)
    await _alert_owner(tenant, tenant_id=tenant_id, call_id=call_id,
                       appointment_id=str((appt or {}).get("id") or appointment_ref),
                       caller_name=caller_name, caller_phone=caller_phone, reason=reason)
    return True


async def _alert_owner(tenant: dict, *, tenant_id, call_id, appointment_id, caller_name,
                       caller_phone, reason) -> None:
    business = tenant.get("business_name") or ""
    to = tenant.get("notification_email") or ""
    if to and tenant.get("email_enabled", True):
        try:
            from services.email import send_reschedule_request_email
            await send_reschedule_request_email(
                to=to, business_name=business, caller_name=caller_name,
                caller_number=caller_phone, reason=reason, tenant_id=tenant_id,
                idempotency_key=f"reschedule-handoff:{call_id}:{appointment_id}")
        except Exception as e:
            logger.error("reschedule_handoff: email failed for tenant %s: %s", tenant_id, e)
    try:
        from services.owner_notify import send_owner_sms_whatsapp
        who = f"{caller_name} ({caller_phone})" if caller_name else caller_phone
        await send_owner_sms_whatsapp(
            tenant, sms_body=f"📅 Call back {who}. {reason} — {business}",
            wa_template_sid="", wa_vars={}, event="reschedule_handoff")
    except Exception as e:
        logger.error("reschedule_handoff: SMS failed for tenant %s: %s", tenant_id, e)


def assistant_note(recorded: bool) -> str:
    """Appended to the tool result so the assistant doesn't take it all down again."""
    if not recorded:
        return ""
    return (" This request, including the time the caller wanted, has already been sent "
            "to the team, so you don't need to take it down again. Just tell the caller "
            "the team will be in touch to confirm.")
