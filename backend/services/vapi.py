import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
_raw_backend = os.getenv("APP_BACKEND_URL", "https://backend-production-71174.up.railway.app").strip()
APP_BACKEND_URL = _raw_backend if _raw_backend.startswith("http") else f"https://{_raw_backend}"
VAPI_BASE_URL = "https://api.vapi.ai"


def _headers(api_key: str | None = None) -> dict:
    """Return Authorization headers. Uses tenant sub-org key when provided,
    otherwise falls back to the parent org VAPI_API_KEY."""
    key = api_key or VAPI_API_KEY
    if not key:
        raise RuntimeError("VAPI_API_KEY must be set")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def get_tenant_vapi_key(tenant: dict) -> str | None:
    """Return the decrypted sub-org API key for a tenant, or None to use the
    parent VAPI_API_KEY. Call sites should pass the result into api_key=."""
    encrypted = (tenant or {}).get("vapi_suborg_api_key")
    if not encrypted:
        return None  # caller falls back to parent key
    try:
        from services.security import decrypt
        return decrypt(encrypted)
    except Exception as e:
        logger.error("Failed to decrypt sub-org API key for tenant %s: %s",
                     (tenant or {}).get("id", "?"), e)
        return None  # safe fallback — still works, just uses parent pool


async def create_suborg(business_name: str) -> dict:
    """Create a Vapi sub-organization under the parent org.

    Returns {"id": str, "api_key": str} on success.
    Requires VAPI_API_KEY to be the parent org admin key.

    Vapi API: POST /org
    Note: if the exact field name for the returned key differs in your Vapi
    plan, adjust the key extraction below (apiKey / privateKey / key).
    """
    if not VAPI_API_KEY:
        raise RuntimeError("VAPI_API_KEY must be set")
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{VAPI_BASE_URL}/org",
                headers=_headers(),
                json={"name": f"{business_name} — OpenLines"},
                timeout=30.0,
            )
            res.raise_for_status()
            data = res.json()
            suborg_id = data.get("id", "")
            # Vapi may return the key as "apiKey", "privateKey", or "key"
            suborg_key = data.get("apiKey") or data.get("privateKey") or data.get("key") or ""
            if not suborg_id or not suborg_key:
                raise RuntimeError(
                    f"Unexpected sub-org response shape (missing id or key): {data}"
                )
            logger.info("Created Vapi sub-org %s for '%s'", suborg_id, business_name)
            return {"id": suborg_id, "api_key": suborg_key}
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to create Vapi sub-org for '%s': %s %s",
            business_name, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error creating Vapi sub-org for '%s': %s", business_name, e)
        raise


async def create_assistant(config: dict, api_key: str | None = None) -> str:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{VAPI_BASE_URL}/assistant",
                headers=_headers(api_key),
                json=config,
                timeout=30.0,
            )
            res.raise_for_status()
            assistant_id = res.json()["id"]
            logger.info("Created Vapi assistant %s", assistant_id)
            return assistant_id
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to create Vapi assistant: %s %s",
            e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error creating Vapi assistant: %s", e)
        raise


async def update_assistant(assistant_id: str, config: dict, api_key: str | None = None) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.patch(
                f"{VAPI_BASE_URL}/assistant/{assistant_id}",
                headers=_headers(api_key),
                json=config,
                timeout=30.0,
            )
            res.raise_for_status()
            logger.info("Updated Vapi assistant %s", assistant_id)
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to update Vapi assistant %s: %s %s",
            assistant_id, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error updating Vapi assistant %s: %s", assistant_id, e)
        raise


def build_assistant_config(tenant: dict, system_prompt: str) -> dict:
    if not APP_BACKEND_URL:
        raise RuntimeError("APP_BACKEND_URL must be set")
    tenant_id = tenant.get("id")
    tools = [build_caller_lookup_tool(tenant_id)] if tenant_id else []
    return {
        "name": tenant["agent_name"],
        "firstMessage": tenant["greeting_template"],
        "endCallMessage": "",
        "backgroundSound": "off",
        "backchannelingEnabled": True,
        "responseDelaySeconds": 0,
        "numWordsToInterruptAssistant": 2,
        "silenceTimeoutSeconds": 10,
        "endCallFunctionEnabled": True,
        "endCallPhrases": [
            "goodbye",
            "bye bye",
            "bye for now",
        ],
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
            "smartFormat": True,
            "endpointing": 400,
        },
        "model": {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "temperature": 0.7,
            "tools": tools,
            "messages": [
                {"role": "system", "content": system_prompt + _CALLER_LOOKUP_NOTE},
            ],
        },
        "voice": {
            "provider": "openai",
            "voiceId": "nova",
            "speed": 1.0,
            "fillerInjectionEnabled": True,
        },
        "serverUrl": f"{APP_BACKEND_URL}/webhooks/vapi-call-ended",
    }


