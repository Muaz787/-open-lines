"""
Platform subscription billing: the plan price catalog, and creating the trialing
subscription a new signup starts on.

NOT to be confused with services/stripe_service.py, which is Stripe CONNECT —
money moving from a tenant's own customers to that tenant (deposits, refunds).
This module is about the tenant paying US.

The price catalog lived in routers/billing.py until the card-required trial
needed it from the onboarding router too. It is plain configuration with no HTTP
concerns, so it belongs in a service; routers/billing.py now aliases these names
rather than keeping a second copy.
"""
from __future__ import annotations

import json
import logging
import os
import time

import stripe

logger = logging.getLogger(__name__)

# Per-plan, per-interval Stripe price IDs. Annual prices are optional — if the
# *_ANNUAL env vars aren't set, annual signups for that plan fail with a clear
# message until the price is created in Stripe.
PRICE_IDS: dict[str, dict[str, str]] = {
    "starter":  {"month": os.getenv("STRIPE_PRICE_STARTER", ""),  "year": os.getenv("STRIPE_PRICE_STARTER_ANNUAL", "")},
    "pro":      {"month": os.getenv("STRIPE_PRICE_PRO", ""),       "year": os.getenv("STRIPE_PRICE_PRO_ANNUAL", "")},
    "business": {"month": os.getenv("STRIPE_PRICE_BUSINESS", ""),  "year": os.getenv("STRIPE_PRICE_BUSINESS_ANNUAL", "")},
}

# Metered overage price linked to a Stripe Billing Meter (event_name: call_minutes)
OVERAGE_PRICE_ID: str = os.getenv("STRIPE_CALL_MINUTES_PRICE_ID") or os.getenv("STRIPE_OVERAGE_PRICE_ID", "")

# Flat set of every plan price ID across intervals (for membership checks)
ALL_PLAN_PRICE_IDS = {pid for p in PRICE_IDS.values() for pid in p.values() if pid}

# Free-trial length. Mirrors services/trial.TRIAL_DAYS; imported lazily where
# needed to keep this module free of a circular import.
TRIAL_DAYS = 7

# List prices, used ONLY as a fallback in trial notices when Stripe can't be
# reached for the real figure. Mirrors frontend/src/lib/plans.ts. Prefer
# upcoming_charge() below, which returns the actual tax-inclusive amount.
PLAN_LIST_PRICES: dict[str, int] = {"starter": 99, "pro": 199, "business": 379}


def _money(cents: int, currency: str = "cad") -> str:
    return f"${cents / 100:,.2f} {currency.upper()}"


def upcoming_charge(tenant: dict) -> dict:
    """What the tenant will actually be charged when their trial ends, plus the
    card it lands on. Best-effort: every failure degrades to the plan list price
    rather than blocking the notice, because a trial-ending email that never
    sends is far worse than one quoting a pre-tax figure.

    Returns {"amount_text": str, "card_last4": str}.
    """
    plan     = (tenant.get("subscription_plan") or "").lower()
    fallback = PLAN_LIST_PRICES.get(plan)
    result   = {
        "amount_text": f"${fallback} USD" if fallback else "",
        "card_last4":  "",
    }

    customer_id = tenant.get("stripe_customer_id") or ""
    sub_id      = tenant.get("stripe_subscription_id") or ""
    key         = os.getenv("STRIPE_SECRET_KEY", "")
    if not (customer_id and key):
        return result
    stripe.api_key = key

    # Real amount, including GST/HST — this is the number the notice must quote.
    try:
        upcoming = stripe.Invoice.upcoming(
            customer=customer_id, subscription=sub_id or None,
            automatic_tax={"enabled": True},
        )
        due = int(getattr(upcoming, "amount_due", 0) or 0)
        if due > 0:
            result["amount_text"] = _money(due, str(getattr(upcoming, "currency", "cad") or "cad"))
            if int(getattr(upcoming, "tax", 0) or 0) > 0:
                result["amount_text"] += " (incl. tax)"
    except Exception as e:
        logger.info("upcoming_charge: could not price tenant %s, using list price: %s", tenant.get("id"), e)

    try:
        cust = stripe.Customer.retrieve(customer_id, expand=["invoice_settings.default_payment_method"])
        pm   = getattr(getattr(cust, "invoice_settings", None), "default_payment_method", None)
        last4 = getattr(getattr(pm, "card", None), "last4", "") or ""
        result["card_last4"] = str(last4)
    except Exception:
        pass

    return result


