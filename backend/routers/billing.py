import os
import json
import logging
import stripe
from fastapi import APIRouter, HTTPException, Request
from dotenv import load_dotenv

from db import supabase as db

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

STRIPE_SECRET_KEY    = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "https://openlines.ai")

# Per-plan, per-interval Stripe price IDs. Annual prices are optional — if the
# *_ANNUAL env vars aren't set, annual signups for that plan will 500 with a
# clear message until the price is created in Stripe.
PRICE_IDS: dict[str, dict[str, str]] = {
    "starter":  {"month": os.getenv("STRIPE_PRICE_STARTER", ""),  "year": os.getenv("STRIPE_PRICE_STARTER_ANNUAL", "")},
    "pro":      {"month": os.getenv("STRIPE_PRICE_PRO", ""),       "year": os.getenv("STRIPE_PRICE_PRO_ANNUAL", "")},
    "business": {"month": os.getenv("STRIPE_PRICE_BUSINESS", ""),  "year": os.getenv("STRIPE_PRICE_BUSINESS_ANNUAL", "")},
}
# Metered overage price linked to a Stripe Billing Meter (event_name: call_minutes)
STRIPE_OVERAGE_PRICE_ID: str = os.getenv("STRIPE_CALL_MINUTES_PRICE_ID") or os.getenv("STRIPE_OVERAGE_PRICE_ID", "")

# Flat set of every plan price ID across intervals (for membership checks)
_ALL_PLAN_PRICE_IDS = {pid for p in PRICE_IDS.values() for pid in p.values() if pid}

stripe.api_key = STRIPE_SECRET_KEY


def _norm_interval(interval: str | None) -> str:
    """Normalize any annual alias to 'year', everything else to 'month'."""
    return "year" if (interval or "").strip().lower() in ("year", "annual", "yearly", "yr") else "month"


def _resolve_price(plan: str, interval: str | None = "month") -> str:
    """Resolve the Stripe price ID for a plan + billing interval."""
    return PRICE_IDS.get(plan, {}).get(_norm_interval(interval), "")


def _plan_from_price(price_id: str) -> str | None:
    """Reverse-lookup the plan name from any of its price IDs."""
    for plan, intervals in PRICE_IDS.items():
        if price_id in intervals.values():
            return plan
    return None


def _interval_from_price(price_id: str) -> str:
    """Reverse-lookup the billing interval ('month'/'year') from a price ID."""
    for intervals in PRICE_IDS.values():
        for iv, pid in intervals.items():
            if pid and pid == price_id:
                return iv
    return "month"


def _base_item(sub):
    """Return the subscription item for the base plan price (not the overage meter item)."""
    for item in (sub.items.data if sub.items else []):
        price_id = getattr(getattr(item, "price", None), "id", "") or ""
        if price_id != STRIPE_OVERAGE_PRICE_ID and price_id in _ALL_PLAN_PRICE_IDS:
            return item
    # Fallback: first item that is not the overage price
    for item in (sub.items.data if sub.items else []):
        price_id = getattr(getattr(item, "price", None), "id", "") or ""
        if price_id != STRIPE_OVERAGE_PRICE_ID:
            return item
    return sub.items.data[0]


def _sub_interval(sub) -> str:
    """Detect the billing interval of an existing subscription from its base item."""
    base = _base_item(sub)
    pid = getattr(getattr(base, "price", None), "id", "") or ""
    return _interval_from_price(pid)


def _extract_pi_secret(invoice) -> str | None:
    """Get PaymentIntent client_secret from an invoice (stripe <12 / pre-Basil API)."""
    if not invoice:
        return None
    if isinstance(invoice, str):
        try:
            invoice = stripe.Invoice.retrieve(invoice, expand=["payment_intent"])
        except stripe.StripeError:
            return None
    pi = invoice.payment_intent
    if not pi:
        return None
    if isinstance(pi, str):
        try:
            pi = stripe.PaymentIntent.retrieve(pi)
        except stripe.StripeError:
            return None
    return getattr(pi, "client_secret", None) or None


