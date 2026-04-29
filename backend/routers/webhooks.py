import os
import json
import logging
import httpx
from datetime import datetime
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI

from db import supabase as db
from services import knowledge

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


def _format_whatsapp_message(business_name: str, analysis: dict) -> str:
    caller_name = analysis.get("caller_name", "Unknown")
    key_details: dict = analysis.get("key_details") or {}
    urgency = analysis.get("urgency", "unknown")
    summary = analysis.get("summary", "")
    next_step = analysis.get("suggested_next_step", "")

    detail_lines = "\n".join(
        f"• *{k.replace('_', ' ').title()}:* {v}"
        for k, v in key_details.items()
    )

    return (
        f"📞 *New Call — {business_name}*\n\n"
        f"👤 *{caller_name}*\n"
        f"{detail_lines}\n\n"
        f"⚡ Urgency: *{urgency}*\n"
        f"📝 {summary}\n\n"
        f"➡️ {next_step}"
    )


@router.post("/vapi-call-ended")
async def vapi_call_ended(payload: dict):
    # Step 1 — Extract call fields
    try:
        call = payload.get("call", {})
        call_id: str = call.get("id") or payload.get("call_id", "")
        transcript: str = call.get("transcript") or payload.get("transcript", "")
        caller_number: str = (call.get("customer") or {}).get("number", "")
        called_number: str = call.get("phoneNumberId") or payload.get("phoneNumberId", "")
        started_at: str | None = call.get("startedAt")
        ended_at: str | None = call.get("endedAt")
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
        duration = _parse_duration(started_at, ended_at)
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
        # Only overwrite name if GPT extracted one and the lead doesn't already have one
        if caller_name and not (existing_lead and existing_lead.get("name")):
            lead_update["name"] = caller_name
        await db.update_lead(tenant_id, lead_id, lead_update)
        logger.info("Updated lead %s after call %s", lead_id, call_id)
    except Exception as e:
        logger.error("Failed to update lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to update lead")

    # Step 7 — Format WhatsApp message
    try:
        message = _format_whatsapp_message(business_name, analysis)
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

    # Step 9 — Return
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
