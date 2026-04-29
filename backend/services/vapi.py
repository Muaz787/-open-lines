import os
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
APP_BACKEND_URL = os.getenv("APP_BACKEND_URL")
VAPI_BASE_URL = "https://api.vapi.ai"


def _headers() -> dict:
    if not VAPI_API_KEY:
        raise RuntimeError("VAPI_API_KEY must be set")
    return {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }


async def create_assistant(config: dict) -> str:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{VAPI_BASE_URL}/assistant",
                headers=_headers(),
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


async def update_assistant(assistant_id: str, config: dict) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.patch(
                f"{VAPI_BASE_URL}/assistant/{assistant_id}",
                headers=_headers(),
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
    return {
        "name": tenant["agent_name"],
        "firstMessage": tenant["greeting_template"],
        "endCallMessage": "Thank you for calling. Have a great day.",
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
        },
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
            ],
        },
        "voice": {
            "provider": "openai",
            "voiceId": "shimmer",
        },
        "serverUrl": f"{APP_BACKEND_URL}/webhooks/vapi-call-ended",
    }


async def import_twilio_number(
    phone_number: str,
    twilio_account_sid: str,
    twilio_auth_token: str,
    assistant_id: str,
    label: str = "",
) -> str:
    """Import a Twilio number into Vapi and assign it to an assistant.
    Returns the Vapi phone number ID."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{VAPI_BASE_URL}/phone-number",
                headers=_headers(),
                json={
                    "provider": "twilio",
                    "number": phone_number,
                    "twilioAccountSid": twilio_account_sid,
                    "twilioAuthToken": twilio_auth_token,
                    "assistantId": assistant_id,
                    "name": label or phone_number,
                },
                timeout=30.0,
            )
            res.raise_for_status()
            vapi_phone_id = res.json()["id"]
            logger.info(
                "Imported Twilio number %s into Vapi as %s, assigned to assistant %s",
                phone_number, vapi_phone_id, assistant_id,
            )
            return vapi_phone_id
    except httpx.HTTPStatusError as e:
        logger.error(
            "Failed to import Twilio number %s into Vapi: %s %s",
            phone_number, e.response.status_code, e.response.text,
        )
        raise
    except httpx.RequestError as e:
        logger.error("Network error importing Twilio number %s: %s", phone_number, e)
        raise


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
