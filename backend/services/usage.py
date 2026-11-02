"""
Per-tenant call minute tracking and Stripe Meter overage reporting.

Flow per call:
  1. record_call_minutes() is called by webhook_processor after each end-of-call event
  2. Minutes are accumulated in tenants.minutes_used_this_period
  3. Once a tenant crosses their plan allocation, incremental overage minutes are
     reported to the Stripe Billing Meter (event_name: "call_minutes")
  4. Stripe automatically charges the overage amount on the next invoice
  5. Threshold alerts fire at 80% and 100% of plan allocation

Billing period resets are detected by comparing the stored billing_period_anchor
to Stripe's current_period_start. The check is skipped unless >= 28 days have
passed since the anchor to avoid an API call on every call end.
"""

import hashlib
import logging
import os
import stripe
import uuid
from datetime import date, datetime, timedelta, timezone

from db import supabase as db
from services import subscriptions, trial

logger = logging.getLogger(__name__)

PLAN_ALLOCATIONS: dict[str, int] = {
    "starter":  150,
    "pro":      400,
    "business": 900,
}
OVERAGE_RATE_CENTS = 69  # $0.69 per minute (priced above the most expensive plan's
                          # per-minute rate so overage is never cheaper than a plan)

_stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
_overage_price_id = os.getenv("STRIPE_CALL_MINUTES_PRICE_ID") or os.getenv("STRIPE_OVERAGE_PRICE_ID", "")


