import os
import logging
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

load_dotenv()

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")


def _master_client() -> Client:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _sub_client(subaccount_sid: str, subaccount_token: str) -> Client:
    return Client(subaccount_sid, subaccount_token)


async def create_subaccount(business_name: str) -> dict:
    try:
        client = _master_client()
        account = client.api.accounts.create(
            friendly_name=f"OpenLines - {business_name}"
        )
        logger.info("Created Twilio sub-account %s for '%s'", account.sid, business_name)
        return {"sid": account.sid, "auth_token": account.auth_token}
    except TwilioRestException as e:
        logger.error("Failed to create sub-account for '%s': %s", business_name, e)
        raise


# Per-country search config.
# area_codes: try these first in order; fall through to national search if all miss.
# Empty list means go straight to national search.
_COUNTRY_CONFIG: dict[str, dict] = {
    "CA": {"twilio_code": "CA", "area_codes": ["416", "647", "905", "604", "403", "780", "613", "438"]},
    "US": {"twilio_code": "US", "area_codes": ["212", "310", "312", "415", "718", "617", "404", "206"]},
    "GB": {"twilio_code": "GB", "area_codes": []},
    "AU": {"twilio_code": "AU", "area_codes": []},
    "IE": {"twilio_code": "IE", "area_codes": []},
    "NZ": {"twilio_code": "NZ", "area_codes": []},
}

SUPPORTED_COUNTRIES = set(_COUNTRY_CONFIG.keys())


async def find_available_number(
    subaccount_sid: str,
    subaccount_token: str,
    country_code: str = "CA",
) -> str:
    cc = country_code.upper()
    if cc not in _COUNTRY_CONFIG:
        logger.warning("Country %s not supported, falling back to CA", cc)
        cc = "CA"

    config = _COUNTRY_CONFIG[cc]
    twilio_code = config["twilio_code"]
    area_codes: list[str] = config["area_codes"]
    client = _sub_client(subaccount_sid, subaccount_token)

    # Try area codes first (North America)
    for area_code in area_codes:
        try:
            results = client.available_phone_numbers(twilio_code).local.list(
                area_code=area_code, limit=1,
            )
            if results:
                number = results[0].phone_number
                logger.info("Found %s in area code %s (sub-account %s)", number, area_code, subaccount_sid)
                return number
        except TwilioRestException as e:
            logger.warning("Area code %s search failed on sub-account %s: %s", area_code, subaccount_sid, e)

    # National fallback — no area code filter
    try:
        results = client.available_phone_numbers(twilio_code).local.list(limit=1)
        if results:
            number = results[0].phone_number
            logger.info("Found %s via national search in %s (sub-account %s)", number, twilio_code, subaccount_sid)
            return number
    except TwilioRestException as e:
        logger.error("National search failed for %s on sub-account %s: %s", twilio_code, subaccount_sid, e)
        raise

    raise ValueError(f"No available local numbers found in {twilio_code}")


async def purchase_number(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
) -> str:
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        incoming = client.incoming_phone_numbers.create(phone_number=phone_number)
        logger.info(
            "Purchased number %s on sub-account %s (SID %s)",
            incoming.phone_number, subaccount_sid, incoming.sid,
        )
        return incoming.phone_number
    except TwilioRestException as e:
        logger.error(
            "Failed to purchase number %s on sub-account %s: %s",
            phone_number, subaccount_sid, e,
        )
        raise


async def release_number(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
) -> None:
    """Release a purchased number back to Twilio. Used for rollback on failed provisioning."""
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
        if numbers:
            numbers[0].delete()
            logger.info("Released number %s from sub-account %s", phone_number, subaccount_sid)
    except Exception as e:
        logger.error("Failed to release number %s on rollback: %s", phone_number, e)


TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")


async def send_whatsapp(to_number: str, body: str) -> bool:
    """Send a WhatsApp message via the main Twilio account (sandbox or Business API)."""
    try:
        client = _master_client()
        msg = client.messages.create(
            body=body,
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
        )
        logger.info("WhatsApp sent to %s (SID %s)", to_number, msg.sid)
        return True
    except TwilioRestException as e:
        logger.error("Failed to send WhatsApp to %s: %s", to_number, e)
        return False


async def send_sms(
    subaccount_sid: str,
    subaccount_token: str,
    from_number: str,
    to_number: str,
    body: str,
) -> bool:
    """Send an SMS from the tenant's provisioned number to the caller."""
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        logger.info("SMS sent to %s (SID %s)", to_number, message.sid)
        return True
    except TwilioRestException as e:
        logger.error("Failed to send SMS to %s: %s", to_number, e)
        return False


async def point_number_to_vapi(
    subaccount_sid: str,
    subaccount_token: str,
    phone_number: str,
    vapi_sip_uri: str,
) -> bool:
    try:
        client = _sub_client(subaccount_sid, subaccount_token)
        numbers = client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)
        if not numbers:
            raise ValueError(f"Number {phone_number} not found on sub-account {subaccount_sid}")
        numbers[0].update(voice_url=vapi_sip_uri, voice_method="POST")
        logger.info(
            "Pointed %s to Vapi SIP URI on sub-account %s",
            phone_number, subaccount_sid,
        )
        return True
    except (TwilioRestException, ValueError) as e:
        logger.error(
            "Failed to point %s to Vapi on sub-account %s: %s",
            phone_number, subaccount_sid, e,
        )
        raise
