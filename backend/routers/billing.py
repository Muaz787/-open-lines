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

PRICE_IDS: dict[str, str] = {
    "starter":  os.getenv("STRIPE_PRICE_STARTER", ""),
    "pro":      os.getenv("STRIPE_PRICE_PRO", ""),
    "business": os.getenv("STRIPE_PRICE_BUSINESS", ""),
}

stripe.api_key = STRIPE_SECRET_KEY


@router.post("/create-checkout")
async def create_checkout(body: dict):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="plan must be starter, pro, or business")

    price_id = PRICE_IDS[plan]
    if not price_id:
        raise HTTPException(status_code=500, detail=f"STRIPE_PRICE_{plan.upper()} not configured on server")

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

    elif event_type == "customer.subscription.updated":
        sub: dict       = event.get("data", {}).get("object", {})
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
            if tenant:
                await db.update_tenant(tenant["id"], {"subscription_status": our_status})
                logger.info("Subscription status updated to %s for customer %s", our_status, customer_id)
        except Exception as e:
            logger.error("Failed to update subscription status for customer %s: %s", customer_id, e)

    elif event_type == "customer.subscription.deleted":
        sub     = event.get("data", {}).get("object", {})
        customer_id = sub.get("customer", "")

        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant:
                await db.update_tenant(tenant["id"], {
                    "subscription_status": "canceled",
                    "subscription_plan":   None,
                })
                logger.info("Subscription canceled for customer %s", customer_id)
        except Exception as e:
            logger.error("Failed to cancel subscription for customer %s: %s", customer_id, e)

    return {"status": "ok"}


@router.post("/create-subscription")
async def create_subscription(body: dict):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="plan must be starter, pro, or business")

    price_id = PRICE_IDS[plan]
    if not price_id:
        raise HTTPException(status_code=500, detail=f"STRIPE_PRICE_{plan.upper()} not configured on server")

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

    # If an active/past_due subscription already exists, update its plan (upgrade/downgrade)
    existing_sub_id: str = tenant.get("stripe_subscription_id", "") or ""
    if existing_sub_id:
        try:
            existing = stripe.Subscription.retrieve(existing_sub_id)
            if existing.status in ("active", "trialing", "past_due"):
                items = existing.get("items", {}).get("data", [])
                if items:
                    stripe.Subscription.modify(
                        existing_sub_id,
                        items=[{"id": items[0]["id"], "price": price_id}],
                        proration_behavior="create_prorations",
                    )
                    await db.update_tenant(tenant_id, {"subscription_plan": plan})
                    logger.info("Plan changed to %s for tenant %s (sub %s)", plan, tenant_id, existing_sub_id)
                    return {"needs_payment": False, "subscription_id": existing_sub_id}
        except stripe.InvalidRequestError:
            pass  # subscription gone — fall through to create new

    # Create a new incomplete subscription so we can collect payment via Payment Element
    try:
        sub = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice.payment_intent"],
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
    except stripe.StripeError as e:
        logger.error("Stripe subscription creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to create subscription")

    try:
        client_secret = sub.latest_invoice.payment_intent.client_secret
    except Exception as e:
        logger.error("Could not extract client_secret from subscription for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Subscription created but could not get payment intent")

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
    price_id = items[0].get("price", {}).get("id", "") if items else ""
    plan = next((k for k, v in PRICE_IDS.items() if v == price_id), "starter")

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

    if not sub_id and not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe subscription linked to this tenant")

    try:
        if sub_id:
            sub = stripe.Subscription.retrieve(sub_id)
        else:
            # Find latest subscription for this customer
            subs = stripe.Subscription.list(customer=customer_id, limit=1, status="all")
            if not subs.data:
                raise HTTPException(status_code=404, detail="No Stripe subscription found for this customer")
            sub = subs.data[0]

        stripe_status = sub.get("status", "")
        our_status = {
            "active": "active", "trialing": "active",
            "past_due": "past_due", "unpaid": "past_due",
            "canceled": "canceled", "incomplete_expired": "canceled",
        }.get(stripe_status, stripe_status)

        # Extract plan from subscription items
        items = (sub.get("items") or {}).get("data", [])
        price_id = items[0].get("price", {}).get("id", "") if items else ""
        plan = next(
            (k for k, v in PRICE_IDS.items() if v == price_id),
            tenant.get("subscription_plan", "starter"),
        )

        await db.update_tenant(tenant_id, {
            "stripe_subscription_id": sub["id"],
            "stripe_customer_id":     sub["customer"],
            "subscription_plan":      plan,
            "subscription_status":    our_status,
        })
        logger.info("Manually synced subscription for tenant %s: plan=%s status=%s", tenant_id, plan, our_status)
        return {"status": "synced", "plan": plan, "subscription_status": our_status}

    except stripe.StripeError as e:
        logger.error("Stripe sync failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")
