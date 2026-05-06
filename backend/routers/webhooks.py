import os
import json
import logging
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI

from db import supabase as db
from services import knowledge, telephony, vapi as vapi_svc
from routers.calendar import _CALENDAR_NOTE

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")

_openai: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai


def _parse_duration(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds()))
    except Exception:
        return None


def _format_whatsapp_message(business_name: str, analysis: dict, caller_number: str = "") -> str:
    caller_name = analysis.get("caller_name", "Unknown")
    key_details: dict = analysis.get("key_details") or {}
    urgency = analysis.get("urgency", "unknown")
    summary = analysis.get("summary", "")
    next_step = analysis.get("suggested_next_step", "")

    detail_lines = "\n".join(
        f"• *{k.replace('_', ' ').title()}:* {v}"
        for k, v in key_details.items()
    )

    phone_line = f"📱 *Phone:* {caller_number}\n" if caller_number else ""

    return (
        f"📞 *New Call — {business_name}*\n\n"
        f"👤 *{caller_name}*\n"
        f"{phone_line}"
        f"{detail_lines}\n\n"
        f"⚡ Urgency: *{urgency}*\n"
        f"📝 {summary}\n\n"
        f"➡️ {next_step}"
    )


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

    print(f"ASSISTANT-REQUEST: called_number={called_number!r} caller_phone={caller_phone!r} payload_keys={list(msg.keys())}", flush=True)
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
            "assistant-request: tenant %s missing last_system_prompt — returning assistantId only",
            tenant_id,
        )
        return {"assistantId": assistant_id}

    # Today's date in tenant timezone
    tz_str: str = tenant.get("calendar_timezone") or "America/Toronto"
    today = datetime.now(ZoneInfo(tz_str))
    date_note = (
        f"\n\nTODAY'S DATE: {today.strftime('%A, %B %d, %Y')} ({today.strftime('%Y-%m-%d')}). "
        "Resolve all relative dates (today, tomorrow, next Monday, etc.) against this date "
        "before passing to any tool."
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
                caller_context = (
                    "\n\nCALLER CONTEXT (this caller has called before — use this immediately in your greeting):\n"
                    + "\n".join(lines)
                )
                greeting_name = name or "there"
                personalized_greeting = f"Hey {greeting_name}! Great to hear from you again. How can I help you today?"
        except Exception as e:
            logger.warning("assistant-request: caller lookup failed for tenant %s: %s", tenant_id, e)

    # Assemble system prompt
    system_prompt = base_prompt + date_note + caller_context
    if tenant.get("google_refresh_token"):
        system_prompt += _CALENDAR_NOTE

    # Tools
    try:
        tools = (
            vapi_svc.build_calendar_tools(tenant_id)
            if tenant.get("google_refresh_token")
            else [vapi_svc.build_caller_lookup_tool(tenant_id)]
        )
    except Exception as e:
        logger.error("assistant-request: failed to build tools for tenant %s: %s", tenant_id, e)
        return {"assistantId": assistant_id}

    logger.info(
        "assistant-request: tenant %s caller %s → %s",
        tenant_id, caller_phone or "unknown", "returning" if caller_context else "new",
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


@router.post("/vapi-debug")
async def vapi_debug(payload: dict):
    """Temporary: echo back the full Vapi payload so we can inspect it."""
    logger.info("VAPI DEBUG PAYLOAD: %s", json.dumps(payload, default=str))
    return {"received": payload}


@router.post("/vapi-call-ended")
async def vapi_call_ended(payload: dict):
    msg = payload.get("message", payload)
    event_type = msg.get("type", "")
    logger.info("VAPI EVENT: type=%s keys=%s", event_type, list(msg.keys()))

    if event_type == "assistant-request":
        result = await _handle_assistant_request(msg)
        print(f"ASSISTANT-REQUEST RESPONSE KEYS: {list(result.keys())} assistantId={result.get('assistantId')} error={result.get('error')}", flush=True)
        return result

    if event_type and event_type != "end-of-call-report":
        logger.debug("Ignoring Vapi event type: %s", event_type)
        return {"status": "ignored", "type": event_type}

    logger.info("Processing end-of-call-report")
    try:
        call = msg.get("call", {})
        call_id: str = call.get("id") or msg.get("call_id", "")
        transcript: str = call.get("transcript") or msg.get("transcript", "")
        caller_number: str = (call.get("customer") or {}).get("number", "")
        # phoneNumber.number holds the actual E.164 number; phoneNumberId is the Vapi ID
        phone_obj: dict = msg.get("phoneNumber") or call.get("phoneNumber") or {}
        called_number: str = (
            phone_obj.get("number")
            or phone_obj.get("twilioPhoneNumber")
            or call.get("phoneNumberId", "")
        )
        started_at: str | None = call.get("startedAt")
        ended_at: str | None = call.get("endedAt")
        vapi_duration: int | None = call.get("duration") or call.get("durationSeconds")
    except Exception as e:
        logger.error("Failed to extract call fields from payload: %s", e)
        raise HTTPException(status_code=400, detail="Malformed Vapi payload")

    if not called_number:
        raise HTTPException(status_code=400, detail="Missing phoneNumberId in payload")

    # Step 2 — Look up tenant by called number
    try:
        tenant = await db.get_tenant_by_phone(called_number)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", called_number, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found for this number")

    tenant_id: str = tenant["id"]
    business_name: str = tenant["business_name"]

    # Step 3 — Find or create lead
    try:
        existing_lead = await db.get_lead_by_phone(tenant_id, caller_number)
        if existing_lead:
            lead_id: str = existing_lead["id"]
            logger.info("Found existing lead %s for caller %s", lead_id, caller_number)
        else:
            new_lead = await db.insert_lead(tenant_id, {"phone": caller_number, "status": "new"})
            lead_id = new_lead["id"]
            existing_lead = None
            logger.info("Created new lead %s for caller %s", lead_id, caller_number)
    except Exception as e:
        logger.error("Lead lookup/create failed for tenant %s caller %s: %s", tenant_id, caller_number, e)
        raise HTTPException(status_code=500, detail="Lead lookup failed")

    # Step 4 — Summarise with GPT-4o
    try:
        qualification_fields = tenant.get("qualification_fields") or {}
        user_prompt = (
            f"Transcript: {transcript}\n\n"
            f"Qualification fields: {json.dumps(qualification_fields)}\n\n"
            "Extract: caller_name, key_details (dict matching qualification_fields), "
            "urgency (hot/warm/cold), summary (2 sentences max), suggested_next_step. "
            "Return JSON only."
        )
        response = await _get_openai().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You extract structured data from call transcripts."},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        analysis: dict = json.loads(response.choices[0].message.content)
        logger.info("GPT-4o analysis complete for call %s", call_id)
    except Exception as e:
        logger.error("GPT-4o analysis failed for call %s: %s", call_id, e)
        raise HTTPException(status_code=500, detail="Call analysis failed")

    # Step 5 — Save call record
    try:
        call_data: dict = {
            "vapi_call_id": call_id,
            "transcript": transcript,
        }
        duration = vapi_duration or _parse_duration(started_at, ended_at)
        if duration is not None:
            call_data["duration_secs"] = duration
        await db.insert_call(tenant_id, lead_id, call_data)
        logger.info("Saved call record for call %s (duration=%s s)", call_id, duration)
    except Exception as e:
        logger.error("Failed to save call record %s: %s", call_id, e)
        raise HTTPException(status_code=500, detail="Failed to save call record")

    # Step 6 — Update lead with summary and metadata
    try:
        caller_name = analysis.get("caller_name")
        lead_update: dict = {
            "summary": analysis.get("summary", ""),
            "urgency": analysis.get("urgency", ""),
            "status": "contacted",
            "metadata": {
                "key_details": analysis.get("key_details") or {},
                "suggested_next_step": analysis.get("suggested_next_step", ""),
                "last_call_id": call_id,
            },
        }
        if caller_name:
            lead_update["name"] = caller_name
        await db.update_lead(tenant_id, lead_id, lead_update)
        logger.info("Updated lead %s after call %s", lead_id, call_id)
    except Exception as e:
        logger.error("Failed to update lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to update lead")

    # Step 7 — Format WhatsApp message
    try:
        message = _format_whatsapp_message(business_name, analysis, caller_number)
    except Exception as e:
        logger.error("Failed to format WhatsApp message for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to format notification")

    # Step 8 — POST to Make webhook (non-fatal on failure)
    if MAKE_WEBHOOK_URL and tenant.get("whatsapp_number"):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    MAKE_WEBHOOK_URL,
                    json={"to": tenant["whatsapp_number"], "message": message},
                    timeout=10.0,
                )
                resp.raise_for_status()
            logger.info("WhatsApp notification sent for tenant %s call %s", tenant_id, call_id)
        except Exception as e:
            logger.error("WhatsApp notification failed for tenant %s: %s", tenant_id, e)
    else:
        logger.info(
            "Skipping WhatsApp notification (MAKE_WEBHOOK_URL=%s, whatsapp_number=%s)",
            bool(MAKE_WEBHOOK_URL),
            bool(tenant.get("whatsapp_number")),
        )

    # Step 9 — Send SMS confirmation if an appointment was booked (non-fatal)
    if caller_number:
        try:
            appointment = await db.get_appointment_by_call_id(call_id)
            if appointment:
                from zoneinfo import ZoneInfo
                tz_str = tenant.get("calendar_timezone") or "America/Toronto"
                appt_dt_raw = appointment.get("appointment_datetime", "")
                service = appointment.get("service", "appointment")
                caller_name_for_sms = analysis.get("caller_name") or ""

                try:
                    appt_dt = datetime.fromisoformat(appt_dt_raw)
                    if appt_dt.tzinfo is None:
                        appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
                    appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
                    h = appt_dt.hour % 12 or 12
                    ampm = "AM" if appt_dt.hour < 12 else "PM"
                    friendly_time = f"{appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
                except Exception:
                    friendly_time = appt_dt_raw

                greeting = f"Hi {caller_name_for_sms}! " if caller_name_for_sms else ""
                sms_body = (
                    f"{greeting}Your {service} at {business_name} is confirmed "
                    f"for {friendly_time}. See you then! — {business_name}"
                )

                subaccount_sid   = tenant.get("twilio_subaccount_sid", "")
                subaccount_token = tenant.get("twilio_auth_token", "")
                business_phone   = tenant.get("twilio_phone_number", "")

                if subaccount_sid and subaccount_token and business_phone:
                    await telephony.send_sms(
                        subaccount_sid=subaccount_sid,
                        subaccount_token=subaccount_token,
                        from_number=business_phone,
                        to_number=caller_number,
                        body=sms_body,
                    )
                    logger.info(
                        "Appointment SMS sent to %s for tenant %s (call %s)",
                        caller_number, tenant_id, call_id,
                    )
        except Exception as e:
            logger.error("Appointment SMS step failed for call %s: %s", call_id, e)

    # Step 10 — Return
    return {"status": "processed"}


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

    return {"status": "synced", "vectors_stored": result["vectors_stored"]}
