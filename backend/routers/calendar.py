import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from services import calendar as cal_svc
from services.calendar import CalendarTokenExpiredError
import httpx
from services import vapi
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])

_raw_frontend = os.getenv("FRONTEND_URL", "https://openlines.ai")
FRONTEND_URL = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"

_CALENDAR_NOTE = """

CALENDAR BOOKING TOOLS AVAILABLE
You have access to three tools for managing appointments in real time:
- check_availability: use this when the caller mentions wanting to book and gives a date or day preference.
- book_appointment: use this ONLY after the caller has confirmed a specific date AND time slot.
- cancel_appointment: use this ONLY after the caller has explicitly confirmed they want to cancel.

When booking:
1. Ask "What day were you thinking?" if the caller hasn't given a date.
2. Call check_availability, then offer only the FIRST TWO available slots: "I have [time1] or [time2] available — does either work for you?"
3. If neither works, offer the next two slots. Never read out all slots at once.
4. Once the caller picks a slot, confirm: "Perfect — just to confirm, [service] on [date] at [time]?"
5. After they say yes, call book_appointment immediately.
6. Tell the caller the booking is confirmed and they'll get a text shortly.
Do NOT say "our team will confirm with you" — you are confirming it now.

When cancelling:
1. Confirm: "Just to confirm, you'd like to cancel your upcoming appointment?"
2. After they say yes, call cancel_appointment immediately.
3. Tell the caller the appointment has been cancelled."""


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

    cal_page = f"{FRONTEND_URL}/dashboard/{tenant_id}/calendar"

    if error:
        logger.warning("Google OAuth error for tenant %s: %s", tenant_id, error)
        return RedirectResponse(f"{cal_page}?calendar=error")

    # Exchange code for tokens
    try:
        tokens = await cal_svc.exchange_code(code)
    except Exception as e:
        logger.error("Token exchange failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{cal_page}?calendar=error")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        logger.error("No refresh_token in Google response for tenant %s", tenant_id)
        return RedirectResponse(f"{cal_page}?calendar=error")

    # Validate the token works before storing — catches bad tokens from Testing-mode
    # expiry edge cases or misconfigured OAuth apps before they silently break calls.
    token_ok = await cal_svc.verify_token(refresh_token)
    if not token_ok:
        logger.error("Token verification failed immediately after exchange for tenant %s — rejecting", tenant_id)
        return RedirectResponse(f"{cal_page}?calendar=error")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        return RedirectResponse(f"{cal_page}?calendar=error")

    if not tenant:
        return RedirectResponse(f"{cal_page}?calendar=error")

    # Store refresh token
    try:
        await db.update_tenant(tenant_id, {"google_refresh_token": refresh_token})
    except Exception as e:
        logger.error("Failed to store Google refresh token for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{cal_page}?calendar=error")

    # Patch Vapi assistant with calendar tools + updated system prompt
    assistant_id = tenant.get("vapi_assistant_id")
    if assistant_id:
        try:
            tenant_key = vapi.get_tenant_vapi_key(tenant)
            tools = vapi.build_calendar_tools(tenant_id)
            # Fetch current assistant to get existing system prompt
            current = await vapi.get_assistant(assistant_id, api_key=tenant_key)
            raw_messages = (current.get("model") or {}).get("messages") or []
            # Strip to role+content only — Vapi GET may return extra metadata fields
            messages = [{"role": m["role"], "content": m["content"]} for m in raw_messages if m.get("role") and m.get("content")]
            if messages and messages[0].get("role") == "system":
                existing_prompt = messages[0]["content"]
                if "CALENDAR BOOKING TOOLS AVAILABLE" in existing_prompt:
                    existing_prompt = existing_prompt[:existing_prompt.index("\n\nCALENDAR BOOKING TOOLS AVAILABLE")]
                messages[0]["content"] = existing_prompt + _CALENDAR_NOTE
            await vapi.update_assistant(assistant_id, {
                "model": {
                    "provider": "openai", "model": "gpt-4o", "temperature": 0.7,
                    "tools": tools, "messages": messages,
                },
            }, api_key=tenant_key)
        except Exception as e:
            logger.error("Failed to update Vapi assistant %s with calendar tools: %s", assistant_id, e)
            # Non-fatal: calendar is connected, tools just aren't live yet

    logger.info("Google Calendar connected for tenant %s", tenant_id)
    return RedirectResponse(f"{cal_page}?calendar=connected")


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
            tenant_key = vapi.get_tenant_vapi_key(tenant)
            current = await vapi.get_assistant(assistant_id, api_key=tenant_key)
            raw_messages = (current.get("model") or {}).get("messages") or []
            messages = [{"role": m["role"], "content": m["content"]} for m in raw_messages if m.get("role") and m.get("content")]
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
            }, api_key=tenant_key)
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

