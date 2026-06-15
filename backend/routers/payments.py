import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services import stripe_service as svc, vapi
from services.webhook_processor import _format_whatsapp_message
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

_ELIGIBLE_PLANS   = {"pro", "business"}
_ELIGIBLE_STATUSES = {"active", "trialing", "canceling"}


def _is_eligible(tenant: dict) -> bool:
    plan   = (tenant.get("subscription_plan") or "").lower()
    status = tenant.get("subscription_status") or ""
    return plan in _ELIGIBLE_PLANS and status in _ELIGIBLE_STATUSES


# ---------------------------------------------------------------------------
# GET /payments/settings/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/settings/{tenant_id}")
async def get_settings(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "eligible":              _is_eligible(tenant),
        "stripe_connected":      bool(tenant.get("stripe_account_id")),
        "deposits_enabled":      bool(tenant.get("stripe_deposits_enabled")),
        "deposit_cents":         int(tenant.get("stripe_deposit_cents") or 2500),
        "deposit_mandatory":     bool(tenant.get("stripe_deposit_mandatory", True)),
        "deposit_expiry_min":    int(tenant.get("stripe_deposit_expiry_min") or 120),
        "deposit_label":         tenant.get("stripe_deposit_label") or "Appointment Deposit",
    }


# ---------------------------------------------------------------------------
# POST /payments/settings/{tenant_id}
# ---------------------------------------------------------------------------

class DepositSettingsRequest(BaseModel):
    deposits_enabled:   bool
    deposit_cents:      int
    deposit_mandatory:  bool
    deposit_expiry_min: int
    deposit_label:      str | None = None


@router.post("/settings/{tenant_id}")
async def save_settings(tenant_id: str, body: DepositSettingsRequest):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not _is_eligible(tenant):
        raise HTTPException(status_code=403, detail="Pro or Business plan required")

    if body.deposit_cents < 50:
        raise HTTPException(status_code=400, detail="Minimum deposit is $0.50")

    if not tenant.get("stripe_account_id") and body.deposits_enabled:
        raise HTTPException(
            status_code=400,
            detail="Connect your Stripe account before enabling deposits",
        )

    update = {
        "stripe_deposits_enabled": body.deposits_enabled,
        "stripe_deposit_cents":    body.deposit_cents,
        "stripe_deposit_mandatory": body.deposit_mandatory,
        "stripe_deposit_expiry_min": body.deposit_expiry_min,
    }
    if body.deposit_label:
        update["stripe_deposit_label"] = body.deposit_label

    try:
        await db.update_tenant(tenant_id, update)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Re-patch assistant so tool appears/disappears based on new setting
    try:
        updated_tenant = await db.get_tenant_by_id(tenant_id)
        if updated_tenant:
            await vapi.patch_assistant_tools(updated_tenant)
    except Exception as e:
        logger.warning("Failed to patch assistant after deposit settings change for tenant %s: %s", tenant_id, e)

    return {"status": "saved"}


# ---------------------------------------------------------------------------
# GET /payments/list/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/list/{tenant_id}")
async def list_payments(tenant_id: str, limit: int = 50):
    try:
        payments = await db.get_payments_by_tenant(tenant_id, limit=min(limit, 100))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"payments": payments}


# ---------------------------------------------------------------------------
# POST /payments/webhook  (Stripe webhook — raw body required)
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = svc.verify_webhook(payload, sig_header)
    except Exception as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id   = event["id"]
    event_type = event["type"]

    # Idempotency check
    existing = await db.get_stripe_webhook_event(event_id)
    if existing and existing.get("processed"):
        return {"status": "already_processed"}

    # Persist event for audit trail (ignore duplicate-insert errors)
    try:
        session_obj = event.get("data", {}).get("object", {})
        tenant_id   = (session_obj.get("metadata") or {}).get("tenant_id")
        await db.insert_stripe_webhook_event(event_id, event_type, tenant_id, dict(event))
    except Exception as e:
        logger.warning("Could not persist Stripe webhook event %s: %s", event_id, e)

    try:
        match event_type:
            case "checkout.session.completed":
                await _handle_checkout_completed(event["data"]["object"])
            case "checkout.session.expired":
                await _handle_checkout_expired(event["data"]["object"])
    except Exception as e:
        logger.error("Stripe webhook processing failed for event %s: %s", event_id, e)
        raise HTTPException(status_code=500, detail="Processing failed")

    try:
        await db.mark_stripe_webhook_processed(event_id)
    except Exception:
        pass

    return {"status": "ok"}


