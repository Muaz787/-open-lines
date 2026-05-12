import os
import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from services import calendar as cal_svc
from services import vapi
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])

_raw_frontend = os.getenv("FRONTEND_URL", "https://open-lines.vercel.app")
FRONTEND_URL = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"

_CALENDAR_NOTE = """

CALENDAR BOOKING TOOLS AVAILABLE
You have access to two tools that let you book appointments in real time:
- check_availability: use this when the caller mentions wanting to book and gives a date or day preference.
- book_appointment: use this ONLY after the caller has confirmed a specific date AND time slot.

When using these tools:
1. Ask "What day were you thinking?" if the caller hasn't given a date.
2. Call check_availability, then offer only the FIRST TWO available slots: "I have [time1] or [time2] available — does either work for you?"
3. If neither works, offer the next two slots. Never read out all slots at once.
4. Once the caller picks a slot, confirm: "Perfect — just to confirm, [service] on [date] at [time]?"
5. After they say yes, call book_appointment immediately.
6. Tell the caller the booking is confirmed and they'll get a text shortly.
Do NOT say "our team will confirm with you" — you are confirming it now."""


class CalendarSettingsRequest(BaseModel):
    appointment_duration_minutes: int | None = None
    calendar_timezone: str | None = None


# ---------------------------------------------------------------------------
# GET /calendar/connect/{tenant_id}  — start OAuth flow
# ---------------------------------------------------------------------------

@router.get("/connect/{tenant_id}")
async def calendar_connect(tenant_id: str):
    try:
        url = cal_svc.build_oauth_url(state=tenant_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# GET /calendar/callback  — Google redirects here after authorisation
# ---------------------------------------------------------------------------

@router.get("/callback")
async def calendar_callback(code: str, state: str, error: str | None = None):
    tenant_id = state

    if error:
        logger.warning("Google OAuth error for tenant %s: %s", tenant_id, error)
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    # Exchange code for tokens
    try:
        tokens = await cal_svc.exchange_code(code)
    except Exception as e:
        logger.error("Token exchange failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        logger.error("No refresh_token in Google response for tenant %s", tenant_id)
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    if not tenant:
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    # Store refresh token
    try:
        await db.update_tenant(tenant_id, {"google_refresh_token": refresh_token})
    except Exception as e:
        logger.error("Failed to store Google refresh token for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=error")

    # Patch Vapi assistant with calendar tools + updated system prompt
    assistant_id = tenant.get("vapi_assistant_id")
    if assistant_id:
        try:
            tools = vapi.build_calendar_tools(tenant_id)
            # Fetch current assistant to get existing system prompt
            current = await vapi.get_assistant(assistant_id)
            messages = (current.get("model") or {}).get("messages") or []
            if messages and messages[0].get("role") == "system":
                existing_prompt = messages[0]["content"]
                # Remove any previously appended calendar note, then re-append fresh
                if "CALENDAR BOOKING TOOLS AVAILABLE" in existing_prompt:
                    existing_prompt = existing_prompt[:existing_prompt.index("\n\nCALENDAR BOOKING TOOLS AVAILABLE")]
                messages[0]["content"] = existing_prompt + _CALENDAR_NOTE
            await vapi.update_assistant(assistant_id, {
                "model": {
                    "provider": "openai", "model": "gpt-4o", "temperature": 0.7,
                    "tools": tools, "messages": messages,
                },
            })
        except Exception as e:
            logger.error("Failed to update Vapi assistant %s with calendar tools: %s", assistant_id, e)
            # Non-fatal: calendar is connected, tools just aren't live yet

    logger.info("Google Calendar connected for tenant %s", tenant_id)
    return RedirectResponse(f"{FRONTEND_URL}/dashboard/{tenant_id}?calendar=connected")


# ---------------------------------------------------------------------------
# GET /calendar/status/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/status/{tenant_id}")
async def calendar_status(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "connected":                    bool(tenant.get("google_refresh_token")),
        "appointment_duration_minutes": tenant.get("appointment_duration_minutes") or 60,
        "calendar_timezone":            tenant.get("calendar_timezone") or "America/Toronto",
    }


# ---------------------------------------------------------------------------
# POST /calendar/disconnect/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/disconnect/{tenant_id}")
async def calendar_disconnect(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    assistant_id = tenant.get("vapi_assistant_id")
    if assistant_id:
        try:
            current = await vapi.get_assistant(assistant_id)
            messages = (current.get("model") or {}).get("messages") or []
            if messages and messages[0].get("role") == "system":
                existing_prompt = messages[0]["content"]
                if "CALENDAR BOOKING TOOLS AVAILABLE" in existing_prompt:
                    existing_prompt = existing_prompt[:existing_prompt.index("\n\nCALENDAR BOOKING TOOLS AVAILABLE")]
                messages[0]["content"] = existing_prompt
            await vapi.update_assistant(assistant_id, {
                "model": {
                    "provider": "openai", "model": "gpt-4o", "temperature": 0.7,
                    "tools": [vapi.build_caller_lookup_tool(tenant_id)], "messages": messages,
                },
            })
        except Exception as e:
            logger.error("Failed to remove calendar tools from assistant %s: %s", assistant_id, e)

    try:
        await db.update_tenant(tenant_id, {"google_refresh_token": None})
    except Exception as e:
        logger.error("Failed to clear Google token for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to disconnect calendar")

    logger.info("Google Calendar disconnected for tenant %s", tenant_id)
    return {"status": "disconnected"}


# ---------------------------------------------------------------------------
# PATCH /calendar/settings/{tenant_id}
# ---------------------------------------------------------------------------

@router.patch("/settings/{tenant_id}")
async def update_calendar_settings(tenant_id: str, body: CalendarSettingsRequest):
    updates: dict = {}
    if body.appointment_duration_minutes is not None:
        updates["appointment_duration_minutes"] = body.appointment_duration_minutes
    if body.calendar_timezone is not None:
        updates["calendar_timezone"] = body.calendar_timezone

    if not updates:
        return {"status": "no changes"}

    try:
        await db.update_tenant(tenant_id, updates)
    except Exception as e:
        logger.error("Failed to update calendar settings for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Settings update failed")

    return {"status": "updated"}


# ---------------------------------------------------------------------------
# GET /calendar/appointments/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/appointments/{tenant_id}")
async def get_appointments(tenant_id: str):
    try:
        appts = await db.get_appointments(tenant_id)
    except Exception as e:
        logger.error("Appointments fetch failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Appointments fetch failed")
    return appts
