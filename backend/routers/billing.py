import os
import json
import logging
import stripe
from datetime import datetime, timezone as _dt_timezone
from typing import Annotated
from fastapi import APIRouter, HTTPException, Request, Header
from dotenv import load_dotenv

from db import supabase as db
from services import analytics, subscriptions, trial
from services.security import verify_tenant_owner

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

STRIPE_SECRET_KEY    = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "https://openlines.ai")

# Plan price catalog. Defined in services/subscriptions.py so the onboarding
# router can resolve the same prices when it creates a signup's trial
# subscription; these names are kept as aliases so this module reads unchanged.
PRICE_IDS               = subscriptions.PRICE_IDS
STRIPE_OVERAGE_PRICE_ID = subscriptions.OVERAGE_PRICE_ID
_ALL_PLAN_PRICE_IDS     = subscriptions.ALL_PLAN_PRICE_IDS

stripe.api_key = STRIPE_SECRET_KEY


# Stripe status -> our persisted status. Defined in services/trial.py, which owns
# subscription-status semantics (the active set, the call gate), so there is one
# mapping rather than a copy per call site.
_our_status = trial.map_stripe_status


# Price lookups — see services/subscriptions.py.
_norm_interval       = subscriptions.norm_interval
_resolve_price       = subscriptions.resolve_price
_plan_from_price     = subscriptions.plan_from_price
_interval_from_price = subscriptions.interval_from_price


def _items_data(sub) -> list:
    """Return a subscription's line items, robust against the dict.items() name
    collision on Stripe SDK objects — `sub.items` resolves to the builtin dict
    method, not the items field, so always reach the data via subscripting."""
    if sub is None:
        return []
    try:
        items = sub["items"]
    except (KeyError, TypeError, AttributeError):
        items = None
    if not items:
        return []
    try:
        data = items["data"]
    except (KeyError, TypeError, AttributeError):
        data = getattr(items, "data", None)
    return list(data or [])


def _base_item(sub):
    """Return the subscription item for the base plan price (not the overage meter item)."""
    items = _items_data(sub)
    for item in items:
        price_id = getattr(getattr(item, "price", None), "id", "") or ""
        if price_id != STRIPE_OVERAGE_PRICE_ID and price_id in _ALL_PLAN_PRICE_IDS:
            return item
    # Fallback: first item that is not the overage price
    for item in items:
        price_id = getattr(getattr(item, "price", None), "id", "") or ""
        if price_id != STRIPE_OVERAGE_PRICE_ID:
            return item
    return items[0] if items else None


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


def _invoice_breakdown(invoice) -> dict:
    """Amounts (in cents) from the first invoice for display: subtotal, tax, total,
    currency. Lets the client show the tax-inclusive total (GST/HST) before paying."""
    if not invoice or isinstance(invoice, str):
        return {}
    subtotal   = getattr(invoice, "subtotal", None)
    total      = getattr(invoice, "total", None)
    amount_due = getattr(invoice, "amount_due", None)
    currency   = getattr(invoice, "currency", None) or "cad"
    tax        = getattr(invoice, "tax", None)
    # Newer API versions drop `invoice.tax`; derive it from total − subtotal.
    if tax is None and subtotal is not None and total is not None:
        tax = max(0, total - subtotal)
    return {
        "subtotal": subtotal,
        "tax":      tax,
        "total":    total if total is not None else amount_due,
        "currency": currency,
    }


@router.post("/create-checkout")
async def create_checkout(body: dict, authorization: Annotated[str | None, Header()] = None):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()
    interval: str  = _norm_interval(body.get("interval"))

    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    await verify_tenant_owner(tenant_id, authorization)
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
        # Stripe Tax: compute GST/HST automatically from the customer's address.
        # Requires a billing address, so we force collection below.
        "automatic_tax": {"enabled": True},
        "billing_address_collection": "required",
        # Let business customers enter a GST/HST number (reverse-charge / B2B).
        "tax_id_collection": {"enabled": True},
    }

    # Reuse existing Stripe customer so payment methods are remembered
    customer_id = tenant.get("stripe_customer_id")
    if customer_id:
        session_params["customer"] = customer_id
        # Persist the address Checkout collects back onto the Customer so
        # automatic_tax can resolve a jurisdiction (required when `customer` is set).
        session_params["customer_update"] = {"address": "auto", "name": "auto"}
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


