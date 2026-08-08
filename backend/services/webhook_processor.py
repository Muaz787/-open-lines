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
from db import routing as rdb
from services import analytics, telephony, transfer as transfer_svc

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAX_ATTEMPTS = 3
# Retry delays: 30s, 60s, 120s
_RETRY_DELAYS = [30, 60, 120]
# Adaptive polling: poll fast while the queue has work, back off when idle so an
# empty queue isn't hitting Supabase every few seconds (cuts DB load + log noise).
_BATCH_LIMIT = 10
_POLL_INTERVAL_MIN = 5    # seconds — fast poll while there's work to drain
_POLL_INTERVAL_MAX = 20   # seconds — idle ceiling; worst-case pickup latency

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


def _wa_clean(s: str, maxlen: int) -> str:
    """WhatsApp template variables must be single-line and bounded."""
    return " ".join(str(s or "").split())[:maxlen] or "—"


def _whatsapp_summary_vars(business_name: str, analysis: dict, caller_number: str = "") -> dict:
    """Ordered variables for the approved call-summary WhatsApp Content Template.

    The template uses FIVE variables (WhatsApp won't accept two variables on one
    line, so caller name + number are combined into {{2}}):
        New call for {{1}}
        Caller: {{2}}
        Priority: {{3}}
        Summary: {{4}}
        Recommended next step: {{5}}
    """
    analysis = analysis or {}
    caller_name = analysis.get("caller_name") or "Unknown caller"
    number = caller_number or "no caller ID"
    return {
        "1": _wa_clean(business_name, 60),
        "2": _wa_clean(f"{caller_name} • {number}", 90),
        "3": _wa_clean((analysis.get("urgency") or "unknown").capitalize(), 20),
        "4": _wa_clean(analysis.get("summary"), 300),
        "5": _wa_clean(analysis.get("suggested_next_step"), 120),
    }


