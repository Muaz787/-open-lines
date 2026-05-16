"""
Vapi mid-call tool endpoints.

Vapi calls these URLs while a call is in progress.  Each endpoint receives a
POST with the tool-call arguments and must return a { "results": [...] } JSON
response that the AI uses to continue the conversation.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from services import calendar as cal_svc
from services.calendar import CalendarTokenExpiredError
from services import telephony
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])

_CALENDAR_ERROR_MSG = (
    "I'm having a little trouble accessing the calendar right now. "
    "I'll make sure the team follows up with you shortly to confirm a time."
)


def _parse_tool_call(body: dict) -> tuple[str, str, dict]:
    """Return (tool_call_id, call_id, arguments_dict)."""
    msg = body.get("message", body)
    tool_calls = msg.get("toolCallList", [])
    if not tool_calls:
        raise ValueError("No toolCallList in payload")
    tc = tool_calls[0]
    tc_id    = tc.get("id", "")
    call_id  = (msg.get("call") or {}).get("id", "")
    raw_args = tc.get("function", {}).get("arguments", "{}")
    args     = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    return tc_id, call_id, args


def _result(tc_id: str, text: str) -> dict:
    return {"results": [{"toolCallId": tc_id, "result": text}]}


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/caller-lookup
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/caller-lookup")
async def caller_lookup(tenant_id: str, body: dict):
    try:
        tc_id, _, _ = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/caller-lookup: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    msg = body.get("message", body)
    caller_phone: str = (msg.get("call") or {}).get("customer", {}).get("number", "")

    if not caller_phone:
        return _result(tc_id, "new_caller")

    try:
        lead = await db.get_lead_by_phone(tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/caller-lookup: lead lookup failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "new_caller")

    if not lead:
        logger.info("tools/caller-lookup: new caller %s for tenant %s", caller_phone, tenant_id)
        return _result(tc_id, "new_caller")

    name = lead.get("name") or ""
    summary = lead.get("summary") or ""

    lines = [f"returning_caller: {name}" if name else "returning_caller: (name unknown)"]
    if summary:
        lines.append(f"last_call_summary: {summary}")

    try:
        upcoming = await db.get_upcoming_appointment_by_phone(tenant_id, caller_phone)
        if upcoming:
            tenant = await db.get_tenant_by_id(tenant_id)
            tz_str = (tenant or {}).get("calendar_timezone") or "America/Toronto"
            appt_dt_raw = upcoming.get("appointment_datetime", "")
            service = upcoming.get("service", "appointment")
            try:
                appt_dt = datetime.fromisoformat(appt_dt_raw)
                if appt_dt.tzinfo is None:
                    appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
                appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
                h = appt_dt.hour % 12 or 12
                ampm = "AM" if appt_dt.hour < 12 else "PM"
                friendly = f"{appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
                lines.append(f"upcoming_appointment: {service} on {friendly}")
            except Exception:
                lines.append(f"upcoming_appointment: {service}")
    except Exception as e:
        logger.warning("tools/caller-lookup: appointment lookup failed for tenant %s: %s", tenant_id, e)

    result_text = "\n".join(lines)
    logger.info("tools/caller-lookup: recognized caller %s for tenant %s", caller_phone, tenant_id)
    return _result(tc_id, result_text)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/availability
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/availability")
async def check_availability(tenant_id: str, body: dict):
    logger.info("tools/availability raw payload for tenant %s: %s", tenant_id, body)
    try:
        tc_id, _, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/availability: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    date_str = args.get("date", "")
    period   = args.get("period", "any")

    if not date_str:
        return _result(tc_id, "I need a date to check availability. What date were you thinking?")

    # Extract caller phone so we can detect a reschedule mid-call
    msg_body     = body.get("message", body)
    caller_phone = (msg_body.get("call") or {}).get("customer", {}).get("number", "")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/availability: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    refresh_token = tenant.get("google_refresh_token")
    if not refresh_token:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    duration_minutes = tenant.get("appointment_duration_minutes") or 60
    timezone         = tenant.get("calendar_timezone") or "America/Toronto"

    # If the caller already has an appointment, exclude its time block from the
    # busy check so the agent doesn't falsely report that slot as unavailable.
    exclude_range = None
    if caller_phone:
        try:
            existing = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
            if existing:
                ex_start = datetime.fromisoformat(existing["appointment_datetime"])
                if ex_start.tzinfo is None:
                    ex_start = ex_start.replace(tzinfo=ZoneInfo(timezone))
                ex_end = ex_start + timedelta(minutes=duration_minutes)
                exclude_range = (ex_start, ex_end)
                logger.info(
                    "tools/availability: reschedule detected for %s — excluding %s to %s",
                    caller_phone, ex_start.isoformat(), ex_end.isoformat(),
                )
        except Exception as e:
            logger.warning("tools/availability: existing-appt check failed: %s", e)

    try:
        slots = await cal_svc.list_free_slots(
            refresh_token=refresh_token,
            date_str=date_str,
            duration_minutes=duration_minutes,
            timezone=timezone,
            period=period,
            exclude_range=exclude_range,
        )
    except CalendarTokenExpiredError:
        logger.error("tools/availability: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
        try:
            await db.update_tenant(tenant_id, {"google_refresh_token": None})
        except Exception:
            pass
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    except Exception as e:
        logger.error("tools/availability: calendar query failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    if not slots:
        return _result(
            tc_id,
            f"Unfortunately there are no available slots on {date_str}. "
            "Would you like to try a different day?"
        )

    offer = slots[:2]
    has_more = len(slots) > 2
    offer_text = " or ".join(offer)
    msg = f"I have {offer_text} available on {date_str} — does either of those work for you?"
    if has_more:
        msg += " I have more times if neither works."
    return _result(tc_id, msg)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/book
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/book")
async def book_appointment(tenant_id: str, body: dict):
    try:
        tc_id, call_id, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/book: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    # Prefer caller phone from Vapi call metadata (more reliable than AI-provided)
    msg = body.get("message", body)
    caller_phone_from_meta = (msg.get("call") or {}).get("customer", {}).get("number", "")

    caller_name  = args.get("caller_name", "")
    caller_phone = caller_phone_from_meta or args.get("caller_phone", "")
    service      = args.get("service", "Appointment")
    date_str     = args.get("date", "")
    time_str     = args.get("time", "")  # HH:MM 24-hour

    if not date_str or not time_str:
        return _result(tc_id, "I need both a date and a time to complete the booking. Could you confirm those?")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/book: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    refresh_token    = tenant.get("google_refresh_token")
    duration_minutes = tenant.get("appointment_duration_minutes") or 60
    timezone         = tenant.get("calendar_timezone") or "America/Toronto"
    business_name    = tenant["business_name"]

    if not refresh_token:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        tz = ZoneInfo(timezone)
        naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        start_dt = naive_dt.replace(tzinfo=tz)
    except Exception as e:
        logger.error("tools/book: datetime parse failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "I couldn't parse that date and time. Could you say it again?")

    # Cancel existing appointment for this caller (reschedule flow).
    # Look back 24h so same-day reschedules are caught even if the slot has passed.
    existing_appt = None
    if caller_phone:
        try:
            existing_appt = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
        except Exception as e:
            logger.warning("tools/book: appointment lookup failed for tenant %s: %s", tenant_id, e)

        if existing_appt:
            old_event_id = existing_appt.get("google_event_id", "")
            if old_event_id:
                try:
                    await cal_svc.cancel_event(refresh_token, old_event_id)
                    logger.info("Cancelled old event %s for reschedule (tenant %s)", old_event_id, tenant_id)
                except CalendarTokenExpiredError:
                    logger.error("tools/book: calendar token expired during reschedule for tenant %s — auto-disconnecting", tenant_id)
                    try:
                        await db.update_tenant(tenant_id, {"google_refresh_token": None})
                    except Exception:
                        pass
                    return _result(tc_id, _CALENDAR_ERROR_MSG)
                except Exception as e:
                    logger.warning("tools/book: could not delete old calendar event %s: %s", old_event_id, e)

    try:
        description = (
            f"Booked via Open Lines AI receptionist.\n"
            f"Service: {service}\n"
            f"Caller: {caller_name}\n"
            f"Phone: {caller_phone}"
        )
        event = await cal_svc.create_event(
            refresh_token=refresh_token,
            title=f"{service} — {caller_name}" if caller_name else service,
            start_dt=start_dt,
            duration_minutes=duration_minutes,
            timezone=timezone,
            description=description,
        )
        logger.info(
            "Booked appointment for tenant %s: %s on %s at %s (event %s)",
            tenant_id, service, date_str, time_str, event.get("id"),
        )
    except CalendarTokenExpiredError:
        logger.error("tools/book: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
        try:
            await db.update_tenant(tenant_id, {"google_refresh_token": None})
        except Exception:
            pass
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    except Exception as e:
        logger.error("tools/book: calendar event creation failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        appt_data = {
            "tenant_id":             tenant_id,
            "caller_name":           caller_name,
            "caller_phone":          caller_phone,
            "service":               service,
            "appointment_datetime":  start_dt.isoformat(),
            "duration_minutes":      duration_minutes,
            "status":                "confirmed",
            "vapi_call_id":          call_id,
            "google_event_id":       event.get("id", ""),
        }
        if existing_appt:
            await db.update_appointment(existing_appt["id"], appt_data)
        else:
            await db.insert_appointment(appt_data)
    except Exception as e:
        logger.error("tools/book: failed to save appointment for tenant %s: %s", tenant_id, e)
        # Don't fail the whole response — event was created in Google, just log the DB miss

    # Friendly confirmation string for the AI
    h = start_dt.hour % 12 or 12
    ampm = "AM" if start_dt.hour < 12 else "PM"
    friendly = f"{start_dt.strftime('%A, %B')} {start_dt.day} at {h}:{start_dt.minute:02d} {ampm}"

    # Send SMS confirmation now — more reliable than waiting for end-of-call-report
    try:
        subaccount_sid   = tenant.get("twilio_subaccount_sid", "")
        subaccount_token = tenant.get("twilio_auth_token", "")
        business_phone   = tenant.get("twilio_phone_number", "")
        if subaccount_sid and subaccount_token and business_phone and caller_phone:
            greeting = f"Hi {caller_name}! " if caller_name else ""
            sms_body = (
                f"{greeting}Your {service} at {business_name} is confirmed "
                f"for {friendly}. See you then! — {business_name}"
            )
            await telephony.send_sms(
                subaccount_sid=subaccount_sid,
                subaccount_token=subaccount_token,
                from_number=business_phone,
                to_number=caller_phone,
                body=sms_body,
            )
            logger.info("Appointment SMS sent to %s for tenant %s", caller_phone, tenant_id)
    except Exception as e:
        logger.error("tools/book: SMS failed for tenant %s: %s", tenant_id, e)

    confirmation = (
        f"Done! Your {service} at {business_name} is confirmed for {friendly}. "
        "You'll receive a text confirmation shortly."
    )
    return _result(tc_id, confirmation)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/cancel")
async def cancel_appointment(tenant_id: str, body: dict):
    try:
        tc_id, _, _ = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/cancel: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    msg = body.get("message", body)
    caller_phone = (msg.get("call") or {}).get("customer", {}).get("number", "")

    if not caller_phone:
        return _result(tc_id, "I wasn't able to find your phone number to look up the appointment. Could you confirm the number on file?")

    try:
        appt = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/cancel: appointment lookup failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble looking up your appointment. Please call back and we'll get that sorted.")

    if not appt:
        return _result(tc_id, "I don't see any upcoming appointment for your number. Is it possible it's under a different phone number?")

    # Cancel Google Calendar event
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/cancel: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble processing the cancellation. Please call back and we'll get that sorted.")

    refresh_token = (tenant or {}).get("google_refresh_token")
    event_id = appt.get("google_event_id", "")

    if refresh_token and event_id:
        try:
            await cal_svc.cancel_event(refresh_token, event_id)
        except CalendarTokenExpiredError:
            logger.error("tools/cancel: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
            try:
                await db.update_tenant(tenant_id, {"google_refresh_token": None})
            except Exception:
                pass
        except Exception as e:
            logger.warning("tools/cancel: could not delete calendar event %s: %s", event_id, e)

    # Mark appointment cancelled in DB
    try:
        await db.update_appointment(appt["id"], {**appt, "status": "cancelled"})
    except Exception as e:
        logger.error("tools/cancel: failed to update appointment status for tenant %s: %s", tenant_id, e)

    service  = appt.get("service", "appointment")
    appt_dt_raw = appt.get("appointment_datetime", "")
    friendly = appt_dt_raw
    try:
        tz_str  = (tenant or {}).get("calendar_timezone") or "America/Toronto"
        appt_dt = datetime.fromisoformat(appt_dt_raw)
        if appt_dt.tzinfo is None:
            appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
        appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
        h    = appt_dt.hour % 12 or 12
        ampm = "AM" if appt_dt.hour < 12 else "PM"
        friendly = f"{appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
    except Exception:
        pass

    logger.info("Cancelled appointment %s for tenant %s caller %s", appt["id"], tenant_id, caller_phone)
    return _result(tc_id, f"Done — your {service} on {friendly} has been cancelled. Is there anything else I can help you with?")
