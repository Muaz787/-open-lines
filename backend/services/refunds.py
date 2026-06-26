"""
Shared deposit-refund + cancellation helpers used by both the caller-initiated
cancel tool (routers/tools.py) and the provider webhook backstop
(routers/payments.py): provider refund-API dispatch, caller SMS, business notify.

Kept in services/ (not a router) so tools.py can import it without a circular
dependency on the payments router.
"""
import logging
from datetime import datetime, timezone

from services import telephony
from services.short_links import format_currency

logger = logging.getLogger(__name__)


def _amount_display(amount_cents: int) -> str:
    return f"{amount_cents // 100}" if amount_cents % 100 == 0 else f"{amount_cents / 100:.2f}"


def refund_eligible(appt_dt_utc: datetime | None, refund_hours: int, now: datetime | None = None) -> bool:
    """Full deposit refund is owed when the appointment is at least
    `refund_hours` away. refund_hours=0 → always eligible (future appt)."""
    if appt_dt_utc is None:
        return False
    now = now or datetime.now(timezone.utc)
    hours_until = (appt_dt_utc - now).total_seconds() / 3600.0
    return hours_until >= refund_hours


async def issue_provider_refund(payment: dict, tenant: dict) -> bool:
    """Issue a full refund through the payment's provider. Returns True on
    success (or successful initiation, for async Square refunds)."""
    provider = payment.get("provider") or "stripe"
    amount_cents = int(payment.get("amount_cents") or 0)
    currency     = payment.get("currency") or "usd"

    try:
        if provider == "square":
            from services import square_service as sq_svc
            from services.security import decrypt
            access_token = decrypt(tenant["square_access_token"])
            square_payment_id = payment.get("payment_intent_id") or ""
            if not square_payment_id:
                logger.error("Refund: missing Square payment id for payment %s", payment.get("id"))
                return False
            await sq_svc.refund_payment(
                access_token=access_token,
                square_payment_id=square_payment_id,
                amount_cents=amount_cents,
                currency=currency,
            )
        else:
            from services import stripe_service as stripe_svc
            stripe_account_id = payment.get("stripe_account_id") or tenant.get("stripe_account_id") or ""
            payment_intent_id = payment.get("payment_intent_id") or ""
            if not (stripe_account_id and payment_intent_id):
                logger.error("Refund: missing Stripe ids for payment %s", payment.get("id"))
                return False
            await stripe_svc.refund_payment(
                stripe_account_id=stripe_account_id,
                payment_intent_id=payment_intent_id,
            )
        logger.info("Refund issued via %s for payment %s", provider, payment.get("id"))
        return True
    except Exception as e:
        logger.error("Refund: provider API call failed for payment %s: %s", payment.get("id"), e)
        return False


async def sms_caller_refund(tenant: dict, payment: dict, appointment: dict | None = None) -> None:
    """Tell the caller their deposit was refunded and the appointment cancelled."""
    caller_phone  = payment.get("caller_phone", "")
    caller_name   = payment.get("caller_name", "") or "there"
    service       = payment.get("service") or "appointment"
    business_name = tenant.get("business_name", "us")
    sid    = tenant.get("twilio_subaccount_sid", "")
    tok    = tenant.get("twilio_auth_token", "")
    from_n = tenant.get("twilio_phone_number", "")
    if not (sid and tok and from_n and caller_phone):
        return

    currency       = format_currency(payment.get("currency", "usd"))
    amount_display = _amount_display(int(payment.get("amount_cents") or 0))
    sms_body = (
        f"Hi {caller_name}! Your {currency} {amount_display} deposit for your {service} at "
        f"{business_name} has been refunded, and your appointment has been cancelled. "
        f"Please contact us if you'd like to rebook. — {business_name}"
    )
    await _send(tenant, caller_phone, sms_body, "refund")


