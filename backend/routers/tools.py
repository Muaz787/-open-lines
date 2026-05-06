"""
Vapi mid-call tool endpoints.

Vapi calls these URLs while a call is in progress.  Each endpoint receives a
POST with the tool-call arguments and must return a { "results": [...] } JSON
response that the AI uses to continue the conversation.
"""

import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from services import calendar as cal_svc
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

    try:
        slots = await cal_svc.list_free_slots(
            refresh_token=refresh_token,
            date_str=date_str,
            duration_minutes=duration_minutes,
            timezone=timezone,
            period=period,
        )
    except Exception as e:
        logger.error("tools/availability: calendar query failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    if not slots:
        return _result(
            tc_id,
            f"Unfortunately there are no available slots on {date_str}. "
            "Would you like to try a different day?"
        )

    slots_text = ", ".join(slots)
    return _result(tc_id, f"Available times on {date_str}: {slots_text}. Which works best for you?")


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
    except Exception as e:
        logger.error("tools/book: calendar event creation failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        await db.insert_appointment({
            "tenant_id":             tenant_id,
            "caller_name":           caller_name,
            "caller_phone":          caller_phone,
            "service":               service,
            "appointment_datetime":  start_dt.isoformat(),
            "duration_minutes":      duration_minutes,
            "status":                "confirmed",
            "vapi_call_id":          call_id,
            "google_event_id":       event.get("id", ""),
        })
    except Exception as e:
        logger.error("tools/book: failed to save appointment for tenant %s: %s", tenant_id, e)
        # Don't fail the whole response — event was created in Google, just log the DB miss

    # Friendly confirmation string for the AI
    h = start_dt.hour % 12 or 12
    ampm = "AM" if start_dt.hour < 12 else "PM"
    friendly = f"{start_dt.strftime('%A, %B')} {start_dt.day} at {h}:{start_dt.minute:02d} {ampm}"

    confirmation = (
        f"Done! Your {service} at {business_name} is confirmed for {friendly}. "
        "You'll receive a text confirmation shortly."
    )
    return _result(tc_id, confirmation)
