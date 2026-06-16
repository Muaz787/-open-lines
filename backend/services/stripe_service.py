import os
import logging
import stripe
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY              = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PAYMENTS_WEBHOOK_SECRET = os.getenv("STRIPE_PAYMENTS_WEBHOOK_SECRET", "")
_raw_frontend  = os.getenv("FRONTEND_URL", "https://openlines.ai")
FRONTEND_URL   = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"
_raw_backend   = os.getenv("APP_BACKEND_URL", "https://backend-production-71174.up.railway.app")
APP_BACKEND_URL = _raw_backend if _raw_backend.startswith("http") else f"https://{_raw_backend}"


def _key() -> str:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY must be set")
    return STRIPE_SECRET_KEY


async def create_connect_account(business_name: str) -> str:
    """Create a Stripe Connect Express account. Returns the account ID."""
    acct = stripe.Account.create(
        type="express",
        business_profile={"name": business_name},
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        api_key=_key(),
    )
    logger.info("Created Stripe Connect account %s for '%s'", acct.id, business_name)
    return acct.id


async def create_account_link(account_id: str, tenant_id: str) -> str:
    """Create a Stripe Connect onboarding link. Returns the URL.
    Both return/refresh go to the frontend — avoids APP_BACKEND_URL dependency."""
    dashboard_url = f"{FRONTEND_URL}/dashboard/{tenant_id}/payments"
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=f"{dashboard_url}?stripe=refresh&account_id={account_id}",
        return_url=f"{dashboard_url}?stripe=return&account_id={account_id}",
        type="account_onboarding",
        api_key=_key(),
    )
    return link.url


async def get_account(account_id: str) -> dict:
    """Retrieve a Connect account status."""
    acct = stripe.Account.retrieve(account_id, api_key=_key())
    return {
        "id": acct.id,
        "charges_enabled": acct.charges_enabled,
        "payouts_enabled": acct.payouts_enabled,
        "details_submitted": acct.details_submitted,
    }


async def create_checkout_session(
    stripe_account_id: str,
    amount_cents: int,
    description: str,
    tenant_id: str,
    payment_id: str,
    caller_name: str,
    expiry_minutes: int,
    currency: str = "usd",
) -> tuple[str, str]:
    """Create a Stripe Checkout Session on the tenant's connected account.
    Returns (session_id, checkout_url)."""
    expires_at = int(
        (datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)).timestamp()
    )
    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": currency.lower(),
                "product_data": {"name": description},
                "unit_amount": amount_cents,
            },
            "quantity": 1,
        }],
        metadata={
            "tenant_id": tenant_id,
            "payment_id": payment_id,
            "caller_name": caller_name,
            "type": "deposit",
        },
        expires_at=expires_at,
        success_url=f"{FRONTEND_URL}/payment-success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{FRONTEND_URL}/payment-cancelled",
        stripe_account=stripe_account_id,
        api_key=_key(),
    )
    return session.id, session.url


def verify_webhook(payload: bytes, sig_header: str) -> dict:
    if not STRIPE_PAYMENTS_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_PAYMENTS_WEBHOOK_SECRET must be set")
    return stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_PAYMENTS_WEBHOOK_SECRET
    )