@router.post("/create-checkout")
async def create_checkout(body: dict):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()
    interval: str  = _norm_interval(body.get("interval"))

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="plan must be starter, pro, or business")

    price_id = _resolve_price(plan, interval)
    if not price_id:
        suffix = "_ANNUAL" if interval == "year" else ""
        raise HTTPException(status_code=500, detail=f"STRIPE_PRICE_{plan.upper()}{suffix} not configured on server")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    success_url = f"{FRONTEND_URL}/dashboard/{tenant_id}?billing=success"
    cancel_url  = f"{FRONTEND_URL}/dashboard/{tenant_id}?billing=canceled"

    session_params: dict = {
        "mode":       "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url":  cancel_url,
        "client_reference_id": tenant_id,
        "metadata": {"tenant_id": tenant_id, "plan": plan},
    }

    # Reuse existing Stripe customer so payment methods are remembered
    customer_id = tenant.get("stripe_customer_id")
    if customer_id:
        session_params["customer"] = customer_id
    else:
        email = tenant.get("email")
        if email:
            session_params["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**session_params)
    except stripe.StripeError as e:
        logger.error("Stripe checkout creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")

    logger.info("Checkout session created for tenant %s plan %s", tenant_id, plan)
    return {"checkout_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    # Stripe requires raw bytes to verify the signature — do NOT parse as JSON first
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not set")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # Step 1: verify signature only — discard the SDK object (may be typed, not a plain dict)
    try:
        stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError as e:
        logger.warning("Stripe webhook: invalid signature — %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error("Stripe webhook signature check error: %s", e)
        raise HTTPException(status_code=400, detail="Signature check failed")

    # Step 2: parse raw JSON for safe plain-dict access (avoids stripe SDK object quirks)
    try:
        event: dict = json.loads(payload)
    except Exception as e:
        logger.error("Stripe webhook JSON parse error: %s", e)
        raise HTTPException(status_code=400, detail="JSON parse failed")

    event_type: str = event.get("type", "")
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        session: dict   = event.get("data", {}).get("object", {})
        tenant_id: str  = session.get("client_reference_id") or (session.get("metadata") or {}).get("tenant_id", "")
        plan: str       = (session.get("metadata") or {}).get("plan", "starter")
        customer_id: str = session.get("customer", "")
        sub_id: str      = session.get("subscription", "")

        logger.info("checkout.session.completed — tenant_id=%s plan=%s customer=%s sub=%s",
                    tenant_id, plan, customer_id, sub_id)

        if not tenant_id:
            logger.error("checkout.session.completed: no tenant_id found — client_reference_id and metadata both empty")
            return {"status": "ok", "warning": "no tenant_id"}

        try:
            await db.update_tenant(tenant_id, {
                "stripe_customer_id":      customer_id,
                "stripe_subscription_id":  sub_id,
                "subscription_plan":       plan,
                "subscription_status":     "active",
            })
            logger.info("Tenant %s activated on %s plan", tenant_id, plan)
        except Exception as e:
            logger.error("DB update failed for tenant %s: %s", tenant_id, e)
            raise HTTPException(status_code=500, detail=f"DB update failed: {e}")

        # Add the overage meter item if checkout created the subscription without it
        if sub_id and STRIPE_OVERAGE_PRICE_ID:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                has_overage = any(
                    (getattr(getattr(it, "price", None), "id", "") == STRIPE_OVERAGE_PRICE_ID)
                    for it in (sub.items.data if sub.items else [])
                )
                if not has_overage:
                    stripe.SubscriptionItem.create(
                        subscription=sub_id,
                        price=STRIPE_OVERAGE_PRICE_ID,
                    )
                    logger.info("Added overage item to sub %s for tenant %s", sub_id, tenant_id)
            except Exception as e:
                logger.error("Failed to add overage item to sub %s: %s", sub_id, e)

    elif event_type == "customer.subscription.updated":
        sub: dict       = event.get("data", {}).get("object", {})
        sub_id          = sub.get("id", "")
        customer_id     = sub.get("customer", "")
        stripe_status   = sub.get("status", "")
        our_status = {
            "active": "active", "trialing": "active",
            "past_due": "past_due", "unpaid": "past_due",
            "canceled": "canceled", "incomplete": "incomplete",
            "incomplete_expired": "canceled", "paused": "paused",
        }.get(stripe_status, stripe_status)

        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant and tenant.get("stripe_subscription_id") == sub_id:
                updates: dict = {"subscription_status": our_status}

                # Reset usage counters when billing period rolls over
                new_period_start = sub.get("current_period_start")
                if new_period_start:
                    from datetime import datetime, timezone as _tz
                    new_anchor = datetime.fromtimestamp(int(new_period_start), tz=_tz.utc).strftime("%Y-%m-%d")
                    stored_anchor = str(tenant.get("billing_period_anchor") or "")
                    if stored_anchor and stored_anchor != new_anchor:
                        updates.update({
                            "minutes_used_this_period": 0,
                            "overage_minutes_reported": 0,
                            "billing_period_anchor":    new_anchor,
                        })
                        logger.info("Usage counters reset for new billing period %s → %s (tenant %s)",
                                    stored_anchor, new_anchor, tenant["id"])

                await db.update_tenant(tenant["id"], updates)
                logger.info("Subscription status updated to %s for customer %s sub %s", our_status, customer_id, sub_id)
            elif tenant:
                logger.info("Ignoring subscription.updated for stale sub %s (tenant has %s)", sub_id, tenant.get("stripe_subscription_id"))
        except Exception as e:
            logger.error("Failed to update subscription status for customer %s: %s", customer_id, e)

    elif event_type == "customer.subscription.deleted":
        sub         = event.get("data", {}).get("object", {})
        sub_id      = sub.get("id", "")
        customer_id = sub.get("customer", "")

        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant and tenant.get("stripe_subscription_id") == sub_id:
                await db.update_tenant(tenant["id"], {
                    "subscription_status": "canceled",
                    "subscription_plan":   None,
                })
                logger.info("Subscription canceled for customer %s sub %s", customer_id, sub_id)
            elif tenant:
                logger.info("Ignoring subscription.deleted for stale sub %s (tenant has %s)", sub_id, tenant.get("stripe_subscription_id"))
        except Exception as e:
            logger.error("Failed to cancel subscription for customer %s: %s", customer_id, e)

    return {"status": "ok"}


@router.post("/create-subscription")
async def create_subscription(body: dict):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()
    interval: str  = _norm_interval(body.get("interval"))

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="plan must be starter, pro, or business")

    price_id = _resolve_price(plan, interval)
    if not price_id:
        suffix = "_ANNUAL" if interval == "year" else ""
        raise HTTPException(status_code=500, detail=f"STRIPE_PRICE_{plan.upper()}{suffix} not configured on server")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get or create Stripe customer
    customer_id: str = tenant.get("stripe_customer_id", "") or ""
    if not customer_id:
        try:
            params: dict = {"metadata": {"tenant_id": tenant_id}}
            if tenant.get("email"):
                params["email"] = tenant["email"]
            if tenant.get("business_name"):
                params["name"] = tenant["business_name"]
            customer = stripe.Customer.create(**params)
            customer_id = customer.id
            await db.update_tenant(tenant_id, {"stripe_customer_id": customer_id})
        except stripe.StripeError as e:
            logger.error("Failed to create Stripe customer for tenant %s: %s", tenant_id, e)
            raise HTTPException(status_code=500, detail="Failed to create Stripe customer")

    # If a subscription already exists, handle based on its status
    existing_sub_id: str = tenant.get("stripe_subscription_id", "") or ""
    if existing_sub_id:
        try:
            existing = stripe.Subscription.retrieve(
                existing_sub_id,
                expand=["latest_invoice.payment_intent"],
            )
            logger.info(
                "Existing sub %s status=%s for tenant %s, plan requested=%s",
                existing_sub_id, existing.status, tenant_id, plan,
            )
        except stripe.InvalidRequestError:
            logger.warning("Sub %s not found in Stripe for tenant %s — will create new", existing_sub_id, tenant_id)
            existing = None
        except stripe.StripeError as e:
            logger.error("Failed to retrieve sub %s for tenant %s: %s", existing_sub_id, tenant_id, e)
            raise HTTPException(status_code=500, detail=f"Could not retrieve existing subscription: {e.user_message or str(e)}")

        if existing is not None:
            if existing.status in ("active", "trialing", "past_due"):
                # Upgrade/downgrade — modify only the base plan item, leave overage item untouched
                sub_items = (existing.items.data if existing.items else []) or []
                if not sub_items:
                    logger.error("No items on sub %s for tenant %s", existing_sub_id, tenant_id)
                    raise HTTPException(status_code=500, detail="Could not modify subscription — no items found")
                try:
                    base = _base_item(existing)
                    stripe.Subscription.modify(
                        existing_sub_id,
                        items=[{"id": base.id, "price": price_id}],
                        proration_behavior="always_invoice",
                    )
                except stripe.StripeError as se:
                    logger.error("Stripe modify failed for sub %s tenant %s: %s", existing_sub_id, tenant_id, se)
                    raise HTTPException(status_code=500, detail=f"Plan change failed: {se.user_message or str(se)}")
                await db.update_tenant(tenant_id, {"subscription_plan": plan})
                logger.info("Plan changed to %s for tenant %s (sub %s)", plan, tenant_id, existing_sub_id)
                return {"needs_payment": False, "subscription_id": existing_sub_id}

            elif existing.status == "incomplete":
                # Reuse the existing incomplete subscription's payment intent
                invoice = existing.latest_invoice
                secret = _extract_pi_secret(invoice)
                if secret:
                    logger.info("Reusing incomplete subscription %s for tenant %s", existing_sub_id, tenant_id)
                    return {"needs_payment": True, "client_secret": secret, "subscription_id": existing_sub_id}
                # No usable payment intent — cancel stale incomplete sub and create fresh
                try:
                    stripe.Subscription.cancel(existing_sub_id)
                except stripe.StripeError:
                    pass
                logger.info("Cancelled stale incomplete subscription %s for tenant %s", existing_sub_id, tenant_id)

            elif existing.status in ("canceled", "incomplete_expired"):
                pass  # Fall through to create a new subscription

    # Create a new incomplete subscription so we can collect payment via Payment Element
    try:
        items_payload: list = [{"price": price_id}]
        # Stripe requires all items in a subscription to share the same billing
        # interval, so the monthly overage meter can only attach to monthly plans.
        # Annual plans pre-pay for the year and skip metered overage (upgrade tiers
        # for more minutes).
        if STRIPE_OVERAGE_PRICE_ID and interval == "month":
            items_payload.append({"price": STRIPE_OVERAGE_PRICE_ID})
        sub = stripe.Subscription.create(
            customer=customer_id,
            items=items_payload,
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"],
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
    except stripe.StripeError as e:
        logger.error("Stripe subscription creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to create subscription")

    # If subscription went active immediately (e.g. covered by customer credit balance)
    if getattr(sub, "status", None) == "active":
        await db.update_tenant(tenant_id, {
            "stripe_customer_id":     customer_id,
            "stripe_subscription_id": sub.id,
            "subscription_plan":      plan,
            "subscription_status":    "active",
        })
        logger.info("Subscription %s active immediately (credit balance) for tenant %s", sub.id, tenant_id)
        return {"needs_payment": False, "subscription_id": sub.id}

    try:
        invoice = sub.latest_invoice
        client_secret = _extract_pi_secret(invoice)

        if client_secret is None:
            # No PaymentIntent — only valid if invoice is genuinely $0
            amount_due = getattr(invoice, "amount_due", 1) if invoice and not isinstance(invoice, str) else 1
            if amount_due == 0:
                await db.update_tenant(tenant_id, {
                    "stripe_customer_id":     customer_id,
                    "stripe_subscription_id": sub.id,
                    "subscription_plan":      plan,
                    "subscription_status":    "active",
                })
                logger.info("Subscription %s zero-amount invoice for tenant %s", sub.id, tenant_id)
                return {"needs_payment": False, "subscription_id": sub.id}
            logger.error("No client_secret for sub %s tenant %s (amount_due=%s)", sub.id, tenant_id, amount_due)
            raise HTTPException(status_code=500, detail="Could not initialise payment. Please try again.")

    except HTTPException:
        raise
    except stripe.StripeError as se:
        logger.error("Stripe error extracting payment intent for tenant %s sub %s: %s", tenant_id, sub.id, se)
        raise HTTPException(status_code=500, detail=f"Stripe error: {se.user_message or str(se)}")
    except Exception as e:
        logger.error("Unexpected error extracting payment intent for tenant %s sub %s: %s", tenant_id, sub.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not initialise payment. Please try again.")

    await db.update_tenant(tenant_id, {
        "stripe_customer_id":     customer_id,
        "stripe_subscription_id": sub.id,
        "subscription_plan":      plan,
        "subscription_status":    "incomplete",
    })
    logger.info("Subscription %s created (incomplete) for tenant %s plan %s", sub.id, tenant_id, plan)
    return {"needs_payment": True, "client_secret": client_secret, "subscription_id": sub.id}


@router.post("/confirm-payment")
async def confirm_payment(body: dict):
    """Called by the frontend after Payment Element confirms — syncs subscription status to DB."""
    tenant_id: str       = body.get("tenant_id", "")
    subscription_id: str = body.get("subscription_id", "")

    if not tenant_id or not subscription_id:
        raise HTTPException(status_code=400, detail="tenant_id and subscription_id are required")

    try:
        sub = stripe.Subscription.retrieve(subscription_id)
    except stripe.StripeError as e:
        logger.error("Stripe subscription retrieve failed for %s: %s", subscription_id, e)
        raise HTTPException(status_code=500, detail="Failed to retrieve subscription from Stripe")

    stripe_status: str = sub.status or ""
    our_status = {
        "active": "active", "trialing": "active",
        "past_due": "past_due", "unpaid": "past_due",
        "canceled": "canceled", "incomplete_expired": "canceled",
    }.get(stripe_status, stripe_status)

    items = (sub.get("items") or {}).get("data", [])
    plan = "starter"
    for _it in items:
        _p = _plan_from_price((_it.get("price") or {}).get("id", ""))
        if _p:
            plan = _p
            break

    await db.update_tenant(tenant_id, {
        "stripe_subscription_id": subscription_id,
        "subscription_plan":      plan,
        "subscription_status":    our_status,
    })
    logger.info("Payment confirmed for tenant %s: plan=%s status=%s", tenant_id, plan, our_status)
    return {"status": our_status, "plan": plan}


@router.post("/sync/{tenant_id}")
async def sync_subscription(tenant_id: str):
    """
    Manually pull the tenant's Stripe subscription and sync status to DB.
    Useful when a webhook was missed or failed.
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id      = tenant.get("stripe_subscription_id")
    customer_id = tenant.get("stripe_customer_id")

    if not customer_id and not sub_id:
        raise HTTPException(status_code=400, detail="No Stripe subscription linked to this tenant")

    try:
        # Always prefer the active/trialing sub for this customer — avoids syncing a stale
        # cancelled sub_id that was left in the DB after a webhook race condition.
        sub = None
        if customer_id:
            for status_filter in ("active", "trialing", "past_due", "incomplete"):
                subs = stripe.Subscription.list(customer=customer_id, limit=1, status=status_filter)
                if subs.data:
                    sub = subs.data[0]
                    break
        if sub is None and sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="No Stripe subscription found for this customer")

        stripe_status = str(getattr(sub, "status", "") or "")
        our_status = {
            "active": "active", "trialing": "active",
            "past_due": "past_due", "unpaid": "past_due",
            "canceled": "canceled", "incomplete_expired": "canceled",
        }.get(stripe_status, stripe_status)

        # Extract plan from subscription items (use attribute access — SDK objects aren't dicts)
        items = list(getattr(sub.items, "data", []) if getattr(sub, "items", None) else [])
        plan = tenant.get("subscription_plan", "starter")
        for _it in items:
            _p = _plan_from_price(str(getattr(getattr(_it, "price", None), "id", "") or ""))
            if _p:
                plan = _p
                break

        await db.update_tenant(tenant_id, {
            "stripe_subscription_id": sub.id,
            "stripe_customer_id":     sub.customer,
            "subscription_plan":      plan,
            "subscription_status":    our_status,
        })
        logger.info("Manually synced subscription for tenant %s: plan=%s status=%s", tenant_id, plan, our_status)
        return {"status": "synced", "plan": plan, "subscription_status": our_status}

    except stripe.StripeError as e:
        logger.error("Stripe sync failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


# ── Subscription management endpoints ───────────────────────────────────────

@router.get("/subscription-details/{tenant_id}")
async def subscription_details(tenant_id: str):
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id      = tenant.get("stripe_subscription_id", "") or ""
    customer_id = tenant.get("stripe_customer_id", "") or ""
    db_plan     = tenant.get("subscription_plan") or "starter"
    db_status   = tenant.get("subscription_status") or "none"

    if not sub_id:
        return {"has_subscription": False}

    # ── Live Stripe data ──────────────────────────────────────────────────────
    # Wrapped entirely — any Stripe issue falls back to DB-only response so the
    # page always renders rather than showing a blank "no subscription" state.
    try:
        # expand only default_payment_method; latest_invoice is not used here
        sub = stripe.Subscription.retrieve(sub_id, expand=["default_payment_method"])

        sub_status           = str(sub.status or "")
        cancel_at_period_end = bool(sub.cancel_at_period_end)
        period_start         = int(sub.current_period_start or 0) or None
        period_end           = int(sub.current_period_end   or 0) or None
        interval             = _sub_interval(sub)  # 'month' or 'year'

        # Payment method: subscription default → customer default
        pm = sub.default_payment_method
        if not pm and customer_id:
            try:
                cust         = stripe.Customer.retrieve(customer_id, expand=["invoice_settings.default_payment_method"])
                inv_settings = getattr(cust, "invoice_settings", None)
                if inv_settings:
                    pm = getattr(inv_settings, "default_payment_method", None)
            except Exception:
                pm = None

        pm_info = None
        if pm:
            try:
                card = getattr(pm, "card", None)
                if card:
                    pm_info = {
                        "brand":     str(getattr(card, "brand",      "") or ""),
                        "last4":     str(getattr(card, "last4",      "") or ""),
                        "exp_month": int(getattr(card, "exp_month",  0)  or 0),
                        "exp_year":  int(getattr(card, "exp_year",   0)  or 0),
                    }
            except Exception:
                pass

        # Upcoming invoice amount
        next_amount = None
        try:
            upcoming    = stripe.Invoice.upcoming(customer=customer_id, subscription=sub_id)
            next_amount = int(upcoming.amount_due or 0) or None
        except Exception:
            pass

    except stripe.InvalidRequestError:
        # Subscription deleted from Stripe — treat as no subscription
        return {"has_subscription": False}
    except Exception as e:
        # Any other Stripe/network error — return DB fallback so page doesn't break
        logger.error("subscription_details failed for %s: %s", tenant_id, e)
        return {
            "has_subscription":     True,
            "plan":                 db_plan,
            "status":               db_status,
            "cancel_at_period_end": False,
            "current_period_start": None,
            "current_period_end":   None,
            "next_invoice_amount":  None,
            "payment_method":       None,
        }

    return {
        "has_subscription":      True,
        "plan":                  db_plan,
        "status":                sub_status,
        "interval":              interval,
        "cancel_at_period_end":  cancel_at_period_end,
        "current_period_start":  period_start,
        "current_period_end":    period_end,
        "next_invoice_amount":   next_amount,
        "payment_method":        pm_info,
    }


@router.get("/invoices/{tenant_id}")
async def list_invoices(tenant_id: str):
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id", "") or ""
    if not customer_id:
        return []

    try:
        invoices = stripe.Invoice.list(customer=customer_id, limit=12)
    except stripe.StripeError as e:
        logger.error("list_invoices stripe error for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Stripe error")

    result = []
    for inv in invoices.data:
        result.append({
            "id":                  inv.id,
            "amount_paid":         inv.amount_paid,
            "amount_due":          inv.amount_due,
            "currency":            inv.currency,
            "status":              inv.status,
            "created":             inv.created,
            "invoice_pdf":         inv.invoice_pdf,
            "hosted_invoice_url":  inv.hosted_invoice_url,
        })
    return result


@router.post("/portal/{tenant_id}")
async def customer_portal(tenant_id: str):
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id", "") or ""
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked to this tenant")

    return_url = f"{FRONTEND_URL}/dashboard/{tenant_id}/subscription"
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except stripe.StripeError as e:
        logger.error("Customer portal creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not open billing portal")

    return {"url": session.url}


@router.post("/cancel/{tenant_id}")
async def cancel_subscription(tenant_id: str):
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id = tenant.get("stripe_subscription_id", "") or ""
    if not sub_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    try:
        stripe.Subscription.modify(sub_id, cancel_at_period_end=True)
    except stripe.StripeError as e:
        logger.error("Cancel subscription failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to cancel subscription")

    await db.update_tenant(tenant_id, {"subscription_status": "canceling"})
    logger.info("Subscription set to cancel at period end for tenant %s", tenant_id)
    return {"status": "canceling"}


@router.post("/reactivate/{tenant_id}")
async def reactivate_subscription(tenant_id: str):
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id = tenant.get("stripe_subscription_id", "") or ""
    if not sub_id:
        raise HTTPException(status_code=400, detail="No subscription found")

    try:
        stripe.Subscription.modify(sub_id, cancel_at_period_end=False)
    except stripe.StripeError as e:
        logger.error("Reactivate subscription failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to reactivate subscription")

    await db.update_tenant(tenant_id, {"subscription_status": "active"})
    logger.info("Subscription reactivated for tenant %s", tenant_id)
    return {"status": "active"}


@router.post("/proration-preview")
async def proration_preview(body: dict):
    """Return the prorated amount the customer would pay to upgrade now."""
    tenant_id = body.get("tenant_id", "")
    plan      = body.get("plan", "").lower()
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id      = tenant.get("stripe_subscription_id") or ""
    customer_id = tenant.get("stripe_customer_id") or ""
    if not sub_id or not customer_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    try:
        sub  = stripe.Subscription.retrieve(sub_id)
        item = _base_item(sub)
        # Preserve the customer's current billing interval when changing plans
        price_id = _resolve_price(plan, _sub_interval(sub))
        if not price_id:
            raise HTTPException(status_code=500, detail="Target plan price not configured")
        upcoming = stripe.Invoice.upcoming(
            customer=customer_id,
            subscription=sub_id,
            subscription_items=[{"id": item.id, "price": price_id}],
            subscription_proration_behavior="always_invoice",
        )
        return {
            "amount_due":   upcoming.amount_due,
            "currency":     upcoming.currency,
            "period_end":   sub.current_period_end,
        }
    except stripe.StripeError as e:
        logger.error("Proration preview failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upgrade-plan")
async def upgrade_plan(body: dict):
    """
    Immediately modify the subscription to the new (higher) plan with proration.
    Returns the PaymentIntent client_secret so the frontend can collect the charge.
    """
    tenant_id = body.get("tenant_id", "")
    plan      = body.get("plan", "").lower()
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id = tenant.get("stripe_subscription_id") or ""
    if not sub_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    try:
        sub  = stripe.Subscription.retrieve(sub_id)
        item = _base_item(sub)
        # Preserve the customer's current billing interval when changing plans
        price_id = _resolve_price(plan, _sub_interval(sub))
        if not price_id:
            raise HTTPException(status_code=500, detail="Target plan price not configured")

        updated = stripe.Subscription.modify(
            sub_id,
            items=[{"id": item.id, "price": price_id}],
            proration_behavior="always_invoice",
            expand=["latest_invoice.payment_intent"],
        )

        invoice = updated.latest_invoice
        if isinstance(invoice, str):
            invoice = stripe.Invoice.retrieve(invoice, expand=["payment_intent"])

        pi = invoice.payment_intent if invoice else None
        if isinstance(pi, str):
            pi = stripe.PaymentIntent.retrieve(pi)

        # Already paid (e.g. auto-charged via saved card)
        if pi and getattr(pi, "status", "") == "succeeded":
            await db.update_tenant(tenant_id, {"subscription_plan": plan})
            logger.info("Upgrade to %s auto-charged for tenant %s", plan, tenant_id)
            return {"needs_payment": False, "subscription_id": sub_id}

        client_secret = getattr(pi, "client_secret", None) if pi else None
        amount_due    = getattr(invoice, "amount_due", 0) if invoice else 0
        currency      = getattr(invoice, "currency", "cad") if invoice else "cad"

        if not client_secret:
            # No outstanding charge (zero proration) — just update DB
            await db.update_tenant(tenant_id, {"subscription_plan": plan})
            logger.info("Upgrade to %s (zero proration) for tenant %s", plan, tenant_id)
            return {"needs_payment": False, "subscription_id": sub_id}

        logger.info("Upgrade to %s needs payment (amount=%s) for tenant %s", plan, amount_due, tenant_id)
        return {
            "needs_payment":   True,
            "client_secret":   client_secret,
            "amount_due":      amount_due,
            "currency":        currency,
            "subscription_id": sub_id,
        }

    except stripe.StripeError as e:
        logger.error("Upgrade failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Upgrade failed: {e.user_message or str(e)}")


@router.post("/downgrade-plan")
async def downgrade_plan(body: dict):
    """
    Schedule a downgrade to take effect at the next billing cycle.
    No proration charge — current plan continues until period end.
    """
    tenant_id = body.get("tenant_id", "")
    plan      = body.get("plan", "").lower()
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    sub_id = tenant.get("stripe_subscription_id") or ""
    if not sub_id:
        raise HTTPException(status_code=400, detail="No active subscription")

    try:
        sub  = stripe.Subscription.retrieve(sub_id)
        item = _base_item(sub)
        period_end = sub.current_period_end
        # Preserve the customer's current billing interval when changing plans
        price_id = _resolve_price(plan, _sub_interval(sub))
        if not price_id:
            raise HTTPException(status_code=500, detail="Target plan price not configured")

        stripe.Subscription.modify(
            sub_id,
            items=[{"id": item.id, "price": price_id}],
            proration_behavior="none",
            billing_cycle_anchor="unchanged",
        )

        # Update DB to reflect the new plan (billing changes at next cycle)
        await db.update_tenant(tenant_id, {"subscription_plan": plan})
        logger.info("Downgrade to %s scheduled for tenant %s (period_end=%s)", plan, tenant_id, period_end)
        return {"status": "scheduled", "effective_date": period_end, "plan": plan}

    except stripe.StripeError as e:
        logger.error("Downgrade failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Downgrade failed: {e.user_message or str(e)}")


@router.post("/setup-intent/{tenant_id}")
async def create_setup_intent(tenant_id: str):
    """Create a Stripe SetupIntent so the customer can add/update a payment method in-app."""
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id") or ""
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked to this tenant")

    try:
        si = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=["card"],
            usage="off_session",
        )
    except stripe.StripeError as e:
        logger.error("SetupIntent creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not initialise payment form")

    return {"client_secret": si.client_secret}


@router.get("/usage/{tenant_id}")
async def get_usage(tenant_id: str):
    """Return current billing-period minute usage and overage for a tenant."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    from services.usage import get_usage_summary
    return get_usage_summary(tenant)


@router.post("/update-payment-method")
async def update_payment_method(body: dict):
    """Attach a new PaymentMethod to the customer and set it as default on the subscription."""
    tenant_id = body.get("tenant_id", "")
    pm_id     = body.get("payment_method_id", "")

    if not tenant_id or not pm_id:
        raise HTTPException(status_code=400, detail="tenant_id and payment_method_id are required")

    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id") or ""
    sub_id      = tenant.get("stripe_subscription_id") or ""

    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked")

    try:
        # Attach PM to customer
        stripe.PaymentMethod.attach(pm_id, customer=customer_id)
        # Set as customer invoice default
        stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id})
        # Set as subscription default so next invoice uses it
        if sub_id:
            stripe.Subscription.modify(sub_id, default_payment_method=pm_id)
    except stripe.StripeError as e:
        logger.error("Update payment method failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Could not update payment method: {e.user_message or str(e)}")

    logger.info("Payment method updated for tenant %s", tenant_id)
    return {"status": "updated"}