def _format_sms_summary(business_name: str, analysis: dict, caller_number: str = "") -> str:
    """Compact, plain-text call summary for SMS (no markdown, length-bounded)."""
    analysis = analysis or {}
    caller_name = analysis.get("caller_name") or "Unknown caller"
    urgency = analysis.get("urgency", "")
    summary = (analysis.get("summary") or "").strip()
    next_step = (analysis.get("suggested_next_step") or "").strip()

    lines = [f"New call — {business_name}", caller_name]
    if caller_number:
        lines.append(caller_number)
    if urgency:
        lines.append(f"Urgency: {urgency}")
    if summary:
        lines.append(summary[:300])
    if next_step:
        lines.append(f"Next: {next_step[:120]}")
    # Keep within a couple of SMS segments.
    return "\n".join(lines)[:600]


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
    ended_reason: str = call.get("endedReason") or msg.get("endedReason") or ""
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
    is_new_lead = existing_lead is None
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
    inserted_call: dict = {}
    try:
        inserted_call = await db.insert_call(tenant_id, lead_id, call_data)
    except Exception as e:
        logger.error(
            "Failed to save call record for call %s tenant %s (lead update will still run): %s",
            call_id, tenant_id, e,
        )

    # Transfer outcome — only when this call actually had a transfer attempt (created
    # by the transfer-destination webhook) or Vapi reports a forwarded call. Maps the
    # end-of-call reason to our outcome + inbox disposition. Best-effort; never blocks.
    try:
        attempt = await rdb.get_transfer_attempt(call_id)
        if attempt or ended_reason == "assistant-forwarded-call":
            outcome = transfer_svc.outcome_from_ended_reason(ended_reason)
            if outcome:
                # NOTE: we set ended_at (the AI-side hand-off time) but NOT
                # duration_secs. The real transfer duration is the post-hand-off
                # caller<->operator talk-time, which lives on the Twilio operator leg
                # and is STILL IN PROGRESS at this end-of-call event (Vapi has already
                # left the call). Reading it needs deferred Twilio-leg reconciliation —
                # a tracked follow-up. Do not fill duration_secs with (ended_at -
                # started_at); that is only the ~seconds-long hand-off window, not the
                # talk-time, and would misrepresent transfer COGS. See transfer.py.
                await rdb.record_transfer_attempt({
                    "tenant_id": tenant_id, "vapi_call_id": call_id, "attempt_index": 0,
                    "outcome": outcome, "ended_at": ended_at or None,
                })
                if inserted_call.get("id"):
                    await db.update_call(inserted_call["id"], {
                        "transferred": True,
                        "disposition": transfer_svc.disposition_for_outcome(outcome),
                    })
                logger.info("Recorded transfer outcome=%s for call %s tenant %s", outcome, call_id, tenant_id)
    except Exception as e:
        logger.warning("Transfer-outcome recording failed for call %s tenant %s: %s", call_id, tenant_id, e)

    # PRIVACY: no transcript, no caller phone number — ids and duration only
    _distinct = analytics.distinct_id_for(tenant, tenant_id)
    analytics.capture(_distinct, "call_completed", {
        "tenant_id": tenant_id,
        "call_id": call_id,
        "duration_seconds": int(duration) if duration else None,
    })

    # Combined per-call analysis: lead fields + AI Insights enrichment signals.
    analysis: dict = {}
    if transcript and len(transcript.strip()) > 20:
        try:
            from services import call_enrichment
            analysis = await call_enrichment.analyze_transcript(transcript, tenant)
            logger.info("Call analysis complete for call %s (intent=%s)", call_id, analysis.get("intent"))
            # Persist enrichment signals on the call row (non-fatal).
            if inserted_call.get("id"):
                try:
                    await db.update_call(inserted_call["id"], call_enrichment.call_enrichment(analysis))
                except Exception as e:
                    logger.warning("Call enrichment store failed for call %s (continuing): %s", call_id, e)
        except Exception as e:
            logger.warning("Call analysis failed for call %s (continuing): %s", call_id, e)

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

    if analysis:
        # PRIVACY: urgency level only — no summary text, name, or details
        analytics.capture(_distinct, "call_summary_generated", {
            "tenant_id": tenant_id,
            "call_id": call_id,
            "urgency": analysis.get("urgency", ""),
        })

    # Zapier REST Hook triggers (best-effort — never blocks call processing).
    # Unlike analytics, these payloads carry the tenant's own caller data, since
    # they flow to the tenant's own connected apps.
    try:
        from services import zapier
        _caller_name = (analysis.get("caller_name") if analysis else "") or ""
        _urgency = (analysis.get("urgency") if analysis else "") or ""
        await zapier.emit(tenant_id, "call_completed", {
            "call_id": call_id,
            "caller_name": _caller_name,
            "caller_phone": caller_number,
            "duration_secs": int(duration) if duration else None,
            "urgency": _urgency,
            "summary": analysis.get("summary", "") if analysis else "",
            "suggested_next_step": analysis.get("suggested_next_step", "") if analysis else "",
            "key_details": analysis.get("key_details", {}) if analysis else {},
            "transcript": transcript,
        })
        if is_new_lead:
            await zapier.emit(tenant_id, "new_lead", {
                "lead_id": lead_id, "name": _caller_name, "phone": caller_number, "status": "new",
            })
        if _urgency.lower() == "hot":
            await zapier.emit(tenant_id, "hot_lead", {
                "lead_id": lead_id, "name": _caller_name, "phone": caller_number, "urgency": _urgency,
                "summary": analysis.get("summary", "") if analysis else "",
                "key_details": analysis.get("key_details", {}) if analysis else {},
            })
    except Exception as e:
        logger.warning("Zapier emit failed for call %s tenant %s (non-fatal): %s", call_id, tenant_id, e)

    # HubSpot CRM sync (non-fatal — never blocks call processing)
    if tenant.get("hubspot_refresh_token"):
        try:
            from services.hubspot import sync_call_to_hubspot
            await sync_call_to_hubspot(
                tenant=tenant,
                caller_phone=caller_number,
                caller_name=analysis.get("caller_name") if analysis else None,
                analysis=analysis or {},
                call_id=call_id,
            )
            analytics.capture(_distinct, "hubspot_sync_completed", {"tenant_id": tenant_id})
        except Exception as e:
            logger.error("HubSpot sync failed for tenant %s call %s: %s", tenant_id, call_id, e)

    # Slack notification (non-fatal)
    if tenant.get("slack_webhook_url"):
        try:
            from services.slack import post_call_summary as slack_post
            await slack_post(
                webhook_url=tenant["slack_webhook_url"],
                business_name=business_name,
                analysis=analysis or {},
                caller_number=caller_number,
            )
            analytics.capture(_distinct, "owner_notification_sent", {
                "tenant_id": tenant_id, "channel": "slack",
            })
        except Exception as e:
            logger.error("Slack notification failed for tenant %s: %s", tenant_id, e)

    # ── Call-summary notifications — independent per-channel toggles ──
    notification_email = tenant.get("notification_email", "")
    # SMS + WhatsApp both go to the dedicated mobile (else the business phone).
    mobile_to = (tenant.get("sms_alert_number") or tenant.get("business_phone") or "").strip()

    # Email (non-fatal)
    if tenant.get("email_enabled", True) and notification_email:
        try:
            from services.email import send_call_summary_email
            await send_call_summary_email(
                to=notification_email,
                business_name=business_name,
                analysis=analysis,
                caller_number=caller_number,
                tenant_id=tenant.get("id", ""),
            )
            analytics.capture(_distinct, "owner_notification_sent", {
                "tenant_id": tenant_id, "channel": "email",
            })
        except Exception as e:
            logger.error("Email notification failed for tenant %s: %s", tenant_id, e)

    # SMS (non-fatal) — from the tenant's own Twilio line
    if tenant.get("sms_enabled", False) and mobile_to:
        try:
            sub_sid  = tenant.get("twilio_subaccount_sid", "")
            sub_tok  = tenant.get("twilio_auth_token", "")
            from_num = tenant.get("twilio_phone_number", "")
            if sub_sid and sub_tok and from_num:
                await telephony.send_sms(
                    subaccount_sid=sub_sid,
                    subaccount_token=sub_tok,
                    from_number=from_num,
                    to_number=mobile_to,
                    body=_format_sms_summary(business_name, analysis, caller_number),
                )
                analytics.capture(_distinct, "owner_notification_sent", {
                    "tenant_id": tenant_id, "channel": "sms",
                })
            else:
                logger.warning("SMS notification skipped for tenant %s: missing Twilio creds", tenant_id)
        except Exception as e:
            logger.error("SMS notification failed for tenant %s: %s", tenant_id, e)

    # WhatsApp (non-fatal) — PRODUCTION ONLY, via an approved Twilio Content
    # Template from the central OpenLines WhatsApp sender. Never freeform. Skips
    # silently if the sender/template env vars aren't configured.
    if tenant.get("whatsapp_enabled", False) and mobile_to:
        try:
            sent = await telephony.send_whatsapp_template(
                mobile_to,
                telephony.TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID,
                _whatsapp_summary_vars(business_name, analysis, caller_number),
            )
            if sent:
                analytics.capture(_distinct, "owner_notification_sent", {
                    "tenant_id": tenant_id, "channel": "whatsapp",
                })
        except Exception as e:
            logger.error("WhatsApp notification failed for tenant %s: %s", tenant_id, e)

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
    interval = _POLL_INTERVAL_MIN
    while True:
        try:
            events = await db.claim_pending_webhook_events(limit=_BATCH_LIMIT)
            for event in events:
                await _process_one(event)
        except Exception as e:
            logger.error("Webhook processor loop error: %s", e)
            events = None

        if events and len(events) >= _BATCH_LIMIT:
            # Full batch — more is likely queued; drain immediately without sleeping.
            interval = _POLL_INTERVAL_MIN
            continue
        if events:
            # Had work but drained it — stay responsive for the next event.
            interval = _POLL_INTERVAL_MIN
        else:
            # Idle (or a poll error) — back off up to the ceiling to cut load + noise.
            interval = min(interval * 2, _POLL_INTERVAL_MAX)
        await asyncio.sleep(interval)


def start_background_processor() -> None:
    asyncio.create_task(_processor_loop())