def _ceil_minutes(duration_secs: int) -> int:
    """Round up seconds to whole minutes (standard telecom billing).
    Casts to int first — Vapi sends float durations (e.g. 217.6) which would
    otherwise make this return a float and break the int DB column on persist."""
    secs = int(duration_secs)
    return max(1, -(-secs // 60))


def get_usage_summary(tenant: dict) -> dict:
    """Return current-period usage for a tenant dict. Does not hit the DB or Stripe."""
    plan = tenant.get("subscription_plan") or "starter"
    allocation = PLAN_ALLOCATIONS.get(plan, 150)
    minutes_used = tenant.get("minutes_used_this_period") or 0
    overage = max(0, minutes_used - allocation)
    return {
        "plan":                   plan,
        "minutes_included":       allocation,
        "minutes_used":           minutes_used,
        "minutes_remaining":      max(0, allocation - minutes_used),
        "overage_minutes":        overage,
        "overage_cost_cents":     overage * OVERAGE_RATE_CENTS,
        "usage_pct":              round(min(100.0, minutes_used / allocation * 100) if allocation else 0.0, 1),
        "billing_period_anchor":  tenant.get("billing_period_anchor"),
    }


async def check_platform_minutes_alert() -> dict:
    """Ops alert: when total platform call-minutes for the current period cross a
    threshold (default 30,000/month), email the founder — once per threshold — that
    it's time to revisit replacing Vapi with a self-hosted voice stack.

    Deduped via system_meta so it fires at most once per threshold. Automatically
    re-arms if PLATFORM_MINUTES_ALERT_THRESHOLD is later raised (e.g. 30k -> 50k).
    Set the threshold to 0 to disable. Wired into the daily cron; also runnable via
    POST /admin/check-minutes-alert. Recipient: PLATFORM_ALERT_EMAIL (or SUPPORT_EMAIL).
    """
    threshold = int(os.getenv("PLATFORM_MINUTES_ALERT_THRESHOLD", "30000"))
    if threshold <= 0:
        return {"fired": False, "reason": "disabled"}

    total = await db.sum_minutes_used_this_period()
    meta = await db.get_system_meta("platform_minutes_alert_threshold")
    last_fired = int((meta or {}).get("value") or 0)

    if total >= threshold and last_fired < threshold:
        from services.email import send_platform_minutes_alert_email
        try:
            await send_platform_minutes_alert_email(total_minutes=total, threshold=threshold)
        except Exception as e:
            logger.error("platform minutes alert email failed: %s", e)
        await db.set_system_meta("platform_minutes_alert_threshold", str(threshold))
        logger.warning(
            "PLATFORM MINUTES ALERT fired: total=%d >= threshold=%d (Vapi-migration nudge sent)",
            total, threshold,
        )
        return {"fired": True, "total_minutes": total, "threshold": threshold}

    return {"fired": False, "total_minutes": total, "threshold": threshold, "last_fired_threshold": last_fired}


def _send_usage_alert(tenant: dict, threshold_pct: int, minutes_used: int, allocation: int) -> None:
    """Log usage threshold alert. Wire to an email provider when ready."""
    logger.warning(
        "USAGE ALERT %d%%: tenant %s (%s) on %s plan — %d/%d minutes used",
        threshold_pct,
        tenant.get("id", ""),
        tenant.get("business_name", ""),
        tenant.get("subscription_plan", "starter"),
        minutes_used,
        allocation,
    )
    # TODO: send email to tenant.get("email") once an email service is wired in


# Stripe drops a repeated meter identifier for at least 24 hours. Past this age a retry
# could bill twice, so a person looks at it instead.
OVERAGE_RETRY_WINDOW = timedelta(hours=23)
OVERAGE_RETRY_AFTER  = timedelta(minutes=5)


async def _current_period_start(tenant: dict) -> str | None:
    """Stripe's current period start, when the period may have changed. Skips the Stripe
    call unless >= 28 days have passed since the stored anchor. None means unknown, and
    the rollover then sorts the call into the right period by its end time."""
    stored_anchor = str(tenant.get("billing_period_anchor") or "")
    sub_id        = tenant.get("stripe_subscription_id") or ""

    if not sub_id or not _stripe_key:
        return None

    # Only call Stripe if the anchor is old enough that a rollover could have happened
    if stored_anchor:
        try:
            anchor_date = datetime.strptime(stored_anchor, "%Y-%m-%d").date()
            if date.today() < anchor_date + timedelta(days=28):
                return None
        except ValueError:
            pass

    try:
        stripe.api_key = _stripe_key
        return subscriptions.period_start_iso(stripe.Subscription.retrieve(sub_id))
    except Exception as e:
        logger.warning("usage: period check failed for tenant %s: %s", tenant.get("id", ""), e)
        return None


def _meter_identifier(tenant_id: str, call_id: str) -> str:
    return "ol-usage-" + hashlib.sha256(f"{tenant_id}:{call_id}".encode()).hexdigest()[:40]


async def _report_overage(tenant_id: str, customer_id: str, call_id: str, minutes: int, ended_at: str) -> None:
    """Report one call's overage. Safe to repeat: Stripe drops a repeated identifier, so
    a crash between Stripe accepting this and the write below can be retried."""
    stripe.api_key = _stripe_key
    try:
        stripe.billing.MeterEvent.create(
            event_name="call_minutes",
            identifier=_meter_identifier(tenant_id, call_id),
            timestamp=int(datetime.fromisoformat(ended_at.replace("Z", "+00:00")).timestamp()),
            payload={"value": str(minutes), "stripe_customer_id": customer_id},
        )
    except stripe.InvalidRequestError as e:
        # Stripe gives this no error code. It means Stripe already has this event, which
        # is what a retry after a crash expects. Any other 400 stays pending.
        if "already exists with identifier" not in str(e):
            raise
    await db.usage_overage_reported(tenant_id, call_id)
    logger.info("Reported %d overage minutes to Stripe for tenant %s", minutes, tenant_id)


async def retry_pending_overage() -> dict:
    """Finish overage a crash or Stripe outage left unreported. Runs from the webhook
    processor's loop every few minutes, so a row reaches this long before it's too old."""
    result = {"reported": 0, "failed": 0, "review": 0}
    now = datetime.now(timezone.utc)
    for event in await db.usage_pending_overage():
        created = datetime.fromisoformat(str(event["created_at"]).replace("Z", "+00:00"))
        if now - created < OVERAGE_RETRY_AFTER:
            continue
        tenant_id, call_id = event["tenant_id"], event["call_id"]
        if now - created > OVERAGE_RETRY_WINDOW:
            await db.usage_overage_needs_review(tenant_id, call_id)
            logger.error("Overage for tenant %s call %s is too old to retry safely", tenant_id, call_id)
            result["review"] += 1
            continue
        try:
            tenant = await db.get_tenant_by_id(tenant_id)
            await _report_overage(tenant_id, tenant.get("stripe_customer_id") or "", call_id,
                                  event["overage_minutes"], str(event["ended_at"]))
            result["reported"] += 1
        except Exception as e:
            logger.error("Overage retry failed for tenant %s call %s: %s", tenant_id, call_id, e)
            result["failed"] += 1
    return result


async def record_call_minutes(tenant_id: str, duration_secs: int, call_id: str = "",
                              ended_at: str | None = None) -> None:
    """Record a call for a tenant and report any new overage to Stripe. The call belongs
    to the billing period containing ended_at, however late this runs. A retry with the
    same call_id changes nothing."""
    if duration_secs <= 0:
        return
    call_id  = call_id or f"no-call-id-{uuid.uuid4()}"
    ended_at = ended_at or datetime.now(timezone.utc).isoformat()

    minutes = _ceil_minutes(duration_secs)

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if not tenant:
            logger.error("usage.record_call_minutes: tenant %s not found", tenant_id)
            return
    except Exception as e:
        logger.error("usage.record_call_minutes: DB error for %s: %s", tenant_id, e)
        return

    plan       = tenant.get("subscription_plan") or "starter"
    allocation = PLAN_ALLOCATIONS.get(plan, 150)
    customer_id = tenant.get("stripe_customer_id") or ""
    metered = bool(customer_id and tenant.get("stripe_subscription_id") and _stripe_key and _overage_price_id)

    period_start = await _current_period_start(tenant)

    # One locked step in the database, so concurrent calls and the rollover webhook
    # can't overwrite each other.
    try:
        row = await db.usage_record_call(tenant_id, call_id, int(minutes), ended_at, period_start,
                                         allocation if metered else None)
    except Exception as e:
        logger.error("Failed to persist usage for tenant %s: %s", tenant_id, e)
        return
    if not row:
        logger.error("usage.record_call_minutes: tenant %s not found", tenant_id)
        return
    if row["duplicate"]:
        logger.info("Usage for call %s already recorded", call_id)
        return
    if not row["counted"]:
        logger.warning("Call %s ended before tenant %s's current period; not counted against it", call_id, tenant_id)
        return

    new_total    = row["minutes_used"]
    minutes_used = new_total - minutes

    # Threshold alerts
    prev_pct = minutes_used / allocation if allocation else 0
    new_pct  = new_total  / allocation if allocation else 0
    if prev_pct < 0.8 <= new_pct:
        _send_usage_alert(tenant, 80, new_total, allocation)
    elif prev_pct < 1.0 <= new_pct:
        _send_usage_alert(tenant, 100, new_total, allocation)

    # Left pending on failure. retry_pending_overage picks it up with the same identifier.
    if row["overage_minutes"] > 0:
        try:
            await _report_overage(tenant_id, customer_id, call_id, row["overage_minutes"], ended_at)
        except Exception as e:
            logger.error("Stripe meter event failed for tenant %s: %s", tenant_id, e)

    # Auto-convert a card trial that has just used up its trial minutes: charge the
    # card and start the plan the tenant already picked, rather than cutting their
    # line off mid-business-day. See services/trial.convert_card_trial.
    #
    # ORDER MATTERS — this runs AFTER the usage write above. Conversion resets
    # minutes_used_this_period to 0 so the paid period starts clean, and doing it
    # first would let the write above immediately restore the trial's 60 minutes
    # into the customer's fresh, paid allocation.
    if new_total >= trial.CARD_TRIAL_MINUTES and trial.is_card_trial(tenant) \
            and not tenant.get("trial_converted_reason"):
        try:
            await trial.convert_card_trial(tenant, reason="minutes")
        except Exception as e:
            # convert_card_trial swallows its own errors; this is belt-and-braces
            # so a surprise can never lose a recorded call.
            logger.error("Auto-conversion raised for tenant %s: %s", tenant_id, e)
