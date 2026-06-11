"""
Durable end-of-call-report processor.

The webhook router enqueues raw Vapi payloads immediately and acks Vapi.
This module processes them asynchronously with exponential-backoff retries
so a mid-deploy restart or a slow GPT-4o call never loses a call event.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI
from db import supabase as db
from services import telephony

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_ATTEMPTS = 3
# Retry delays: 30s, 60s, 120s
_RETRY_DELAYS = [30, 60, 120]
_POLL_INTERVAL = 5  # seconds between queue polls

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


async def process_end_of_call(payload: dict) -> None:
    """Process a single end-of-call-report payload. Raises on any fatal error."""
    msg = payload.get("message", payload)

    call = msg.get("call", {})
    call_id: str = call.get("id") or msg.get("call_id", "")
    # Transcript may be at call.transcript, msg.transcript, or msg.artifact.transcript (newer Vapi)
    transcript: str = (
        call.get("transcript")
        or msg.get("transcript")
        or (msg.get("artifact") or {}).get("transcript")
        or ""
    )
    caller_number: str = (
        (call.get("customer") or {}).get("number", "")
        or (msg.get("customer") or {}).get("number", "")
        or (msg.get("customer") or {}).get("phoneNumber", "")
    )
    phone_obj: dict = msg.get("phoneNumber") or call.get("phoneNumber") or {}
    called_number: str = (
        phone_obj.get("number")
        or phone_obj.get("twilioPhoneNumber")
        or call.get("phoneNumberId", "")
    )
    started_at: str | None = call.get("startedAt") or msg.get("startedAt")
    ended_at: str | None = call.get("endedAt") or msg.get("endedAt")
    vapi_duration = (
        call.get("durationSeconds")
        or call.get("duration")
        or msg.get("durationSeconds")
        or msg.get("duration")
    )

    if not called_number:
        raise ValueError("Missing called_number in payload — cannot route to tenant")

    tenant = await db.get_tenant_by_phone(called_number)
    if not tenant:
        raise ValueError(f"No tenant found for called number {called_number}")

    tenant_id: str = tenant["id"]
    business_name: str = tenant["business_name"]

    # Find or create lead
    existing_lead = await db.get_lead_by_phone(tenant_id, caller_number)
    if existing_lead:
        lead_id: str = existing_lead["id"]
    else:
        new_lead = await db.insert_lead(tenant_id, {"phone": caller_number, "status": "new"})
        lead_id = new_lead["id"]
        existing_lead = None

    # Save call record — wrapped so a schema/DB error here never blocks the lead update.
    call_data: dict = {"vapi_call_id": call_id, "transcript": transcript}
    duration = vapi_duration or _parse_duration(started_at, ended_at)
    if duration is not None:
        # Cast to int — Vapi may return float (e.g. 60.5) which would fail the int column
        call_data["duration_secs"] = int(duration)
    try:
        await db.insert_call(tenant_id, lead_id, call_data)
    except Exception as e:
        logger.error(
            "Failed to save call record for call %s tenant %s (lead update will still run): %s",
            call_id, tenant_id, e,
        )

    # GPT-4o analysis
    analysis: dict = {}
    if transcript and len(transcript.strip()) > 20:
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
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You extract structured data from call transcripts."},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            analysis = json.loads(response.choices[0].message.content)
            logger.info("GPT-4o analysis complete for call %s", call_id)
        except Exception as e:
            logger.warning("GPT-4o analysis failed for call %s (continuing): %s", call_id, e)

    # Update lead
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
    caller_name = analysis.get("caller_name")
    if caller_name:
        lead_update["name"] = caller_name
    await db.update_lead(tenant_id, lead_id, lead_update)

    # WhatsApp notification (non-fatal)
    whatsapp_number = tenant.get("whatsapp_number", "")
    if whatsapp_number:
        try:
            message = _format_whatsapp_message(business_name, analysis, caller_number)
            await telephony.send_whatsapp(to_number=whatsapp_number, body=message)
            logger.info("WhatsApp notification sent for tenant %s call %s", tenant_id, call_id)
        except Exception as e:
            logger.error("WhatsApp notification failed for tenant %s: %s", tenant_id, e)

    # Email notification (non-fatal)
    notification_email = tenant.get("notification_email", "")
    if notification_email and tenant.get("email_notifications", False):
        try:
            from services.email import send_call_summary_email
            await send_call_summary_email(
                to=notification_email,
                business_name=business_name,
                analysis=analysis,
                caller_number=caller_number,
            )
        except Exception as e:
            logger.error("Email notification failed for tenant %s: %s", tenant_id, e)

    # Record minutes for metered overage billing — cast to int (Vapi sends floats)
    if duration is not None and duration > 0:
        try:
            from services.usage import record_call_minutes
            await record_call_minutes(tenant_id, int(duration))
        except Exception as e:
            logger.error("usage.record_call_minutes failed for tenant %s call %s: %s", tenant_id, call_id, e)

    logger.info("Processed end-of-call-report for call %s tenant %s", call_id, tenant_id)


async def _process_one(event: dict) -> None:
    event_id = event["id"]
    attempts = event["attempts"] + 1
    try:
        await process_end_of_call(event["payload"])
        await db.mark_webhook_done(event_id)
    except Exception as e:
        error_msg = str(e)
        logger.error("Webhook event %s failed (attempt %d): %s", event_id, attempts, error_msg)
        if attempts >= MAX_ATTEMPTS:
            await db.mark_webhook_failed(event_id, attempts, error_msg)
            logger.error("Webhook event %s permanently failed after %d attempts", event_id, attempts)
        else:
            delay = _RETRY_DELAYS[attempts - 1] if attempts - 1 < len(_RETRY_DELAYS) else 120
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            await db.mark_webhook_retry(event_id, attempts, error_msg, retry_at)
            logger.info("Webhook event %s scheduled for retry in %ds", event_id, delay)


async def _processor_loop() -> None:
    logger.info("Webhook processor loop started")
    while True:
        try:
            events = await db.claim_pending_webhook_events(limit=10)
            for event in events:
                await _process_one(event)
        except Exception as e:
            logger.error("Webhook processor loop error: %s", e)
        await asyncio.sleep(_POLL_INTERVAL)


def start_background_processor() -> None:
    asyncio.create_task(_processor_loop())
