import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Annotated
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Header

from db import supabase as db
from db import routing as rdb
from services.security import verify_tenant_owner, verify_vapi_server_secret
from services import analytics, knowledge, vapi as vapi_svc
from services import entitlements, transfer as transfer_svc, routing_destinations as rd
from services.vapi import _CALLER_LOOKUP_NOTE, build_caller_lookup_tool, build_calendar_tools, ensure_safety_preamble
from routers.calendar import _CALENDAR_NOTE

# Injected when NO calendar is connected. The industry/custom templates tell the
# AI to book directly and confirm to the caller; without a booking tool that
# would confirm a phantom appointment. This overrides that for un-connected
# tenants so the AI never claims to book.
_NO_BOOKING_NOTE = """

BOOKING IS NOT AVAILABLE ON THIS LINE YET (no calendar is connected).
- You do NOT have a booking tool. You CANNOT schedule, confirm, reschedule, or cancel a specific appointment time, and you must NEVER say an appointment is booked or confirmed.
- If the caller wants an appointment or a time change: capture their name, preferred day/time, and the reason, then say a member of the team will follow up shortly to confirm the time.
- Do not invent a confirmed time and do not imply a calendar invite will be sent."""

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# In-memory log of the last 30 raw Vapi events (any type) — cleared on redeploy
_recent_events: list[dict] = []

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Subscription gate: tenants can take live calls if they have an active subscription,
# OR are still within this many days of provisioning (so new tenants can test the AI
# before subscribing). Past the grace window without an active sub → calls are gated.
GRACE_PERIOD_DAYS = int(os.getenv("SUBSCRIPTION_GRACE_DAYS", "7"))
_ACTIVE_SUB_STATUSES = {"active", "trialing", "past_due", "canceling"}

def _require_admin(x_admin_key: str | None) -> None:
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def _calls_allowed(tenant: dict) -> bool:
    """True if the tenant may take live AI calls: an active subscription, OR an
    active free trial (within 7 days AND under the 30-minute trial cap)."""
    from services import trial
    return trial.trial_status(tenant)["line_active"]


def _gated_assistant_response(assistant_id: str) -> dict:
    """Vapi config that plays a short 'line not active' message and hangs up, instead
    of engaging the full receptionist. Capped at 30s so it never costs real call time."""
    msg = ("Thanks for calling. This phone line isn't active at the moment. "
           "Please contact the business directly. Goodbye.")
    return {
        "assistantId": assistant_id,
        "assistantOverrides": {
            "firstMessage": msg,
            "firstMessageMode": "assistant-speaks-first",
            "maxDurationSeconds": 30,
            "model": {
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "temperature": 0,
                "messages": [{"role": "system", "content": (
                    "This phone line is inactive. You have already told the caller to contact "
                    "the business directly. If they say anything, briefly repeat that the line "
                    "isn't active and to contact the business directly, then end the call. "
                    "Never collect information, answer questions, or book anything."
                )}],
            },
        },
    }


def _fmt_hour(h: int) -> str:
    """24h int → '9 AM' / '5 PM' / '12 PM'."""
    h = int(h) % 24
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12} {suffix}"


