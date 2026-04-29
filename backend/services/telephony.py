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


async def find_available_number(
    subaccount_sid: str,
    subaccount_token: str,
    area_codes: list = ["416", "905", "647"],
) -> str:
    client = _sub_client(subaccount_sid, subaccount_token)
    for area_code in area_codes:
        try:
            results = client.available_phone_numbers("CA").local.list(
                area_code=area_code,
                limit=1,
            )
            if results:
                number = results[0].phone_number
                logger.info(
                    "Found available number %s in area code %s (sub-account %s)",
                    number, area_code, subaccount_sid,
                )
                return number
            logger.info("No numbers available in area code %s", area_code)
        except TwilioRestException as e:
            logger.error(
                "Error searching area code %s on sub-account %s: %s",
                area_code, subaccount_sid, e,
            )
    raise ValueError(
        f"No available numbers found in any of the area codes: {area_codes}"
    )


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
