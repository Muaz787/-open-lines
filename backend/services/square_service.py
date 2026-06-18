import os
import hmac
import hashlib
import base64
import logging
import httpx

logger = logging.getLogger(__name__)

SQUARE_APP_ID         = os.getenv("SQUARE_APP_ID", "")          # Production app ID (sq0idp-...)
SQUARE_APP_SECRET     = os.getenv("SQUARE_APP_SECRET", "")       # Production app secret
SQUARE_SANDBOX_APP_ID = os.getenv("SQUARE_SANDBOX_APP_ID", "")   # Sandbox app ID (sandbox-sq0idp-...)
SQUARE_SANDBOX_APP_SECRET = os.getenv("SQUARE_SANDBOX_APP_SECRET", "")  # Sandbox app secret
SQUARE_ENVIRONMENT    = os.getenv("SQUARE_ENVIRONMENT", "sandbox")  # "sandbox" or "production"
SQUARE_WEBHOOK_SIGNATURE_KEY = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY", "")


def _app_id() -> str:
    if SQUARE_ENVIRONMENT == "sandbox" and SQUARE_SANDBOX_APP_ID:
        return SQUARE_SANDBOX_APP_ID
    return SQUARE_APP_ID


def _app_secret() -> str:
    if SQUARE_ENVIRONMENT == "sandbox" and SQUARE_SANDBOX_APP_SECRET:
        return SQUARE_SANDBOX_APP_SECRET
    return SQUARE_APP_SECRET

_raw_frontend = os.getenv("FRONTEND_URL", "https://openlines.ai")
FRONTEND_URL = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"
_raw_backend = os.getenv("APP_BACKEND_URL", "https://backend-production-71174.up.railway.app").strip()
APP_BACKEND_URL = _raw_backend if _raw_backend.startswith("http") else f"https://{_raw_backend}"

def _oauth_base() -> str:
    """OAuth base URL must match the API environment.
    Production tokens (connect.squareup.com) are rejected by the sandbox API and vice versa."""
    if SQUARE_ENVIRONMENT == "production":
        return "https://connect.squareup.com"
    return "https://connect.squareupsandbox.com"

_SCOPES = [
    "MERCHANT_PROFILE_READ",
    "PAYMENTS_WRITE_ADDITIONAL_RECIPIENTS",
    "ORDERS_WRITE",
    "PAYMENTS_WRITE",
]


def _api_base() -> str:
    if SQUARE_ENVIRONMENT == "production":
        return "https://connect.squareup.com"
    return "https://connect.squareupsandbox.com"


def _sq_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Square-Version": "2024-11-20",
        "Content-Type": "application/json",
    }


def build_oauth_url(tenant_id: str, state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": _app_id(),
        "scope": " ".join(_SCOPES),
        "session": "false",
        "state": state,
    }
    return f"{_oauth_base()}/oauth2/authorize?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange authorization code for access_token + refresh_token."""
    callback_url = f"{APP_BACKEND_URL}/square-connect/callback"
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{_oauth_base()}/oauth2/token",
            json={
                "client_id": _app_id(),
                "client_secret": _app_secret(),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback_url,
            },
            headers={"Square-Version": "2024-11-20", "Content-Type": "application/json"},
            timeout=15.0,
        )
        res.raise_for_status()
        return res.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{_oauth_base()}/oauth2/token",
            json={
                "client_id": _app_id(),
                "client_secret": _app_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Square-Version": "2024-11-20", "Content-Type": "application/json"},
            timeout=15.0,
        )
        res.raise_for_status()
        return res.json()


async def get_merchant_info(access_token: str) -> dict:
    """Returns {"merchant_id": ..., "currency": ..., "country": ...}"""
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{_api_base()}/v2/merchants/me",
            headers=_sq_headers(access_token),
            timeout=15.0,
        )
        res.raise_for_status()
        merchant = res.json().get("merchant", {})
        return {
            "merchant_id": merchant.get("id", ""),
            "currency":    merchant.get("currency", "USD"),
            "country":     merchant.get("country", ""),
        }


async def list_locations(access_token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{_api_base()}/v2/locations",
            headers=_sq_headers(access_token),
            timeout=15.0,
        )
        res.raise_for_status()
        return res.json().get("locations", [])


async def create_payment_link(
    access_token: str,
    location_id: str,
    amount_cents: int,
    currency: str,
    name: str,
    note: str,
    tenant_id: str,
    payment_id: str,
    expiry_minutes: int,
) -> tuple[str, str, str]:
    """Create a Square payment link. Returns (payment_link_id, order_id, url)."""
    import uuid
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "quick_pay": {
            "name": name,
            "price_money": {
                "amount": amount_cents,
                "currency": currency.upper(),
            },
            "location_id": location_id,
        },
        "checkout_options": {
            "redirect_url": f"{FRONTEND_URL}/payment-success",
            "ask_for_shipping_address": False,
        },
        "payment_note": note,
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{_api_base()}/v2/online-checkout/payment-links",
            json=payload,
            headers=_sq_headers(access_token),
            timeout=15.0,
        )
        res.raise_for_status()
        link = res.json().get("payment_link", {})

    return (
        link.get("id", ""),
        link.get("order_id", ""),
        link.get("url", ""),
    )


def verify_webhook(payload: bytes, signature: str, notification_url: str) -> bool:
    """Verify Square HMAC-SHA256 webhook signature. Returns True if valid."""
    if not SQUARE_WEBHOOK_SIGNATURE_KEY:
        raise RuntimeError("SQUARE_WEBHOOK_SIGNATURE_KEY must be set")
    message = notification_url.encode("utf-8") + payload
    expected = base64.b64encode(
        hmac.new(
            SQUARE_WEBHOOK_SIGNATURE_KEY.encode("utf-8"),
            message,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, signature)