async def import_twilio_number(
    phone_number: str,
    twilio_account_sid: str,
    twilio_auth_token: str,
    assistant_id: str | None = None,
    label: str = "",
    server_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Import a Twilio number into Vapi. Use server_url for smart routing (assistant-request).
    Returns the Vapi phone number ID."""
    body: dict = {
        "provider": "twilio",
        "number": phone_number,
        "twilioAccountSid": twilio_account_sid,
        "twilioAuthToken": twilio_auth_token,
        "name": label or phone_number,
    }
    if assistant_id:
        body["assistantId"] = assistant_id
    if server_url:
        body["serverUrl"] = server_url
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{VAPI_BASE_URL}/phone-number",
                headers=_headers(api_key),
                json=body,
                timeout=30.0,
            )
            res.raise_for_status()
            vapi_phone_id = res.json()["id"]
            logger.info("Imported Twilio number %s into Vapi as %s", phone_number, vapi_phone_id)
            return vapi_phone_id
    except httpx.HTTPStatusError as e:
        body_text = e.response.text
        logger.error(
            "Failed to import Twilio number %s into Vapi: %s %s",
            phone_number, e.response.status_code, body_text,
        )
        raise RuntimeError(
            f"Vapi /phone-number {e.response.status_code}: {body_text}"
        ) from e
    except httpx.RequestError as e:
        logger.error("Network error importing Twilio number %s: %s", phone_number, e)
        raise


async def list_phone_numbers(api_key: str | None = None) -> list:
    """Fetch all phone numbers registered in Vapi."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{VAPI_BASE_URL}/phone-number",
                headers=_headers(api_key),
                timeout=30.0,
            )
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        logger.error("Failed to list Vapi phone numbers: %s %s", e.response.status_code, e.response.text)
        raise
    except httpx.RequestError as e:
        logger.error("Network error listing Vapi phone numbers: %s", e)
        raise


async def update_phone_number(phone_id: str, data: dict, api_key: str | None = None) -> bool:
    """PATCH a Vapi phone number configuration."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.patch(
                f"{VAPI_BASE_URL}/phone-number/{phone_id}",
                headers=_headers(api_key),
                json=data,
                timeout=30.0,
            )
            res.raise_for_status()
            logger.info("Updated Vapi phone number %s", phone_id)
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to update Vapi phone number %s: %s %s",
            phone_id, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error updating Vapi phone number %s: %s", phone_id, e)
        raise


async def get_assistant(assistant_id: str, api_key: str | None = None) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{VAPI_BASE_URL}/assistant/{assistant_id}",
                headers=_headers(api_key),
                timeout=30.0,
            )
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to fetch Vapi assistant %s: %s %s",
            assistant_id, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error fetching Vapi assistant %s: %s", assistant_id, e)
        raise


_CALLER_LOOKUP_NOTE = """

CALLER RECOGNITION
- If this prompt already contains a CALLER CONTEXT section: this is a RETURNING caller.
  • Greet them warmly by name in your very first sentence.
  • Reference their history and any upcoming appointment.
  • SKIP ALL onboarding questions entirely — do NOT ask for their name, how to spell it, whether they are new or existing, their phone number, or any other information you already have. You already have it.
  • Do NOT call caller_lookup.
- If there is no CALLER CONTEXT section: the caller is new.
  • Ask for their name naturally in your first follow-up.
  • Do NOT call caller_lookup.
Never say "I'm looking up your records" or anything that reveals a system lookup.