def _fmt_days(days: list[int]) -> str:
    s = sorted(set(d for d in days if 0 <= d <= 6))
    if not s:
        return "by appointment"
    if len(s) > 1 and s == list(range(s[0], s[-1] + 1)):
        return f"{_DAY_NAMES[s[0]]} through {_DAY_NAMES[s[-1]]}"
    names = [_DAY_NAMES[d] for d in s]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _build_schedule_note(tenant: dict) -> str:
    """Build the operating-schedule + booking-rules note injected into the prompt."""
    raw_days = tenant.get("business_days")
    if isinstance(raw_days, str):
        try:
            raw_days = json.loads(raw_days)
        except Exception:
            raw_days = None
    days = raw_days if isinstance(raw_days, list) and raw_days else [0, 1, 2, 3, 4]
    days = [int(d) for d in days if isinstance(d, (int, float, str)) and str(d).strip().lstrip("-").isdigit()]

    start = int(tenant.get("business_hours_start") or 9)
    end   = int(tenant.get("business_hours_end") or 17)

    lines = [
        "\n\nBUSINESS OPERATING SCHEDULE (enforce strictly)",
        f"- Open days: {_fmt_days(days)}.",
        f"- Hours: {_fmt_hour(start)} to {_fmt_hour(end)}.",
        "- NEVER offer or book appointments outside these days or hours. If a caller asks for a "
        "closed day or time, say you're closed then and offer the nearest open option.",
    ]

    bs, be = tenant.get("break_start"), tenant.get("break_end")
    if bs is not None and be is not None and int(be) > int(bs):
        lines.append(f"- Daily break (no appointments): {_fmt_hour(int(bs))} to {_fmt_hour(int(be))}.")

    instructions = (tenant.get("booking_instructions") or "").strip()
    if instructions:
        lines.append(f"\nADDITIONAL BOOKING INSTRUCTIONS FROM THE BUSINESS OWNER (follow these):\n{instructions}")

    return "\n".join(lines)


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

    # Trial/subscription gate: allow active subscribers and active free trials
    # (within 7 days AND under the 30-minute trial cap). Otherwise play a short
    # "line not active" message and hang up instead of engaging the receptionist.
    from services import trial as _trial
    _ts = _trial.trial_status(tenant)
    if not _ts["line_active"]:
        logger.info(
            "assistant-request: tenant %s GATED reason=%s (status=%s, created=%s, trial_min_used=%s) — playing inactive message",
            tenant_id, _trial.blocked_reason(tenant), tenant.get("subscription_status"),
            tenant.get("created_at"), tenant.get("minutes_used_this_period"),
        )
        return _gated_assistant_response(assistant_id)

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

    # Operating schedule note — gives the AI the business's days, hours, break,
    # and any free-text booking rules so it guides callers correctly.
    schedule_note = _build_schedule_note(tenant)

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

    # Booking is available via ANY connected provider — Google, Microsoft Outlook,
    # or Square Appointments. (Previously only Google was checked here, so Outlook /
    # Square-only tenants silently lost their booking tools + calendar note on the
    # per-call override.) Mirrors vapi.build_all_tools / provisioning._has_booking.
    has_calendar = bool(
        tenant.get("google_refresh_token")
        or tenant.get("microsoft_refresh_token")
        or tenant.get("square_appointments_enabled")
    )

    # Assemble system prompt — always include _CALLER_LOOKUP_NOTE so returning-caller
    # and rescheduling instructions are present even when the static Vapi config is stale.
    system_prompt = base_prompt + date_note + caller_context
    if has_calendar:
        system_prompt += _CALENDAR_NOTE + schedule_note
    else:
        # No calendar connected — stop the AI confirming appointments it can't book.
        system_prompt += _NO_BOOKING_NOTE
    system_prompt += _CALLER_LOOKUP_NOTE
    # Defense-in-depth: guarantee the non-overridable safety preamble is present
    # even if this tenant's stored prompt predates it. The receptionist voice/manner
    # guidance is applied on every call so ALL tenants (incl. pre-existing) get it.
    system_prompt = vapi_svc.ensure_receptionist_style(ensure_safety_preamble(system_prompt))

    # Include tools in the override so they are never lost if Vapi replaces model wholesale
    tools = build_calendar_tools(tenant_id) if has_calendar else [build_caller_lookup_tool(tenant_id)]
    tools += vapi_svc.build_routing_tools(tenant)   # dark unless routing-entitled

    logger.info(
        "assistant-request: tenant %s caller %s → %s (phone_found=%s)",
        tenant_id, caller_phone or "unknown", "returning" if caller_context else "new",
        bool(caller_phone),
    )

    # PRIVACY: caller phone number intentionally excluded — only caller type
    analytics.capture(
        analytics.distinct_id_for(tenant, tenant_id),
        "call_received",
        {
            "tenant_id": tenant_id,
            "caller_type": "returning" if caller_context else "new",
            "has_calendar": has_calendar,
        },
    )

    overrides: dict = {
        "model": {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "temperature": 0.8,
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": tools,
        },
        "transcriber": dict(vapi_svc.RECEPTIONIST_TRANSCRIBER),
        "startSpeakingPlan": vapi_svc.START_SPEAKING_PLAN,
        "stopSpeakingPlan": vapi_svc.STOP_SPEAKING_PLAN,
        "backchannelingEnabled": True,
        # Always inject the correct server config (URL + X-Vapi-Secret when set) so
        # end-of-call-report and all post-call events reach our backend authenticated,
        # regardless of what stale URL (old ngrok, localhost) may be stored on the
        # assistant. This also gives OLD assistants the secret at call time.
        **vapi_svc.server_block(f"{vapi_svc.APP_BACKEND_URL}/webhooks/vapi-call-ended"),
    }
    # Voice: non-canary tenants get the ElevenLabs override on every call (so even
    # pre-existing assistants get the upgraded, gender-matched voice). Canaried
    # Fish-Audio tenants get their voice from the ASSISTANT config instead — Vapi
    # ignores a custom-voice provider in per-call overrides — so we deliberately do
    # NOT set voice here for them (run /admin/patch-fish-voice to set it once).
    if not vapi_svc.is_fish_canary(tenant):
        overrides["voice"] = vapi_svc.build_voice_block(tenant)

    # Always open with the virtual-assistant + recording disclosure (PIPEDA
    # knowledge/consent), covering new, returning, and pre-existing tenants on every call.
    overrides["firstMessage"] = vapi_svc.ensure_call_disclosure(
        personalized_greeting or tenant.get("greeting_template", "")
    )

    # Give callers room to pause/think — 10s was hanging up real calls mid-conversation.
    # Set per-call so existing tenants get it on the next call without re-provisioning.
    overrides["silenceTimeoutSeconds"] = 25

    # Routing-entitled tenants: declare the transfer/outcome server messages so the
    # dynamic transfer webhook + end-of-call outcome recording fire. Belt-and-braces
    # alongside the assistant-level serverMessages (per-call overrides for this field
    # may be ignored by Vapi — the assistant patch is the authoritative path).
    if entitlements.has_feature(tenant, "routing"):
        overrides["serverMessages"] = vapi_svc.ROUTING_SERVER_MESSAGES

    # Public "try the AI" demo line — bound cost/abuse on that tenant only:
    # short max call length + quicker hang-up on silence. Set DEMO_TENANT_ID (and
    # optionally DEMO_MAX_CALL_SECONDS / DEMO_SILENCE_SECONDS) in Railway once the
    # demo tenant is provisioned. Real tenants are unaffected.
    demo_tid = os.getenv("DEMO_TENANT_ID", "").strip()
    if demo_tid and tenant_id == demo_tid:
        overrides["maxDurationSeconds"] = int(os.getenv("DEMO_MAX_CALL_SECONDS", "120"))
        overrides["silenceTimeoutSeconds"] = int(os.getenv("DEMO_SILENCE_SECONDS", "15"))

    return {
        "assistantId": assistant_id,
        "assistantOverrides": overrides,
    }