def norm_interval(interval: str | None) -> str:
    """Normalize any annual alias to 'year', everything else to 'month'."""
    return "year" if (interval or "").strip().lower() in ("year", "annual", "yearly", "yr") else "month"


def resolve_price(plan: str, interval: str | None = "month") -> str:
    """Resolve the Stripe price ID for a plan + billing interval."""
    return PRICE_IDS.get(plan, {}).get(norm_interval(interval), "")


def plan_from_price(price_id: str) -> str | None:
    """Reverse-lookup the plan name from any of its price IDs."""
    for plan, intervals in PRICE_IDS.items():
        if price_id in intervals.values():
            return plan
    return None


def interval_from_price(price_id: str) -> str:
    """Reverse-lookup the billing interval ('month'/'year') from a price ID."""
    for intervals in PRICE_IDS.values():
        for iv, pid in intervals.items():
            if pid and pid == price_id:
                return iv
    return "month"


def clean_address(raw) -> dict | None:
    """Keep only the Stripe-recognised address fields the AddressElement returns.
    Stripe Tax needs at least country + postal_code to resolve a GST/HST jurisdiction."""
    if not isinstance(raw, dict):
        return None
    allowed = ("line1", "line2", "city", "state", "postal_code", "country")
    addr = {k: str(raw[k]).strip() for k in allowed if raw.get(k)}
    if not addr.get("country") or not addr.get("postal_code"):
        return None
    return addr


# ── Card-setup token ─────────────────────────────────────────────────────────
#
# /onboarding/setup-card creates a Stripe Customer BEFORE a tenant exists, so the
# customer id has to survive the round trip to /onboarding/provision. Handing the
# raw id to the browser and trusting it back would be an IDOR: /provision is a
# public endpoint (there is no account to authenticate against yet), so anyone
# could post someone else's customer id and attach a subscription to it.
#
# Instead the id comes back inside an AES-256-GCM token (services/security), which
# is authenticated encryption — it cannot be read or forged without the server
# key. Stateless on purpose: an in-memory map would not survive a Railway restart
# or a second container mid-signup, stranding someone who had already entered a card.

CARD_SETUP_TOKEN_TTL_SECONDS = 2 * 60 * 60


def issue_card_setup_token(customer_id: str) -> str:
    from services.security import encrypt
    return encrypt(json.dumps({
        "cus": customer_id,
        "exp": int(time.time()) + CARD_SETUP_TOKEN_TTL_SECONDS,
    }))


def read_card_setup_token(token: str) -> str:
    """Return the Stripe customer id inside a setup token.
    Raises ValueError if the token is malformed, tampered with, or expired."""
    from services.security import decrypt

    payload = json.loads(decrypt(token))
    customer_id = str(payload.get("cus") or "")
    if not customer_id:
        raise ValueError("card setup token has no customer")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise ValueError("card setup token expired")
    return customer_id


# ── Trial subscription ───────────────────────────────────────────────────────

