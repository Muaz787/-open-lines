import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services import stripe_service as svc, vapi, telephony
from services.webhook_processor import _format_whatsapp_message
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

_ELIGIBLE_PLANS   = {"pro", "business"}
_ELIGIBLE_STATUSES = {"active", "trialing", "canceling"}


_COUNTRY_CURRENCY: dict[str, str] = {
    "US": "usd", "CA": "cad", "AU": "aud", "GB": "gbp",
    "NZ": "nzd", "IE": "eur", "AE": "aed", "SG": "sgd",
}

def _currency_for(tenant: dict) -> str:
    country = (tenant.get("country") or "CA").upper()
    return _COUNTRY_CURRENCY.get(country, "usd")


def _is_eligible(tenant: dict) -> bool:
    plan   = (tenant.get("subscription_plan") or "").lower()
    status = tenant.get("subscription_status") or ""
    return plan in _ELIGIBLE_PLANS and status in _ELIGIBLE_STATUSES


def _effective_currency(tenant: dict) -> str:
    """Return the currency that will actually be used for deposit payments.
    When Square is the active provider, use the Square account's currency
    (Square requires payment links to match the merchant account currency).
    Otherwise derive from tenant country."""
    provider = _deposit_provider(tenant)
    if provider == "square" and tenant.get("square_currency"):
        return tenant["square_currency"].upper()
    return _currency_for(tenant).upper()


def _deposit_provider(tenant: dict) -> str:
    """Return the active deposit provider: 'square', 'stripe', or ''.
    Square takes priority when both are enabled."""
    if tenant.get("square_deposits_enabled") and tenant.get("square_access_token"):
        return "square"
    if tenant.get("stripe_deposits_enabled") and tenant.get("stripe_account_id"):
        return "stripe"
    return ""


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
        "eligible":                _is_eligible(tenant),
        "stripe_connected":        bool(tenant.get("stripe_account_id")),
        "deposits_enabled":        bool(tenant.get("stripe_deposits_enabled")),
        "square_connected":        bool(tenant.get("square_access_token")),
        "square_deposits_enabled": bool(tenant.get("square_deposits_enabled")),
        "square_merchant_id":      tenant.get("square_merchant_id"),
        "square_currency":         (tenant.get("square_currency") or "").upper(),
        "deposit_cents":           int(tenant.get("stripe_deposit_cents") or 2500),
        "deposit_mandatory":       bool(tenant.get("stripe_deposit_mandatory", True)),
        "deposit_expiry_min":      int(tenant.get("stripe_deposit_expiry_min") or 120),
        "deposit_label":           tenant.get("stripe_deposit_label") or "Appointment Deposit",
        "currency":                _effective_currency(tenant),
        "active_provider":         _deposit_provider(tenant) or None,
    }


# ---------------------------------------------------------------------------
# POST /payments/settings/{tenant_id}
# ---------------------------------------------------------------------------