RESCHEDULING RULES
- If a caller wants to change or reschedule an existing appointment, ALWAYS call check_availability first to find open slots — NEVER decide availability yourself based on their existing booking.
- When calling check_availability for a reschedule, you MUST pass caller_phone (their phone number from the CALLER CONTEXT section). This lets the backend remove their existing appointment from the busy list so their current slot shows as available for the new booking.
- The backend automatically removes their existing appointment from the busy list when caller_phone is provided, so the new slot will appear correctly available even if it overlaps with their current booking window.
- Once you have confirmed the new time with the caller, call book_appointment. The backend will automatically cancel the old appointment and create the new one.
- Never tell a caller a specific time is unavailable without first calling check_availability."""


def build_caller_lookup_tool(tenant_id: str) -> dict:
    if not APP_BACKEND_URL:
        raise RuntimeError("APP_BACKEND_URL must be set")
    return {
        "type": "function",
        "function": {
            "name": "caller_lookup",
            "description": (
                "Check whether this caller has called before and retrieve their name, "
                "call history summary, and any upcoming appointment. "
                "Call this as your FIRST action at the start of every call — before any other tools."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        "server": {
            "url": f"{APP_BACKEND_URL}/tools/{tenant_id}/caller-lookup",
            "timeoutSeconds": 10,
        },
    }


def build_calendar_tools(tenant_id: str) -> list[dict]:
    """Build all Vapi tool definitions: caller lookup + calendar booking."""
    if not APP_BACKEND_URL:
        raise RuntimeError("APP_BACKEND_URL must be set")
    base = f"{APP_BACKEND_URL}/tools/{tenant_id}"
    return [
        build_caller_lookup_tool(tenant_id),
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": (
                    "Check available appointment slots in the business calendar for a given date. "
                    "Use this when the caller wants to book OR reschedule an appointment."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": (
                                "The date to check in YYYY-MM-DD format. "
                                "You MUST convert the caller's words to a full calendar date before calling. "
                                "Month+day with no year (e.g. 'May 29th', 'June 3rd') → use the current year from TODAY'S DATE in your system prompt. NEVER use a past year. "
                                "Month names: January=01, February=02, March=03, April=04, May=05, June=06, "
                                "July=07, August=08, September=09, October=10, November=11, December=12. "
                                "If the caller says a range like 'Monday or Tuesday', pick the earlier date. "
                                "Never guess — derive the full YYYY-MM-DD from what the caller actually said."
                            ),
                        },
                        "period": {
                            "type": "string",
                            "enum": ["morning", "afternoon", "evening", "any"],
                            "description": (
                                "Caller's time-of-day preference. "
                                "ONLY use 'morning', 'afternoon', or 'evening' if the caller explicitly "
                                "says they prefer that part of the day. "
                                "Default to 'any' in ALL other cases — this shows the full business day."
                            ),
                        },
                        "caller_phone": {
                            "type": "string",
                            "description": (
                                "The caller's phone number (E.164 format, e.g. '+16471234567'). "
                                "REQUIRED when the caller is rescheduling — pass the phone from the CALLER CONTEXT "
                                "so the backend can remove their existing appointment from the busy list and show "
                                "their current slot as available. Omit for new bookings."
                            ),
                        },
                    },
                    "required": ["date"],
                },
            },
            "server": {"url": f"{base}/availability", "timeoutSeconds": 20},
        },
        {
            "type": "function",
            "function": {
                "name": "book_appointment",
                "description": (
                    "Book a confirmed appointment in the business calendar. "
                    "Call this ONLY after the caller has explicitly agreed to a specific date AND time. "
                    "Do not call this speculatively — wait for clear confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "caller_name": {
                            "type": "string",
                            "description": "Full name of the caller.",
                        },
                        "caller_phone": {
                            "type": "string",
                            "description": "Caller's phone number as provided by caller ID.",
                        },
                        "service": {
                            "type": "string",
                            "description": (
                                "The service or appointment type being booked "
                                "(e.g. 'Haircut', 'Dental check-up', 'Consultation', 'Service call')."
                            ),
                        },
                        "date": {
                            "type": "string",
                            "description": "Confirmed appointment date in YYYY-MM-DD format.",
                        },
                        "time": {
                            "type": "string",
                            "description": "Confirmed appointment time in HH:MM 24-hour format (e.g. '14:00' for 2 PM).",
                        },
                    },
                    "required": ["caller_name", "caller_phone", "service", "date", "time"],
                },
            },
            "server": {"url": f"{base}/book", "timeoutSeconds": 20},
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": (
                    "Cancel the caller's upcoming appointment. "
                    "Call this ONLY after the caller has explicitly confirmed they want to cancel. "
                    "Do not call this speculatively."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            "server": {"url": f"{base}/cancel", "timeoutSeconds": 15},
        },
    ]


async def get_call_details(call_id: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{VAPI_BASE_URL}/call/{call_id}",
                headers=_headers(),
                timeout=30.0,
            )
            res.raise_for_status()
            return res.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to fetch Vapi call %s: %s %s",
            call_id, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error fetching Vapi call %s: %s", call_id, e)
        raise