async def _handle_transfer_destination_request(msg: dict) -> dict:
    """Vapi asks our server for the transfer destination when the AI invokes
    transferCall with no number. We resolve it from the routing DECISION already
    recorded for this call (classify-and-route), so the AI never carries a number.

    Gated by ROUTING_TRANSFER_ENABLED (telephony master) + tenant entitlement. When
    declined, Vapi's fallbackPlan / the assistant continues — never a dropped call.
    Records the transfer attempt (started); the outcome is filled from the
    end-of-call report. Warm/bridged + sipVerb=dial only (metered-mode-only rule)."""
    decline = {"error": "transfer_unavailable"}
    phone_obj = msg.get("phoneNumber") or {}
    call = msg.get("call") or {}
    called_number = (phone_obj.get("number") or phone_obj.get("twilioPhoneNumber")
                     or (call.get("phoneNumber") or {}).get("number", ""))
    call_id = call.get("id", "")
    if not called_number:
        return decline
    try:
        tenant = await db.get_tenant_by_phone(called_number)
    except Exception:
        tenant = None
    if not tenant:
        return decline
    if not (entitlements.has_feature(tenant, "routing") and entitlements.transfer_execution_enabled()):
        return decline

    tenant_id = tenant["id"]
    decision = await rdb.get_latest_transfer_decision(tenant_id, call_id)
    if not decision or not decision.get("chosen_destination_id"):
        return decline
    dest = await rdb.get_destination(tenant_id, decision["chosen_destination_id"])
    if not dest or not dest.get("enabled", True) or not dest.get("e164_encrypted"):
        return decline
    try:
        number = rd.reveal(dest["e164_encrypted"])
    except Exception as e:
        logger.error("transfer-destination: decrypt failed for tenant %s: %s", tenant_id, e)
        return decline
    # loop guard (defence in depth; also enforced at destination creation)
    own = tenant.get("twilio_phone_number")
    try:
        if own and rd.is_same_number(number, rd.keyed_hash(own)):
            logger.warning("transfer-destination: refusing loop to own line (tenant %s)", tenant_id)
            return decline
    except Exception:
        pass

    try:
        await rdb.record_transfer_attempt({
            "tenant_id": tenant_id, "vapi_call_id": call_id, "destination_id": dest["id"],
            "mode": "warm", "attempt_index": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning("transfer-destination: could not record attempt for %s: %s", tenant_id, e)

    logger.info("transfer-destination: routing call %s to destination %s (tenant %s)",
                call_id, dest["id"], tenant_id)
    return {"destination": transfer_svc.build_destination(number)}


@router.post("/vapi-call-ended")
async def vapi_call_ended(
    payload: dict,
    x_vapi_secret: Annotated[str | None, Header()] = None,
):
    verify_vapi_server_secret(x_vapi_secret)
    from datetime import timezone
    msg = payload.get("message", payload)
    event_type = msg.get("type", "")
    logger.info("VAPI EVENT: type=%s keys=%s", event_type, list(msg.keys()))

    # Keep a rolling in-memory log for diagnostics
    _recent_events.append({
        "received_at": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "call_id": (msg.get("call") or {}).get("id", ""),
        "keys": list(msg.keys()),
    })
    if len(_recent_events) > 30:
        _recent_events.pop(0)

    # assistant-request must be handled synchronously — Vapi is waiting for the response
    # to know which assistant to connect to this call.
    if event_type == "assistant-request":
        return await _handle_assistant_request(msg)

    # Dynamic transfer destination — synchronous (Vapi waits for the destination).
    if event_type == "transfer-destination-request":
        return await _handle_transfer_destination_request(msg)

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
async def queue_status(x_admin_key: Annotated[str | None, Header()] = None):
    """Diagnostic: show queued webhook events + recent raw Vapi hits. Admin-only —
    exposes cross-tenant call IDs and error detail."""
    _require_admin(x_admin_key)
    try:
        res = (
            db.get_client()
            .table("webhook_events")
            .select("id, event_type, call_id, status, attempts, last_error, created_at, next_retry_at")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return {
            "queue": res.data or [],
            "queue_count": len(res.data or []),
            "recent_vapi_hits": list(reversed(_recent_events)),
        }
    except Exception as e:
        return {"error": str(e), "recent_vapi_hits": list(reversed(_recent_events))}


@router.post("/sync-knowledge")
async def sync_knowledge(
    body: dict,
    authorization: Annotated[str | None, Header()] = None,
):
    tenant_id: str = body.get("tenant_id", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    # Owner-only: re-scraping + re-embedding is billable work tied to a tenant.
    await verify_tenant_owner(tenant_id, authorization)

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.get("website_url"):
        raise HTTPException(status_code=400, detail="Tenant has no website_url configured")

    # Shared two-phase, clear-before-embed refresh (keeps old KB on failure,
    # never deletes uploaded documents, records crawl metadata).
    from services import recrawl
    try:
        result = await recrawl.recrawl_tenant(tenant, source="manual")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Knowledge refresh failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Knowledge refresh failed — your existing knowledge base is unchanged.")

    return {"status": "synced", "vectors_stored": result.get("vectors_stored", 0)}
