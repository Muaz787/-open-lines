import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException

from db import supabase as db
from services import knowledge, vapi as vapi_svc
from services.vapi import _CALLER_LOOKUP_NOTE, build_caller_lookup_tool, build_calendar_tools
from routers.calendar import _CALENDAR_NOTE

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _handle_assistant_request(msg: dict) -> dict:
    """
    Return a personalized assistant config for an incoming call.
    Injects caller context and today's date so the AI greets the caller by name
    immediately, without any mid-call tool lookup.
    """
    phone_obj: dict = msg.get("phoneNumber") or {}
    called_number: str = (
        phone_obj.get("number")
        or phone_obj.get("twilioPhoneNumber")
        or ""
    )
    caller_phone: str = (msg.get("call") or {}).get("customer", {}).get("number", "")

    if not called_number:
        logger.error("assistant-request: no called_number in payload")
        return {"error": {"message": "No phone number in request"}}

    try:
        tenant = await db.get_tenant_by_phone(called_number)
    except Exception as e:
        logger.error("assistant-request: tenant lookup failed for %s: %s", called_number, e)
        return {"error": {"message": "Tenant lookup failed"}}

    if not tenant:
        return {"error": {"message": f"No tenant for {called_number}"}}

    tenant_id: str = tenant["id"]
    assistant_id: str = tenant.get("vapi_assistant_id", "")
    base_prompt: str = tenant.get("last_system_prompt") or ""

    if not assistant_id:
        return {"error": {"message": "No assistant configured"}}

    if not base_prompt:
        logger.warning(
            "assistant-request: tenant %s missing last_system_prompt — fetching from Vapi",
            tenant_id,
        )
        try:
            tenant_key = vapi_svc.get_tenant_vapi_key(tenant)
            current = await vapi_svc.get_assistant(assistant_id, api_key=tenant_key)
            raw_msgs = (current.get("model") or {}).get("messages") or []
            base_prompt = next(
                (m["content"] for m in raw_msgs if m.get("role") == "system" and m.get("content")),
                "",
            )
            if base_prompt:
                # Cache it so future calls skip this round-trip
                asyncio.create_task(db.update_tenant(tenant_id, {"last_system_prompt": base_prompt}))
        except Exception as e:
            logger.error(
                "assistant-request: could not fetch Vapi prompt for tenant %s: %s — falling back to assistantId only",
                tenant_id, e,
            )
            return {"assistantId": assistant_id}

    # Today's date in tenant timezone
    tz_str: str = tenant.get("calendar_timezone") or "America/Toronto"
    today = datetime.now(ZoneInfo(tz_str))
    date_note = (
        f"\n\nTODAY'S DATE: {today.strftime('%A, %B %d, %Y')} ({today.strftime('%Y-%m-%d')}). "
        f"The current year is {today.year}. "
        "Resolve ALL date references to a full YYYY-MM-DD date before passing to any tool: "
        "• 'today' / 'tomorrow' / 'next Monday' → count forward from today. "
        f"• Month + day with NO year (e.g. 'May 29th', 'June 3rd') → ALWAYS use {today.year}. "
        "NEVER use a past year. NEVER guess — derive the date from what the caller actually said."
    )

    # Try multiple payload paths for caller phone — Vapi may vary the structure
    # between assistant-request and other event types
    _call_obj = msg.get("call") or {}
    _customer  = _call_obj.get("customer") or {}
    caller_phone = (
        _customer.get("number", "")
        or _customer.get("phoneNumber", "")
        or (msg.get("customer") or {}).get("number", "")
        or (msg.get("customer") or {}).get("phoneNumber", "")
    )

    # Caller context
    caller_context = ""
    personalized_greeting = tenant.get("greeting_template", "")

    if caller_phone:
        try:
            lead = await db.get_lead_by_phone(tenant_id, caller_phone)
            if lead:
                name = lead.get("name") or ""
                summary = lead.get("summary") or ""
                lines = [f"RETURNING CALLER: {name}" if name else "RETURNING CALLER (name not captured yet)"]
                lines.append(f"Caller phone: {caller_phone}")
                if summary:
                    lines.append(f"Last call summary: {summary}")
                try:
                    upcoming = await db.get_upcoming_appointment_by_phone(tenant_id, caller_phone)
                    if upcoming:
                        service = upcoming.get("service", "appointment")
                        appt_dt_raw = upcoming.get("appointment_datetime", "")
                        appt_dt = datetime.fromisoformat(appt_dt_raw)
                        if appt_dt.tzinfo is None:
                            appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
                        appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
                        h = appt_dt.hour % 12 or 12
                        ampm = "AM" if appt_dt.hour < 12 else "PM"
                        friendly = f"{appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
                        lines.append(f"Upcoming appointment: {service} on {friendly}")
                except Exception:
                    pass
                # Explicit override: tell the AI to skip onboarding immediately
                lines.append(
                    "‼ SKIP ALL onboarding questions — do NOT ask for name, spelling, "
                    "new-or-existing status, or any info you already have above."
                )
                caller_context = (
                    "\n\nCALLER CONTEXT (this caller has called before — use this immediately in your greeting):\n"
                    + "\n".join(lines)
                )
                greeting_name = name or "there"
                personalized_greeting = f"Hey {greeting_name}! Great to hear from you again. How can I help you today?"
        except Exception as e:
            logger.warning("assistant-request: caller lookup failed for tenant %s: %s", tenant_id, e)

    # Assemble system prompt — always include _CALLER_LOOKUP_NOTE so returning-caller
    # and rescheduling instructions are present even when the static Vapi config is stale.
    system_prompt = base_prompt + date_note + caller_context
    if tenant.get("google_refresh_token"):
        system_prompt += _CALENDAR_NOTE
    system_prompt += _CALLER_LOOKUP_NOTE

    # Include tools in the override so they are never lost if Vapi replaces model wholesale
    has_calendar = bool(tenant.get("google_refresh_token"))
    tools = build_calendar_tools(tenant_id) if has_calendar else [build_caller_lookup_tool(tenant_id)]

    logger.info(
        "assistant-request: tenant %s caller %s → %s (phone_found=%s)",
        tenant_id, caller_phone or "unknown", "returning" if caller_context else "new",
        bool(caller_phone),
    )

    overrides: dict = {
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.7,
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": tools,
        },
    }
    if personalized_greeting:
        overrides["firstMessage"] = personalized_greeting

    return {
        "assistantId": assistant_id,
        "assistantOverrides": overrides,
    }