async def _send_card_trial_email(tenant: dict, kind: str, invoice: dict) -> None:
    """Send a card-trial conversion/failure notice, deduped by a per-tenant flag.

    Never raises: an email problem must not fail the webhook, or Stripe will retry
    the whole event and we would redo the DB work behind it.
    """
    flag = {"converted": "card_trial_converted_sent", "failed": "card_trial_failed_sent"}[kind]
    if tenant.get(flag) or not tenant.get("email"):
        return
    try:
        from services.email import send_card_trial_email
        amount = invoice.get("amount_paid") if kind == "converted" else invoice.get("amount_due")
        currency = str(invoice.get("currency") or "cad").upper()
        amount_text = f"${int(amount or 0) / 100:,.2f} {currency}" if amount else ""

        ok = await send_card_trial_email(
            to=tenant["email"],
            business_name=tenant.get("business_name") or "there",
            kind=kind,
            tenant_id=tenant["id"],
            plan_name=(tenant.get("subscription_plan") or "").title(),
            amount_text=amount_text,
            converted_reason=str(tenant.get("trial_converted_reason") or ""),
        )
        if ok:
            await db.update_tenant(tenant["id"], {flag: True})
    except Exception as e:
        logger.error("Card-trial %s email failed for tenant %s: %s", kind, tenant.get("id"), e)


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

        try:
            _t = await db.get_tenant_by_id(tenant_id)
        except Exception:
            _t = None
        analytics.capture(
            analytics.distinct_id_for(_t, tenant_id),
            "subscription_started",
            {"tenant_id": tenant_id, "plan": plan},
        )

        # Activation confirmation email — once per tenant.
        try:
            if _t and _t.get("email") and not _t.get("subscription_activated_email_sent"):
                from services.email import send_subscription_activated_email
                if await send_subscription_activated_email(
                    to=_t["email"],
                    business_name=_t.get("business_name") or "your business",
                    tenant_id=tenant_id,
                    plan=plan,
                ):
                    await db.update_tenant(tenant_id, {"subscription_activated_email_sent": True})
        except Exception as e:
            logger.error("Subscription activation email failed for tenant %s: %s", tenant_id, e)

        # Add the overage meter item if checkout created the subscription without it
        if sub_id and STRIPE_OVERAGE_PRICE_ID:
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                has_overage = any(
                    (getattr(getattr(it, "price", None), "id", "") == STRIPE_OVERAGE_PRICE_ID)
                    for it in _items_data(sub)
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
        our_status = _our_status(stripe_status, {
            "incomplete": "incomplete", "paused": "paused",
        })

        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant and tenant.get("stripe_subscription_id") == sub_id:
                updates: dict = {"subscription_status": our_status}

                # Mirror the Stripe trial end date so services/trial.py can read it
                # on the call-gating hot path without a Stripe round-trip. Cleared
                # once the subscription leaves `trialing` (converted or cancelled),
                # so a stale date can never make a paid tenant look like a trial.
                trial_end = sub.get("trial_end")
                if our_status == "trialing" and trial_end:
                    updates["stripe_trial_ends_at"] = datetime.fromtimestamp(
                        int(trial_end), tz=_dt_timezone.utc
                    ).isoformat()
                elif our_status != "trialing" and tenant.get("stripe_trial_ends_at"):
                    updates["stripe_trial_ends_at"] = None

                # Trial -> paid transition. This is the ONLY place a natural 7-day
                # conversion is observed: Stripe ends the trial and charges on its
                # own, without going through services/trial.convert_card_trial
                # (which handles only the early exits — minute cap and the
                # dashboard button, both of which set the reason themselves).
                #
                # trial_conversion_unpaid is what lets the call gate tell a bounced
                # FIRST charge from an established customer's expired card: it is
                # set here at conversion and cleared on the first paid invoice
                # below. Without it a natural conversion that failed would keep an
                # unpaid line running indefinitely.
                if (tenant.get("subscription_status") or "") == "trialing" and our_status != "trialing":
                    updates["trial_conversion_unpaid"] = True
                    if not tenant.get("trial_converted_reason"):
                        updates["trial_converted_reason"] = "time"
                    logger.info(
                        "Card trial ended for tenant %s → status=%s (reason=%s)",
                        tenant["id"], our_status,
                        tenant.get("trial_converted_reason") or "time",
                    )
                    analytics.capture(
                        analytics.distinct_id_for(tenant),
                        "trial_converted",
                        {"tenant_id": tenant["id"], "reason": tenant.get("trial_converted_reason") or "time",
                         "status": our_status, "plan": tenant.get("subscription_plan")},
                    )

                # Reset usage counters when billing period rolls over. This is also
                # what gives a converting card trial a clean slate: at trial end
                # Stripe moves current_period_start to the conversion date, so the
                # 60 trial minutes are zeroed and the tenant starts their paid month
                # on their full plan allocation.
                new_period_start = sub.get("current_period_start")
                if new_period_start:
                    new_anchor = datetime.fromtimestamp(int(new_period_start), tz=_dt_timezone.utc).strftime("%Y-%m-%d")
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
                if our_status == "past_due":
                    analytics.capture(
                        analytics.distinct_id_for(tenant),
                        "payment_failed",
                        {"tenant_id": tenant["id"], "status": our_status},
                    )
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
                analytics.capture(
                    analytics.distinct_id_for(tenant),
                    "subscription_canceled",
                    {"tenant_id": tenant["id"]},
                )
            elif tenant:
                logger.info("Ignoring subscription.deleted for stale sub %s (tenant has %s)", sub_id, tenant.get("stripe_subscription_id"))
        except Exception as e:
            logger.error("Failed to cancel subscription for customer %s: %s", customer_id, e)

    elif event_type == "invoice.payment_succeeded":
        # Clears the unpaid-conversion flag. Once ANY invoice is paid, this tenant
        # is an established customer, so a future past_due is ordinary dunning and
        # must NOT cut their line (see services/trial.conversion_payment_failed).
        invoice: dict = event.get("data", {}).get("object", {})
        customer_id   = invoice.get("customer", "")
        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant and tenant.get("trial_conversion_unpaid"):
                await db.update_tenant(tenant["id"], {"trial_conversion_unpaid": False})
                logger.info("First post-trial payment received for tenant %s — line unblocked", tenant["id"])
                analytics.capture(
                    analytics.distinct_id_for(tenant),
                    "trial_conversion_paid",
                    {"tenant_id": tenant["id"], "plan": tenant.get("subscription_plan"),
                     "amount_paid": invoice.get("amount_paid")},
                )
                # Receipt goes out from here, not the daily cron — a charge
                # notification a day late reads as an unexplained card debit.
                await _send_card_trial_email(tenant, "converted", invoice)
        except Exception as e:
            logger.error("invoice.payment_succeeded handling failed for customer %s: %s", customer_id, e)

    elif event_type == "invoice.payment_failed":
        # Status itself is owned by customer.subscription.updated; this handler
        # exists so a failed charge is observable on its own, with the invoice
        # context (attempt count, amount) that the subscription event lacks.
        invoice = event.get("data", {}).get("object", {})
        customer_id = invoice.get("customer", "")
        try:
            tenant = await db.get_tenant_by_stripe_customer(customer_id)
            if tenant:
                first_charge = bool(tenant.get("trial_conversion_unpaid"))
                logger.warning(
                    "Invoice payment failed for tenant %s (attempt=%s, amount_due=%s, first_post_trial=%s)",
                    tenant["id"], invoice.get("attempt_count"), invoice.get("amount_due"), first_charge,
                )
                analytics.capture(
                    analytics.distinct_id_for(tenant),
                    "invoice_payment_failed",
                    {"tenant_id": tenant["id"], "plan": tenant.get("subscription_plan"),
                     "attempt_count": invoice.get("attempt_count"),
                     "amount_due": invoice.get("amount_due"),
                     "first_post_trial_charge": first_charge},
                )
                # Only for the bounced FIRST charge — that is the case where the
                # line actually goes dark and the tenant must act. An established
                # customer mid-dunning keeps service and gets Stripe's own retry
                # emails, so a scary "your line is paused" notice would be wrong.
                if first_charge:
                    await _send_card_trial_email(tenant, "failed", invoice)
        except Exception as e:
            logger.error("invoice.payment_failed handling failed for customer %s: %s", customer_id, e)

    return {"status": "ok"}


_clean_address = subscriptions.clean_address


@router.post("/create-subscription")
async def create_subscription(body: dict, authorization: Annotated[str | None, Header()] = None):
    tenant_id: str = body.get("tenant_id", "")
    plan: str      = body.get("plan", "").lower()
    interval: str  = _norm_interval(body.get("interval"))
    if tenant_id:
        await verify_tenant_owner(tenant_id, authorization)
    # Billing address from the Stripe AddressElement — persisted to the Customer
    # below so automatic_tax can compute GST/HST on the very first invoice.
    address: dict | None = _clean_address(body.get("address"))
    billing_name: str    = str(body.get("name") or "").strip()

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

    # Guard against stale IDs from a different Stripe mode. Tenants created while
    # Stripe was in test mode carry a test customer id (and subscription id) that
    # 404s under the live key ("No such customer"). Detect it and recreate cleanly
    # instead of failing the subscription.
    if customer_id:
        try:
            cust = stripe.Customer.retrieve(customer_id)
            if getattr(cust, "deleted", False):
                customer_id = ""
        except stripe.InvalidRequestError:
            logger.warning(
                "Stored customer %s not found in current Stripe mode for tenant %s — recreating",
                customer_id, tenant_id,
            )
            customer_id = ""
            # A stale customer means the stored subscription id is stale too.
            tenant["stripe_subscription_id"] = ""
            await db.update_tenant(tenant_id, {"stripe_customer_id": None, "stripe_subscription_id": None})

    if not customer_id:
        try:
            params: dict = {"metadata": {"tenant_id": tenant_id}}
            if tenant.get("email"):
                params["email"] = tenant["email"]
            if billing_name or tenant.get("business_name"):
                params["name"] = billing_name or tenant["business_name"]
            if address:
                params["address"] = address
            customer = stripe.Customer.create(**params)
            customer_id = customer.id
            await db.update_tenant(tenant_id, {"stripe_customer_id": customer_id})
        except stripe.StripeError as e:
            logger.error("Failed to create Stripe customer for tenant %s: %s", tenant_id, e)
            raise HTTPException(status_code=500, detail="Failed to create Stripe customer")

    # Persist the billing address onto the Customer BEFORE any subscription/invoice
    # is created — automatic_tax reads the customer's address to pick the GST/HST rate,
    # and an already-created invoice won't recompute tax retroactively.
    if address and customer_id:
        try:
            upd: dict = {"address": address}
            if billing_name:
                upd["name"] = billing_name
            stripe.Customer.modify(customer_id, **upd)
        except stripe.StripeError as e:
            logger.warning("Could not save billing address to customer %s: %s", customer_id, e)

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
                sub_items = _items_data(existing)
                if not sub_items:
                    logger.error("No items on sub %s for tenant %s", existing_sub_id, tenant_id)
                    raise HTTPException(status_code=500, detail="Could not modify subscription — no items found")
                try:
                    base = _base_item(existing)
                    stripe.Subscription.modify(
                        existing_sub_id,
                        items=[{"id": base.id, "price": price_id}],
                        proration_behavior="always_invoice",
                        automatic_tax={"enabled": True},
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
                    return {"needs_payment": True, "client_secret": secret, "subscription_id": existing_sub_id, **_invoice_breakdown(invoice)}
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
            automatic_tax={"enabled": True},
            expand=["latest_invoice.payment_intent"],
            metadata={"tenant_id": tenant_id, "plan": plan},
        )
    except stripe.StripeError as e:
        logger.error("Stripe subscription creation failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to create subscription: {e.user_message or str(e)}")

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
    return {"needs_payment": True, "client_secret": client_secret, "subscription_id": sub.id, **_invoice_breakdown(invoice)}


@router.post("/confirm-payment")
async def confirm_payment(body: dict, authorization: Annotated[str | None, Header()] = None):
    """Called by the frontend after Payment Element confirms — syncs subscription status to DB."""
    tenant_id: str       = body.get("tenant_id", "")
    subscription_id: str = body.get("subscription_id", "")

    if not tenant_id or not subscription_id:
        raise HTTPException(status_code=400, detail="tenant_id and subscription_id are required")
    await verify_tenant_owner(tenant_id, authorization)

    try:
        sub = stripe.Subscription.retrieve(subscription_id)
    except stripe.StripeError as e:
        logger.error("Stripe subscription retrieve failed for %s: %s", subscription_id, e)
        raise HTTPException(status_code=500, detail="Failed to retrieve subscription from Stripe")

    stripe_status: str = sub.status or ""
    our_status = _our_status(stripe_status)

    items = _items_data(sub)
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
async def sync_subscription(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """
    Manually pull the tenant's Stripe subscription and sync status to DB.
    Useful when a webhook was missed or failed.
    """
    await verify_tenant_owner(tenant_id, authorization)
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
        our_status = _our_status(stripe_status)

        # Extract plan from subscription items (use attribute access — SDK objects aren't dicts)
        items = _items_data(sub)
        plan = tenant.get("subscription_plan", "starter")
        for _it in items:
            _p = _plan_from_price(str(getattr(getattr(_it, "price", None), "id", "") or ""))
            if _p:
                plan = _p
                break

        # This endpoint exists to repair a missed webhook, so it must write every
        # field the webhook would have — including the mirrored trial end date,
        # otherwise a resynced card trial is left with no end date at all.
        _trial_end = getattr(sub, "trial_end", None)
        await db.update_tenant(tenant_id, {
            "stripe_subscription_id": sub.id,
            "stripe_customer_id":     sub.customer,
            "subscription_plan":      plan,
            "subscription_status":    our_status,
            "stripe_trial_ends_at": (
                datetime.fromtimestamp(int(_trial_end), tz=_dt_timezone.utc).isoformat()
                if our_status == "trialing" and _trial_end else None
            ),
        })
        logger.info("Manually synced subscription for tenant %s: plan=%s status=%s", tenant_id, plan, our_status)
        return {"status": "synced", "plan": plan, "subscription_status": our_status}

    except stripe.StripeError as e:
        logger.error("Stripe sync failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Stripe error: {e}")


# ── Subscription management endpoints ───────────────────────────────────────

@router.get("/subscription-details/{tenant_id}")
async def subscription_details(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
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
            upcoming    = stripe.Invoice.upcoming(customer=customer_id, subscription=sub_id, automatic_tax={"enabled": True})
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
async def list_invoices(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
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
async def customer_portal(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
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
async def cancel_subscription(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
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


@router.post("/end-trial/{tenant_id}")
async def end_trial(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """End the free trial now and start the paid plan.

    Powers the "start my plan now" action on the dashboard trial banner. Its main
    job is recovery: if auto-conversion at the minute cap failed (Stripe blip),
    the tenant's line is gated by the safety net in services/trial, and this lets
    them unblock themselves in one click instead of filing a support ticket.
    """
    await verify_tenant_owner(tenant_id, authorization)
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not trial.is_card_trial(tenant):
        raise HTTPException(status_code=400, detail="No free trial in progress on this account")

    result = await trial.convert_card_trial(tenant, reason="manual")

    if not result["converted"] and not result["already"]:
        raise HTTPException(status_code=502, detail="We couldn't start your plan just now. Please try again in a moment.")

    return {
        "status":  result["status"],
        "plan":    tenant.get("subscription_plan"),
        "already": result["already"],
    }


@router.post("/reactivate/{tenant_id}")
async def reactivate_subscription(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
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
async def proration_preview(body: dict, authorization: Annotated[str | None, Header()] = None):
    """Return the prorated amount the customer would pay to upgrade now."""
    tenant_id = body.get("tenant_id", "")
    await verify_tenant_owner(tenant_id, authorization)
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
            automatic_tax={"enabled": True},
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
async def upgrade_plan(body: dict, authorization: Annotated[str | None, Header()] = None):
    """
    Immediately modify the subscription to the new (higher) plan with proration.
    Returns the PaymentIntent client_secret so the frontend can collect the charge.
    """
    tenant_id = body.get("tenant_id", "")
    await verify_tenant_owner(tenant_id, authorization)
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
            automatic_tax={"enabled": True},
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
async def downgrade_plan(body: dict, authorization: Annotated[str | None, Header()] = None):
    """
    Schedule a downgrade to take effect at the next billing cycle.
    No proration charge — current plan continues until period end.
    """
    tenant_id = body.get("tenant_id", "")
    await verify_tenant_owner(tenant_id, authorization)
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
            automatic_tax={"enabled": True},
        )

        # Update DB to reflect the new plan (billing changes at next cycle)
        await db.update_tenant(tenant_id, {"subscription_plan": plan})
        logger.info("Downgrade to %s scheduled for tenant %s (period_end=%s)", plan, tenant_id, period_end)
        return {"status": "scheduled", "effective_date": period_end, "plan": plan}

    except stripe.StripeError as e:
        logger.error("Downgrade failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=f"Downgrade failed: {e.user_message or str(e)}")


@router.get("/billing-address/{tenant_id}")
async def get_billing_address(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """Return whether the tenant's Stripe Customer has a tax-resolvable address.
    Used to prompt existing customers (created before address collection) to add one."""
    await verify_tenant_owner(tenant_id, authorization)
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id") or ""
    if not customer_id:
        return {"has_address": False}

    try:
        cust = stripe.Customer.retrieve(customer_id)
        addr = getattr(cust, "address", None) or {}
        country = addr.get("country") if isinstance(addr, dict) else getattr(addr, "country", None)
        postal  = addr.get("postal_code") if isinstance(addr, dict) else getattr(addr, "postal_code", None)
        return {"has_address": bool(country and postal)}
    except stripe.StripeError as e:
        logger.error("get_billing_address failed for tenant %s: %s", tenant_id, e)
        return {"has_address": False}


@router.post("/billing-address/{tenant_id}")
async def save_billing_address(tenant_id: str, body: dict, authorization: Annotated[str | None, Header()] = None):
    """Persist a billing address onto the tenant's Stripe Customer so automatic_tax
    can resolve a GST/HST jurisdiction. Needed for customers created before the
    subscribe flow collected an address (otherwise upgrades fail with
    'customer's location isn't recognized')."""
    await verify_tenant_owner(tenant_id, authorization)
    address = _clean_address(body.get("address"))
    name    = str(body.get("name") or "").strip()
    if not address:
        raise HTTPException(status_code=400, detail="A complete billing address (country + postal code) is required")

    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = tenant.get("stripe_customer_id") or ""
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked to this tenant")

    try:
        upd: dict = {"address": address}
        if name:
            upd["name"] = name
        stripe.Customer.modify(customer_id, **upd)
    except stripe.StripeError as e:
        logger.error("Save billing address failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Could not save billing address")

    logger.info("Billing address saved for tenant %s", tenant_id)
    return {"status": "saved"}


@router.post("/setup-intent/{tenant_id}")
async def create_setup_intent(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """Create a Stripe SetupIntent so the customer can add/update a payment method in-app."""
    await verify_tenant_owner(tenant_id, authorization)
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
async def get_usage(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """Return current billing-period minute usage and overage for a tenant."""
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    from services.usage import get_usage_summary
    return get_usage_summary(tenant)


@router.post("/update-payment-method")
async def update_payment_method(body: dict, authorization: Annotated[str | None, Header()] = None):
    """Attach a new PaymentMethod to the customer and set it as default on the subscription."""
    tenant_id = body.get("tenant_id", "")
    pm_id     = body.get("payment_method_id", "")

    if not tenant_id or not pm_id:
        raise HTTPException(status_code=400, detail="tenant_id and payment_method_id are required")
    await verify_tenant_owner(tenant_id, authorization)

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