async def sms_caller_cancelled(
    tenant: dict,
    caller_phone: str,
    caller_name: str,
    service: str,
    deposit_forfeited: bool = False,
    amount_cents: int = 0,
    currency: str = "usd",
    refund_hours: int = 0,
) -> None:
    """Cancellation SMS when no refund is issued — either no deposit was taken,
    or the cancellation fell inside the non-refundable window."""
    business_name = tenant.get("business_name", "us")
    caller_name = caller_name or "there"
    service = service or "appointment"
    sid    = tenant.get("twilio_subaccount_sid", "")
    tok    = tenant.get("twilio_auth_token", "")
    from_n = tenant.get("twilio_phone_number", "")
    if not (sid and tok and from_n and caller_phone):
        return

    if deposit_forfeited:
        cur = format_currency(currency)
        amt = _amount_display(amount_cents)
        body = (
            f"Hi {caller_name}! Your {service} at {business_name} has been cancelled. "
            f"As it was cancelled within {refund_hours} hours of the appointment, the "
            f"{cur} {amt} deposit is non-refundable per our cancellation policy. — {business_name}"
        )
    else:
        body = (
            f"Hi {caller_name}! Your {service} at {business_name} has been cancelled. "
            f"Please contact us if you'd like to rebook. — {business_name}"
        )
    await _send(tenant, caller_phone, body, "cancellation")


async def _send(tenant: dict, to_number: str, body: str, label: str) -> None:
    try:
        await telephony.send_sms(
            subaccount_sid=tenant.get("twilio_subaccount_sid", ""),
            subaccount_token=tenant.get("twilio_auth_token", ""),
            from_number=tenant.get("twilio_phone_number", ""),
            to_number=to_number,
            body=body,
        )
        logger.info("Caller %s SMS sent to %s for tenant %s", label, to_number, tenant.get("id"))
    except Exception as e:
        logger.error("Caller %s SMS failed for tenant %s: %s", label, tenant.get("id"), e)


async def notify_business(tenant: dict, payment: dict | None, *, refunded: bool, service: str = "", caller_name: str = "", caller_phone: str = "") -> None:
    """Slack/email notification that an appointment was cancelled (and whether
    the deposit was refunded or forfeited)."""
    if payment:
        caller_name  = caller_name or payment.get("caller_name") or "Customer"
        caller_phone = caller_phone or payment.get("caller_phone") or ""
        service      = service or payment.get("service") or "Appointment"
        amount       = f"${(payment.get('amount_cents') or 0) / 100:.2f}"
    else:
        caller_name  = caller_name or "Customer"
        service      = service or "Appointment"
        amount       = None
    business_name = tenant.get("business_name", "")

    if refunded:
        header  = f"💸 Deposit refunded — {business_name}"
        context = "Appointment has been cancelled ❌"
    elif amount is not None:
        header  = f"❌ Appointment cancelled (deposit kept) — {business_name}"
        context = "Cancelled inside the refund window — deposit forfeited"
    else:
        header  = f"❌ Appointment cancelled — {business_name}"
        context = "No deposit was on file"

    # Slack
    if tenant.get("slack_webhook_url"):
        try:
            import httpx
            fields = [
                {"type": "mrkdwn", "text": f"*Customer:*\n{caller_name}"},
                {"type": "mrkdwn", "text": f"*Phone:*\n{caller_phone}"},
                {"type": "mrkdwn", "text": f"*Service:*\n{service}"},
            ]
            if amount is not None:
                fields.append({"type": "mrkdwn", "text": f"*Deposit:*\n{amount}"})
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": header}},
                {"type": "section", "fields": fields},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
            ]
            async with httpx.AsyncClient() as client:
                await client.post(tenant["slack_webhook_url"], json={"blocks": blocks}, timeout=10.0)
        except Exception as e:
            logger.error("Cancellation Slack notification failed for tenant %s: %s", tenant.get("id"), e)

    # Email
    notification_email = tenant.get("notification_email", "")
    if notification_email and tenant.get("email_enabled", True):
        try:
            from services.email import send_call_summary_email
            summary = (
                f"Appointment for {service} was cancelled. "
                + (f"Deposit of {amount} refunded." if refunded
                   else (f"Deposit of {amount} forfeited (cancelled inside the refund window)." if amount is not None
                         else "No deposit was on file."))
            )
            fake_analysis = {
                "caller_name": caller_name,
                "summary": summary,
                "urgency": "warm",
                "suggested_next_step": f"Follow up with {caller_name} if a rebooking is expected.",
                "key_details": {"Service": service, **({"Deposit": amount} if amount is not None else {})},
            }
            await send_call_summary_email(
                to=notification_email,
                business_name=business_name,
                analysis=fake_analysis,
                caller_number=caller_phone,
            )
        except Exception as e:
            logger.error("Cancellation email notification failed for tenant %s: %s", tenant.get("id"), e)
