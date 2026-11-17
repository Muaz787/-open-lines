"""
Release a Square Appointments booking whose mandatory deposit wasn't paid in time.

Decided by Muaz on 2026-11-16: when a mandatory deposit isn't paid within the
link window (stripe_deposit_expiry_min, default 120 minutes), cancel the booking
in Square and text the caller. Square Appointments bookings only, for now.

Square payment links have no expiry of their own; ours was only a date in our
table, so a caller could still pay a link hours or days later. The order of
steps makes sure nobody pays for a slot that has already been given away:

  1. take global ownership of the appointment (nobody else may move or cancel it);
  2. re-read it: still pending_payment, still ours, and no deposit paid;
  3. Square deposits: the order shows nothing paid, then the link is DELETED
     (Square cancels the order), then the order is read again and still shows
     nothing paid. After that point the link can't be paid at all;
     Stripe deposits: only once Stripe itself reported the session expired;
  4. mark the payment expired, cancel the booking at Square, mark the appointment
     cancelled, and text the caller and the owner.

Anything uncertain stops the attempt, releases ownership and is retried on the
next pass. A cancel whose outcome is unknown goes to cancellation
reconciliation, as a caller's cancel would. Nothing is ever charged or refunded.

Kill switch: DEPOSIT_HOLD_EXPIRY=off on the web service.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

GRACE = timedelta(minutes=2)       # let a just-in-time payment webhook land first
LOOKBACK = timedelta(days=7)       # older lapsed links are left to the team
_OFF = ("off", "0", "false", "no")

RELEASED = "released"
SKIPPED = "skipped"


def enabled() -> bool:
    return os.getenv("DEPOSIT_HOLD_EXPIRY", "on").strip().lower() not in _OFF


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def run_once(limit: int = 100) -> dict:
    """One sweep. Returns {"released": n, "skipped": n}."""
    out = {RELEASED: 0, SKIPPED: 0}
    if not enabled():
        return out
    from db import supabase as db
    now = _now()
    try:
        rows = await db.list_lapsed_deposits((now - GRACE).isoformat(), (now - LOOKBACK).isoformat(), limit)
    except Exception as e:
        logger.error("deposit_expiry: listing failed: %s", e)
        return out
    for payment in rows:
        try:
            result = await release_if_lapsed(payment)
        except Exception as e:
            logger.error("deposit_expiry: payment %s raised: %s", payment.get("id"), e)
            result = SKIPPED
        out[RELEASED if result == RELEASED else SKIPPED] += 1
    if out[RELEASED]:
        logger.info("deposit_expiry: %s", out)
    return out


async def release_if_lapsed(payment: dict) -> str:
    from db import supabase as db
    from services import mutation_ownership

    appointment_id = str(payment.get("appointment_id") or "")
    tenant_id = str(payment.get("tenant_id") or "")
    if not (appointment_id and tenant_id):
        return SKIPPED
    tenant = await db.get_tenant_by_id(tenant_id) or {}
    if not tenant.get("square_appointments_enabled"):
        return SKIPPED
    appt = await db.get_appointment_by_id(appointment_id) or {}
    if not _holdable(appt, tenant_id):
        return SKIPPED

    own, claim = await mutation_ownership.acquire_for_cancel(appointment_id, tenant_id)
    if own != mutation_ownership.ACQUIRED or claim is None:
        return SKIPPED          # being moved, cancelled or confirmed right now; next pass

    async def give_up(why: str) -> str:
        logger.info("deposit_expiry: not releasing %s (%s)", appointment_id, why)
        await mutation_ownership.release(claim)
        return SKIPPED

    appt = await db.get_appointment_by_id(appointment_id) or {}
    if not _holdable(appt, tenant_id):
        return await give_up("no longer held")
    if await db.get_payment_by_appointment_id(appointment_id):
        return await give_up("a deposit is paid")

    provider = (payment.get("provider") or "stripe").lower()
    if provider == "square":
        why = await _close_square_link(tenant, payment)
        if why:
            return await give_up(why)
    elif (payment.get("status") or "") != "expired":
        return await give_up("Stripe hasn't expired the checkout yet")

    # Last look under ownership: the payment webhook may have landed meanwhile.
    appt = await db.get_appointment_by_id(appointment_id) or {}
    if not _holdable(appt, tenant_id) or await db.get_payment_by_appointment_id(appointment_id):
        return await give_up("paid or changed while closing the link")

    await db.update_payment(payment["id"], {"status": "expired"})
    return await _cancel(tenant, appt, claim)


def _holdable(appt: dict, tenant_id: str) -> bool:
    return bool(appt and str(appt.get("tenant_id")) == tenant_id
                and (appt.get("status") or "") == "pending_payment"
                and appt.get("google_event_id"))


async def _close_square_link(tenant: dict, payment: dict) -> str:
    """'' when the link is gone and nothing was paid; otherwise why not."""
    from services import square_service as sq
    from services.security import decrypt
    try:
        token = decrypt(tenant["square_access_token"])
    except Exception:
        return "no Square token"
    order_id = str(payment.get("checkout_session_id") or "")
    if await sq.order_payment_state(token, order_id) != sq.ORDER_UNPAID:
        return "order paid or unreadable"
    if await sq.delete_payment_link(token, str(payment.get("payment_intent_id") or "")) == sq.LINK_FAILED:
        return "link not deleted"
    state = await sq.order_payment_state(token, order_id)
    if state == sq.ORDER_PAID:
        logger.error("deposit_expiry: payment %s was PAID as its link was closed; keeping "
                     "the booking", payment.get("id"))
        return "paid as the link closed"
    if state != sq.ORDER_UNPAID:
        return "order unreadable after closing the link"
    return ""


async def _cancel(tenant: dict, appt: dict, claim) -> str:
    from db import mutation_claims as db_mc
    from db import supabase as db
    from services import appointment_cancellation as ac, mutation_ownership

    tenant_id = str(appt["tenant_id"])
    outcome = await ac.cancel_at_provider(tenant, appt, tenant_id)
    if outcome == ac.UNKNOWN:
        await mutation_ownership.to_reconcile(claim, db_mc.REASON_PROVIDER_UNKNOWN)
        return SKIPPED
    if outcome != ac.OK:
        logger.error("deposit_expiry: Square refused to cancel %s (%s); left for the team",
                     appt["id"], outcome)
        await mutation_ownership.release(claim)
        return SKIPPED
    try:
        await db.update_appointment(appt["id"], {"status": "cancelled"})
        await mutation_ownership.release(claim)
    except Exception as e:
        await mutation_ownership.to_reconcile(claim, db_mc.REASON_LOCAL_WRITE_FAILED)
        logger.error("deposit_expiry: cancelled %s at Square but not locally: %s", appt["id"], e)
        return RELEASED
    logger.info("deposit_expiry: released unpaid hold %s (tenant %s)", appt["id"], tenant_id)
    await _tell_people(tenant, appt)
    return RELEASED


def _when(tenant: dict, appt: dict) -> str:
    from services import relative_dates
    try:
        dt = datetime.fromisoformat(str(appt["appointment_datetime"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(relative_dates.tenant_tz(tenant))
        h = dt.hour % 12 or 12
        return f"{dt.strftime('%A, %B')} {dt.day} at {h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except Exception:
        return "your appointment time"


async def _tell_people(tenant: dict, appt: dict) -> None:
    business = tenant.get("business_name") or "us"
    service = (appt.get("service") or "appointment").split(" — ")[0]
    when = _when(tenant, appt)
    name = appt.get("caller_name") or ""
    try:
        from services import telephony
        sid, tok, frm = (tenant.get("twilio_subaccount_sid", ""), tenant.get("twilio_auth_token", ""),
                         tenant.get("twilio_phone_number", ""))
        if sid and tok and frm and appt.get("caller_phone"):
            await telephony.send_sms(
                subaccount_sid=sid, subaccount_token=tok, from_number=frm,
                to_number=appt["caller_phone"],
                body=(f"{'Hi ' + name + '! ' if name else ''}We didn't receive the deposit for your "
                      f"{service} on {when}, so the time has been released. Call us anytime to "
                      f"book again. — {business}"))
    except Exception as e:
        logger.error("deposit_expiry: caller SMS failed for %s: %s", appt.get("id"), e)
    try:
        from services import telephony
        from services.owner_notify import send_owner_sms_whatsapp
        from services.refunds import _one_line
        who = f"{name} ({appt.get('caller_phone')})" if name else (appt.get("caller_phone") or "a caller")
        caller_line = " • ".join(p for p in (name, appt.get("caller_phone") or "") if p) or "A caller"
        # WhatsApp reuses the already-approved cancellation template ("Appointment
        # cancelled — {{1}} / {{2}} / Service: {{3}} / {{4}}"): a released hold IS a
        # cancellation, and a new template would need its own Meta approval.
        await send_owner_sms_whatsapp(
            tenant, sms_body=(f"⏱ Unpaid hold released — {who}, {service} on {when}. The deposit "
                              f"wasn't paid in time, so it was cancelled in Square. — {business}"),
            wa_template_sid=telephony.TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID,
            wa_vars={
                "1": _one_line(business, 60),
                "2": _one_line(caller_line, 90),
                "3": _one_line(f"{service} on {when}", 90),
                "4": _one_line("Deposit wasn't paid in time, so the hold was released "
                               "and cancelled in Square.", 120),
            },
            event="deposit_hold_released")
    except Exception as e:
        logger.error("deposit_expiry: owner alert failed for %s: %s", appt.get("id"), e)