class DepositSettingsRequest(BaseModel):
    deposits_enabled:        bool
    square_deposits_enabled: bool = False
    deposit_cents:           int
    deposit_mandatory:       bool
    deposit_expiry_min:      int
    deposit_label:           str | None = None


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

    if not tenant.get("square_access_token") and body.square_deposits_enabled:
        raise HTTPException(
            status_code=400,
            detail="Connect your Square account before enabling Square deposits",
        )

    update = {
        "stripe_deposits_enabled":  body.deposits_enabled,
        "square_deposits_enabled":  body.square_deposits_enabled,
        "stripe_deposit_cents":     body.deposit_cents,
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
    appointment = None
    if payment.get("appointment_id"):
        try:
            await db.update_appointment(payment["appointment_id"], {"status": "confirmed"})
            logger.info("Appointment %s confirmed after payment", payment["appointment_id"])
            appointment = await db.get_appointment_by_id(payment["appointment_id"])
        except Exception as e:
            logger.error("Failed to confirm appointment %s: %s", payment["appointment_id"], e)

    # Notify the business owner and send caller confirmation SMS
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if tenant:
            await _notify_payment(tenant, payment)
            await _sms_caller_confirmation(tenant, payment, appointment)
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


async def _sms_caller_confirmation(tenant: dict, payment: dict, appointment: dict | None) -> None:
    """Send the caller an appointment confirmation SMS after their deposit clears."""
    caller_phone = payment.get("caller_phone", "")
    caller_name  = payment.get("caller_name", "") or "there"
    service      = payment.get("service") or "appointment"
    business_name = tenant.get("business_name", "us")
    sid   = tenant.get("twilio_subaccount_sid", "")
    tok   = tenant.get("twilio_auth_token", "")
    from_n = tenant.get("twilio_phone_number", "")

    if not (sid and tok and from_n and caller_phone):
        return

    friendly = ""
    if appointment:
        try:
            tz_str  = tenant.get("calendar_timezone") or "America/Toronto"
            appt_dt = datetime.fromisoformat(appointment["appointment_datetime"])
            if appt_dt.tzinfo is None:
                appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
            appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
            h = appt_dt.hour % 12 or 12
            ampm = "AM" if appt_dt.hour < 12 else "PM"
            friendly = f" for {appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
        except Exception:
            pass

    sms_body = (
        f"Hi {caller_name}! Your deposit was received — your {service} at {business_name}"
        f"{friendly} is now confirmed. See you then! — {business_name}"
    )
    try:
        await telephony.send_sms(
            subaccount_sid=sid,
            subaccount_token=tok,
            from_number=from_n,
            to_number=caller_phone,
            body=sms_body,
        )
        logger.info("Caller confirmation SMS sent to %s after payment for tenant %s", caller_phone, tenant.get("id"))
    except Exception as e:
        logger.error("Caller confirmation SMS failed for tenant %s: %s", tenant.get("id"), e)


# ---------------------------------------------------------------------------
# POST /payments/square-webhook  (Square webhook — raw body required)
# ---------------------------------------------------------------------------

@router.post("/square-webhook")
async def square_webhook(request: Request):
    payload    = await request.body()
    sig_header = request.headers.get("x-square-hmacsha256-signature", "")

    from services import square_service as sq_svc
    if not sq_svc.SQUARE_WEBHOOK_SIGNATURE_KEY:
        logger.warning("SQUARE_WEBHOOK_SIGNATURE_KEY not set — refusing Square webhook")
        raise HTTPException(status_code=400, detail="Square webhook not configured")

    notification_url = f"{sq_svc.APP_BACKEND_URL}/payments/square-webhook"
    try:
        if not sq_svc.verify_webhook(payload, sig_header, notification_url):
            logger.warning("Square webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid signature")
    except RuntimeError as e:
        logger.error("Square webhook verification error: %s", e)
        raise HTTPException(status_code=400, detail="Verification error")

    try:
        event = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    event_id   = event.get("event_id", "")

    try:
        match event_type:
            case "payment.updated" | "payment.created":
                await _handle_square_payment_completed(event)
    except Exception as e:
        logger.error("Square webhook processing failed for event %s: %s", event_id, e)
        raise HTTPException(status_code=500, detail="Processing failed")

    return {"status": "ok"}


async def _handle_square_payment_completed(event: dict) -> None:
    payment_obj   = (event.get("data", {}).get("object", {}).get("payment", {}))
    square_status = payment_obj.get("status", "")
    if square_status != "COMPLETED":
        return  # ignore created/pending/failed updates

    # A refund fires payment.updated with status still COMPLETED but
    # refunded_money populated — never treat that as a new deposit.
    if payment_obj.get("refunded_money") or payment_obj.get("refund_ids"):
        logger.info("Square payment.updated is a refund — skipping confirmation")
        return

    order_id      = payment_obj.get("order_id", "")
    square_pay_id = payment_obj.get("id", "")

    if not order_id:
        logger.warning("square payment.completed missing order_id")
        return

    payment = await db.get_payment_by_checkout_session(order_id)
    if not payment:
        logger.warning("No payment record found for Square order_id %s", order_id)
        return

    # Idempotency: Square sends multiple payment.updated events for the
    # same payment. Only process the first transition to succeeded so we
    # never re-send the confirmation SMS.
    if payment.get("status") == "succeeded":
        logger.info("Square payment %s already processed — skipping duplicate webhook", payment["id"])
        return

    tenant_id = payment.get("tenant_id", "")
    paid_at   = datetime.now(timezone.utc).isoformat()
    await db.update_payment(payment["id"], {
        "status":           "succeeded",
        "paid_at":          paid_at,
        "payment_intent_id": square_pay_id,
    })
    logger.info("Square payment %s succeeded for tenant %s", payment["id"], tenant_id)

    appointment = None
    if payment.get("appointment_id"):
        try:
            await db.update_appointment(payment["appointment_id"], {"status": "confirmed"})
            logger.info("Appointment %s confirmed after Square payment", payment["appointment_id"])
            appointment = await db.get_appointment_by_id(payment["appointment_id"])
        except Exception as e:
            logger.error("Failed to confirm appointment %s: %s", payment["appointment_id"], e)

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if tenant:
            await _notify_payment(tenant, payment)
            await _sms_caller_confirmation(tenant, payment, appointment)
    except Exception as e:
        logger.error("Square payment notification failed for tenant %s: %s", tenant_id, e)


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