async def create_trial_subscription(
    *,
    tenant_id: str,
    plan: str,
    customer_id: str,
    payment_method_id: str,
    email: str = "",
    business_name: str = "",
    address: dict | None = None,
) -> dict:
    """Put a freshly provisioned tenant onto a trialing subscription.

    Called at the END of /onboarding/provision — only once the phone number and
    assistant actually exist, so a provisioning failure can never leave a
    subscription behind on a tenant that does not work.

    Monthly only: an annual plan would land a four-figure charge on day 8, which
    is a chargeback magnet. Tenants can switch to annual after converting.

    Returns {"ok": bool, ...}. Never raises — the tenant is already provisioned
    and usable at this point, so a Stripe failure degrades to the card-free
    derived trial (services/trial) rather than failing the signup outright.
    """
    from db import supabase as db

    price_id = resolve_price(plan, "month")
    if not price_id:
        logger.error("create_trial_subscription: STRIPE_PRICE_%s not configured", plan.upper())
        return {"ok": False, "error": "price_not_configured"}

    key = os.getenv("STRIPE_SECRET_KEY", "")
    if key:
        stripe.api_key = key

    try:
        # Persist billing details on the Customer BEFORE the subscription exists.
        # automatic_tax reads the customer's address to pick the GST/HST rate, and
        # an invoice that has already been created will not recompute tax later.
        cust_update: dict = {}
        if address:
            cust_update["address"] = address
        if business_name:
            cust_update["name"] = business_name
        if email:
            cust_update["email"] = email
        # Belt and braces: the SetupIntent already attached this payment method,
        # but making it the customer's invoice default guarantees the trial-end
        # charge uses the card the tenant actually entered.
        cust_update["invoice_settings"] = {"default_payment_method": payment_method_id}
        cust_update["metadata"] = {"tenant_id": tenant_id}
        stripe.Customer.modify(customer_id, **cust_update)
    except Exception as e:
        # Non-fatal on its own: the subscription can still be created. Tax may be
        # wrong on the first invoice, which is recoverable, unlike a failed signup.
        logger.warning("create_trial_subscription: customer %s update failed: %s", customer_id, e)

    items: list[dict] = [{"price": price_id}]
    if OVERAGE_PRICE_ID:
        items.append({"price": OVERAGE_PRICE_ID})

    try:
        sub = stripe.Subscription.create(
            customer=customer_id,
            items=items,
            trial_period_days=TRIAL_DAYS,
            default_payment_method=payment_method_id,
            automatic_tax={"enabled": True},
            # If the card is somehow gone by trial end, cancel rather than leaving
            # a live line on an unpayable subscription.
            trial_settings={"end_behavior": {"missing_payment_method": "cancel"}},
            metadata={"tenant_id": tenant_id, "plan": plan},
            # A retried provision must not create a second subscription.
            idempotency_key=f"trial-sub-{tenant_id}",
        )
    except Exception as e:
        logger.error("create_trial_subscription: Stripe failed for tenant %s: %s", tenant_id, e)
        return {"ok": False, "error": "stripe_error"}

    status     = str(getattr(sub, "status", "") or "")
    trial_end  = getattr(sub, "trial_end", None)
    period_start = getattr(sub, "current_period_start", None)

    from datetime import datetime, timezone
    updates: dict = {
        "stripe_customer_id":     customer_id,
        "stripe_subscription_id": sub.id,
        "subscription_plan":      plan,
        "subscription_status":    status,   # 'trialing' in the normal case
    }
    if trial_end:
        updates["stripe_trial_ends_at"] = datetime.fromtimestamp(int(trial_end), tz=timezone.utc).isoformat()
    if period_start:
        # Seed the anchor now rather than on the tenant's first call. The trial ->
        # paid counter reset compares this against Stripe's new period start, and
        # skips entirely when the anchor is empty (services/usage).
        updates["billing_period_anchor"] = datetime.fromtimestamp(
            int(period_start), tz=timezone.utc
        ).strftime("%Y-%m-%d")

    try:
        await db.update_tenant(tenant_id, updates)
    except Exception as e:
        # Stripe has the subscription; we lost our copy of it. The billing webhook
        # reconciles on the next subscription event, but until then the tenant
        # looks card-free, so this must be loud.
        logger.error(
            "create_trial_subscription: sub %s created but DB write failed for tenant %s: %s",
            sub.id, tenant_id, e,
        )
        return {"ok": False, "error": "db_error", "subscription_id": sub.id, "status": status}

    logger.info(
        "Trial subscription %s created for tenant %s (plan=%s, status=%s)",
        sub.id, tenant_id, plan, status,
    )
    return {
        "ok": True,
        "subscription_id": sub.id,
        "status": status,
        "trial_ends_at": updates.get("stripe_trial_ends_at"),
        "plan": plan,
    }