@router.post("/repair/{tenant_id}")
async def calendar_repair(tenant_id: str):
    """Force-update the Vapi assistant tool URLs to the current APP_BACKEND_URL."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    assistant_id = tenant.get("vapi_assistant_id")
    if not assistant_id:
        raise HTTPException(status_code=400, detail="No Vapi assistant on this tenant")

    tools = vapi.build_calendar_tools(tenant_id) if tenant.get("google_refresh_token") \
        else [vapi.build_caller_lookup_tool(tenant_id)]

    # Try tools-only patch first (avoids any issues with messages format)
    tenant_key = vapi.get_tenant_vapi_key(tenant)
    import httpx as _httpx
    async with _httpx.AsyncClient() as client:
        res = await client.patch(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers=vapi._headers(tenant_key),
            json={"model": {"provider": "openai", "model": "gpt-4o", "tools": tools}},
            timeout=30.0,
        )
        if res.status_code != 200:
            return {
                "status": "error",
                "vapi_status": res.status_code,
                "vapi_error": res.text,
                "attempted_urls": {t["function"]["name"]: t["server"]["url"] for t in tools},
            }

    tool_urls = {t["function"]["name"]: t["server"]["url"] for t in tools}
    logger.info("Repaired Vapi tool URLs for tenant %s: %s", tenant_id, tool_urls)
    return {"status": "repaired", "tool_urls": tool_urls}


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


# ---------------------------------------------------------------------------
# GET /calendar/debug/{tenant_id}  — diagnose exactly where the failure is
# ---------------------------------------------------------------------------

@router.get("/debug/{tenant_id}")
async def calendar_debug(tenant_id: str):
    result: dict = {}

    # Step 1: tenant + token
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        return {"step": "tenant_lookup", "error": str(e)}

    refresh_token = (tenant or {}).get("google_refresh_token")
    result["has_refresh_token"] = bool(refresh_token)
    result["timezone"] = tenant.get("calendar_timezone") or "America/Toronto"
    if not refresh_token:
        return {**result, "step": "no_token", "error": "google_refresh_token is null in DB"}

    # Step 2: exchange refresh token for access token
    try:
        access_token = await cal_svc._access_token(refresh_token)
        result["access_token_ok"] = True
    except CalendarTokenExpiredError as e:
        result["access_token_ok"] = False
        return {**result, "step": "access_token", "error": f"CalendarTokenExpiredError: {e}"}
    except Exception as e:
        result["access_token_ok"] = False
        return {**result, "step": "access_token", "error": str(e)}

    # Step 3: events.list for today
    tz = ZoneInfo(result["timezone"])
    today = datetime.now(tz).date()
    time_min = datetime(today.year, today.month, today.day, 9,  0, tzinfo=tz).isoformat()
    time_max = datetime(today.year, today.month, today.day, 17, 0, tzinfo=tz).isoformat()
    try:
        async with httpx.AsyncClient() as http:
            res = await http.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "orderBy": "startTime"},
                timeout=15.0,
            )
        result["events_list_status"] = res.status_code
        if res.status_code == 200:
            result["events_list_ok"] = True
            result["event_count"] = len(res.json().get("items", []))
        else:
            result["events_list_ok"] = False
            result["events_list_error"] = res.text
    except Exception as e:
        result["events_list_ok"] = False
        result["events_list_error"] = str(e)

    # Step 4: run list_free_slots end-to-end (same path as the tool call)
    tomorrow = datetime.now(tz).date()
    from datetime import timedelta
    tomorrow_str = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        slots = await cal_svc.list_free_slots(
            refresh_token=refresh_token,
            date_str=tomorrow_str,
            duration_minutes=tenant.get("appointment_duration_minutes") or 60,
            timezone=result["timezone"],
            period="any",
        )
        result["slots_test_ok"] = True
        result["slots_date"] = tomorrow_str
        result["slots"] = slots
    except Exception as e:
        result["slots_test_ok"] = False
        result["slots_error"] = str(e)

    # Step 5: check what tools Vapi assistant has configured
    assistant_id = tenant.get("vapi_assistant_id")
    result["vapi_assistant_id"] = assistant_id
    if assistant_id:
        try:
            current = await vapi.get_assistant(assistant_id)
            tools = (current.get("model") or {}).get("tools") or []
            tool_names = [t.get("function", {}).get("name") for t in tools]
            result["vapi_tool_names"] = tool_names
            result["has_check_availability"] = "check_availability" in tool_names
            result["has_book_appointment"] = "book_appointment" in tool_names
            result["vapi_tool_urls"] = {
                t.get("function", {}).get("name"): (t.get("server") or {}).get("url")
                for t in tools
            }
        except Exception as e:
            result["vapi_tools_error"] = str(e)

    return result
