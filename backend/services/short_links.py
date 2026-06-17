import os
import re
import secrets
import logging

logger = logging.getLogger(__name__)

_raw_pay_base = os.getenv("PAY_LINK_BASE_URL", "http://localhost:8000")
PAY_LINK_BASE_URL = _raw_pay_base.rstrip("/")

# Unambiguous alphabet — no 0/O, 1/I/L, 8/B
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN  = 8

_VALID_CODE_RE = re.compile(r"^[A-Z2-9]{8,10}$")

_ALLOWED_STRIPE_PREFIXES = (
    "https://checkout.stripe.com/",
    "https://buy.stripe.com/",
)

_CURRENCY_DISPLAY: dict[str, str] = {
    "usd": "USD", "cad": "CAD", "aud": "AUD", "gbp": "GBP",
    "eur": "EUR", "nzd": "NZD", "aed": "AED", "sgd": "SGD",
}


def generate_short_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def is_valid_short_code(code: str) -> bool:
    return bool(_VALID_CODE_RE.match(code))


def is_safe_stripe_url(url: str) -> bool:
    return any(url.startswith(p) for p in _ALLOWED_STRIPE_PREFIXES)


def build_branded_url(short_code: str) -> str:
    return f"{PAY_LINK_BASE_URL}/d/{short_code}"


def format_currency(code: str) -> str:
    """Normalize a Stripe lowercase currency code to display form (e.g. 'cad' → 'CAD')."""
    return _CURRENCY_DISPLAY.get((code or "").lower(), (code or "").upper())