@router.post("/vapi-call-ended")
async def vapi_call_ended(payload: dict):
    msg = payload.get("message", payload)
    event_type = msg.get("type", "")
    logger.info("VAPI EVENT: type=%s keys=%s", event_type, list(msg.keys()))

    # assistant-request must be handled synchronously — Vapi is waiting for the response
    # to know which assistant to connect to this call.
    if event_type == "assistant-request":
        return await _handle_assistant_request(msg)

    if event_type and event_type != "end-of-call-report":
        logger.debug("Ignoring Vapi event type: %s", event_type)
        return {"status": "ignored", "type": event_type}

    # end-of-call-report: store durably and ack immediately.
    # The background processor handles the slow work (GPT-4o, lead update, WhatsApp).
    call_id: str = (msg.get("call") or {}).get("id") or msg.get("call_id") or ""
    try:
        enqueued = await db.enqueue_webhook_event("end-of-call-report", call_id or None, payload)
        if enqueued:
            logger.info("Enqueued end-of-call-report for call %s", call_id)
        else:
            logger.info("Duplicate end-of-call-report ignored for call %s", call_id)
    except Exception as e:
        logger.error("Failed to enqueue webhook event for call %s: %s", call_id, e)
        raise HTTPException(status_code=500, detail="Failed to store webhook event")

    return {"status": "queued"}


@router.get("/queue-status")
async def queue_status():
    """Diagnostic: show recent webhook_events rows to debug processing issues."""
    try:
        res = (
            db.get_client()
            .table("webhook_events")
            .select("id, event_type, call_id, status, attempts, last_error, created_at, next_retry_at")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        return {"events": res.data or [], "count": len(res.data or [])}
    except Exception as e:
        return {"error": str(e)}


@router.post("/sync-knowledge")
async def sync_knowledge(body: dict):
    tenant_id: str = body.get("tenant_id", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    website_url: str = tenant.get("website_url", "")
    namespace: str = tenant.get("pinecone_namespace", "")

    if not website_url:
        raise HTTPException(status_code=400, detail="Tenant has no website_url configured")
    if not namespace:
        raise HTTPException(status_code=400, detail="Tenant has no pinecone_namespace configured")

    from services.security import validate_public_url
    validate_public_url(website_url)

    try:
        result = await knowledge.refresh_tenant_knowledge(tenant_id, website_url, namespace)
    except Exception as e:
        logger.error("Knowledge refresh failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Knowledge refresh failed")

    try:
        await db.update_tenant(tenant_id, {"last_crawl_at": result["refreshed_at"].isoformat()})
    except Exception as e:
        logger.error("Failed to update last_crawl_at for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update tenant crawl timestamp")

    try:
        await db.upsert_kb_website_entry(tenant_id, website_url)
    except Exception as e:
        logger.warning("Failed to track website KB entry for tenant %s (non-fatal): %s", tenant_id, e)

    # Refresh tenant record so reprompt sees the updated last_crawl_at
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        from services.provisioning import rebuild_and_push_system_prompt
        await rebuild_and_push_system_prompt(tenant)
        logger.info("System prompt rebuilt after knowledge sync for tenant %s", tenant_id)
    except Exception as e:
        logger.warning("System prompt rebuild after sync failed for tenant %s (non-fatal): %s", tenant_id, e)

    return {"status": "synced", "vectors_stored": result["vectors_stored"]}