async def _handle_checkout_completed(session: dict) -> None:
    meta        = session.get("metadata") or {}
    payment_id  = meta.get("payment_id")
    tenant_id   = meta.get("tenant_id")

    if not payment_id or not tenant_id:
        logger.warning("checkout.session.completed missing metadata: %s", meta)
        return

    payment = await db.get_payment_by_checkout_session(session.get("id", ""))
    if not payment:
        logger.warning("No payment record found for session %s", session.get("id"))
        return

    paid_at = datetime.now(timezone.utc).isoformat()
    await db.update_payment(payment["id"], {
        "status":           "succeeded",
        "paid_at":          paid_at,
        "payment_intent_id": session.get("payment_intent"),
    })
    logger.info("Payment %s succeeded for tenant %s", payment["id"], tenant_id)

    # Confirm the linked appointment
    if payment.get("appointment_id"):
        try:
            await db.update_appointment(payment["appointment_id"], {"status": "confirmed"})
            logger.info("Appointment %s confirmed after payment", payment["appointment_id"])
        except Exception as e:
            logger.error("Failed to confirm appointment %s: %s", payment["appointment_id"], e)

    # Notify the business owner
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if tenant:
            await _notify_payment(tenant, payment)
    except Exception as e:
        logger.error("Payment notification failed for tenant %s: %s", tenant_id, e)


async def _handle_checkout_expired(session: dict) -> None:
    meta       = session.get("metadata") or {}
    payment_id = meta.get("payment_id")

    if not payment_id:
        return

    payment = await db.get_payment_by_checkout_session(session.get("id", ""))
    if not payment:
        return

    await db.update_payment(payment["id"], {"status": "expired"})
    logger.info("Payment %s expired (checkout session timed out)", payment["id"])


async def _notify_payment(tenant: dict, payment: dict) -> None:
    """Fire Slack and/or email notification for a received deposit."""
    caller_name  = payment.get("caller_name") or "Customer"
    caller_phone = payment.get("caller_phone") or ""
    service      = payment.get("service") or "Appointment"
    amount       = f"${payment.get('amount_cents', 0) / 100:.2f}"
    business_name = tenant.get("business_name", "")

    # Slack
    if tenant.get("slack_webhook_url"):
        try:
            import httpx
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"💳 Deposit received — {business_name}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Customer:*\n{caller_name}"},
                    {"type": "mrkdwn", "text": f"*Phone:*\n{caller_phone}"},
                    {"type": "mrkdwn", "text": f"*Service:*\n{service}"},
                    {"type": "mrkdwn", "text": f"*Amount:*\n{amount}"},
                ]},
                {"type": "context", "elements": [
                    {"type": "mrkdwn", "text": "Appointment is now confirmed ✅"}
                ]},
            ]
            async with httpx.AsyncClient() as client:
                await client.post(tenant["slack_webhook_url"], json={"blocks": blocks}, timeout=10.0)
        except Exception as e:
            logger.error("Payment Slack notification failed for tenant %s: %s", tenant.get("id"), e)

    # Email
    notification_email = tenant.get("notification_email", "")
    if notification_email and tenant.get("email_notifications", False):
        try:
            from services.email import send_call_summary_email
            fake_analysis = {
                "caller_name": caller_name,
                "summary": f"Deposit of {amount} received for {service}. Appointment confirmed.",
                "urgency": "hot",
                "suggested_next_step": f"Prepare for {caller_name}'s {service}.",
                "key_details": {"Payment": amount, "Service": service},
            }
            await send_call_summary_email(
                to=notification_email,
                business_name=business_name,
                analysis=fake_analysis,
                caller_number=caller_phone,
            )
        except Exception as e:
            logger.error("Payment email notification failed for tenant %s: %s", tenant.get("id"), e)
