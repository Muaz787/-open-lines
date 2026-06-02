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

import logging
import os
import stripe
from datetime import date, datetime, timedelta, timezone

from db import supabase as db

logger = logging.getLogger(__name__)

PLAN_ALLOCATIONS: dict[str, int] = {
    "starter":  150,
    "pro":      400,
    "business": 900,
}
OVERAGE_RATE_CENTS = 35  # $0.35 per minute

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


async def _check_and_reset_period(tenant: dict) -> tuple[int, int, str]:
    """
    Return (minutes_used, overage_reported, anchor) after resetting counters
    if the Stripe billing period has rolled over. Skips the Stripe API call
    unless >= 28 days have passed since the stored anchor.
    """
    minutes_used     = tenant.get("minutes_used_this_period") or 0
    overage_reported = tenant.get("overage_minutes_reported") or 0
    stored_anchor    = str(tenant.get("billing_period_anchor") or "")
    tenant_id        = tenant.get("id", "")
    sub_id           = tenant.get("stripe_subscription_id") or ""

    if not sub_id or not _stripe_key:
        return minutes_used, overage_reported, stored_anchor

    # Only call Stripe if the anchor is old enough that a rollover could have happened
    if stored_anchor:
        try:
            anchor_date = datetime.strptime(stored_anchor, "%Y-%m-%d").date()
            if date.today() < anchor_date + timedelta(days=28):
                return minutes_used, overage_reported, stored_anchor
        except ValueError:
            pass

    try:
        stripe.api_key = _stripe_key
        sub = stripe.Subscription.retrieve(sub_id)
        new_anchor = datetime.fromtimestamp(
            int(sub.current_period_start), tz=timezone.utc
        ).strftime("%Y-%m-%d")

        if stored_anchor and stored_anchor != new_anchor:
            minutes_used     = 0
            overage_reported = 0
            await db.update_tenant(tenant_id, {
                "minutes_used_this_period": 0,
                "overage_minutes_reported": 0,
                "billing_period_anchor":    new_anchor,
            })
            logger.info("Billing period reset for tenant %s → %s", tenant_id, new_anchor)

        return minutes_used, overage_reported, new_anchor

    except Exception as e:
        logger.warning("usage: period check failed for tenant %s: %s", tenant_id, e)
        return minutes_used, overage_reported, stored_anchor


async def record_call_minutes(tenant_id: str, duration_secs: int) -> None:
    """Record call duration for a tenant and report any new overage to Stripe."""
    if duration_secs <= 0:
        return

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

    minutes_used, overage_reported, anchor = await _check_and_reset_period(tenant)

    new_total = minutes_used + minutes

    # Threshold alerts
    prev_pct = minutes_used / allocation if allocation else 0
    new_pct  = new_total  / allocation if allocation else 0
    if prev_pct < 0.8 <= new_pct:
        _send_usage_alert(tenant, 80, new_total, allocation)
    elif prev_pct < 1.0 <= new_pct:
        _send_usage_alert(tenant, 100, new_total, allocation)

    # Incremental overage reporting to Stripe
    overage_total  = max(0, new_total - allocation)
    new_overage    = max(0, overage_total - overage_reported)

    if new_overage > 0 and customer_id and _stripe_key and _overage_price_id:
        try:
            stripe.api_key = _stripe_key
            stripe.billing.MeterEvent.create(
                event_name="call_minutes",
                payload={
                    "value":              str(new_overage),
                    "stripe_customer_id": customer_id,
                },
            )
            overage_reported += new_overage
            logger.info(
                "Reported %d overage minutes to Stripe for tenant %s (period total: %d)",
                new_overage, tenant_id, overage_reported,
            )
        except Exception as e:
            logger.error("Stripe meter event failed for tenant %s: %s", tenant_id, e)

    # Persist usage counters — cast to int (int column; never persist a float)
    try:
        updates: dict = {
            "minutes_used_this_period": int(new_total),
            "overage_minutes_reported": int(overage_reported),
        }
        # Initialise anchor on first call if not yet set
        if not anchor and customer_id and _stripe_key:
            sub_id = tenant.get("stripe_subscription_id") or ""
            if sub_id:
                try:
                    stripe.api_key = _stripe_key
                    sub = stripe.Subscription.retrieve(sub_id)
                    updates["billing_period_anchor"] = datetime.fromtimestamp(
                        int(sub.current_period_start), tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except Exception:
                    pass
        await db.update_tenant(tenant_id, updates)
    except Exception as e:
        logger.error("Failed to persist usage for tenant %s: %s", tenant_id, e)
