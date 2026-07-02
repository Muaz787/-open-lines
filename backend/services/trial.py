"""
Free-trial status + reminders.

Single source of truth for: is a tenant inside its no-card trial, how long is left,
is the line allowed to take calls, and which reminder email (if any) is due.

Trial rules:
  * 7 days from tenant.created_at, no credit card required.
  * Also capped at 30 trial minutes (uses the existing minutes_used_this_period
    counter, which accrues for un-subscribed tenants too).
  * Trial ends when EITHER the 7 days pass OR 30 minutes are used.
  * An active subscription always keeps the line live regardless of trial.
"""
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

TRIAL_DAYS = 7
TRIAL_MINUTES = 30
_ACTIVE_SUB_STATUSES = {"active", "trialing", "past_due", "canceling"}

# Comp / internal accounts (e.g. the openlines.ai demo line) that should never
# expire or require a subscription. Set BILLING_EXEMPT_TENANT_IDS to a comma-
# separated list of tenant ids in the backend env. These keep the line live
# forever without touching subscription_plan, so revenue metrics stay accurate.
_BILLING_EXEMPT_IDS = {
    t.strip() for t in os.getenv("BILLING_EXEMPT_TENANT_IDS", "").split(",") if t.strip()
}


def is_billing_exempt(tenant: dict) -> bool:
    # Per-tenant DB flag (admin-controlled, instant) OR the env allow-list.
    return bool(tenant.get("billing_exempt")) or str(tenant.get("id") or "") in _BILLING_EXEMPT_IDS


def has_active_subscription(tenant: dict) -> bool:
    if is_billing_exempt(tenant):
        return True
    return (tenant.get("subscription_status") or "").strip().lower() in _ACTIVE_SUB_STATUSES


def _created_dt(tenant: dict) -> datetime | None:
    created = tenant.get("created_at")
    if not created:
        return None
    try:
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def trial_status(tenant: dict) -> dict:
    """Compute the full trial/line status for a tenant."""
    has_sub = has_active_subscription(tenant)
    created = _created_dt(tenant)
    now     = datetime.now(timezone.utc)

    ends_at    = (created + timedelta(days=TRIAL_DAYS)) if created else None
    hours_left = ((ends_at - now).total_seconds() / 3600.0) if ends_at else None

    minutes_used      = int(tenant.get("minutes_used_this_period") or 0)
    minutes_remaining = max(0, TRIAL_MINUTES - minutes_used)
    minutes_exhausted = minutes_used >= TRIAL_MINUTES

    # Display value via calendar-date diff (robust to sub-second timing):
    # 7 at provisioning, 1 = "tomorrow", 0 = "today".
    if ends_at is None:
        days_remaining = 0
    else:
        days_remaining = max(0, (ends_at.date() - now.date()).days)

    time_active   = (hours_left is not None) and (hours_left > 0)
    trial_active  = (not has_sub) and time_active and (not minutes_exhausted)
    trial_expired = (not has_sub) and (created is not None) and (not time_active or minutes_exhausted)
    line_active   = has_sub or trial_active

    return {
        "trial_active":            trial_active,
        "trial_expired":           trial_expired,
        "trial_days_total":        TRIAL_DAYS,
        "trial_days_remaining":    days_remaining if not has_sub else 0,
        "trial_ends_at":           ends_at.isoformat() if ends_at else None,
        "trial_minutes_total":     TRIAL_MINUTES,
        "trial_minutes_used":      minutes_used,
        "trial_minutes_remaining": minutes_remaining,
        "has_active_subscription": has_sub,
        "line_active":             line_active,
        "subscription_required":   (not has_sub) and (not trial_active),
    }


def blocked_reason(tenant: dict) -> str:
    """Human-readable reason a call is blocked (for logs). Empty if the line is live."""
    ts = trial_status(tenant)
    if ts["line_active"]:
        return ""
    if int(tenant.get("minutes_used_this_period") or 0) >= TRIAL_MINUTES:
        return "trial_minutes_exhausted"
    return "trial_days_expired"


async def process_trial_reminders(limit: int = 200) -> dict:
    """Send any due trial reminder emails (active / ending / ended), once each,
    deduped by per-tenant sent flags. Safe to run daily. Returns counts."""
    from db import supabase as db
    from services.email import send_trial_reminder_email

    try:
        res = (
            db.get_client().table("tenants")
            .select(
                "id, business_name, email, created_at, subscription_status, "
                "minutes_used_this_period, trial_email_day3_sent, "
                "trial_email_day6_sent, trial_email_ended_sent"
            )
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.error("trial reminders: tenant fetch failed: %s", e)
        return {"active": 0, "ending": 0, "ended": 0, "error": True}

    now  = datetime.now(timezone.utc)
    sent = {"active": 0, "ending": 0, "ended": 0}
    processed = 0

    for t in rows:
        if processed >= limit:
            break
        email = t.get("email")
        if not email or has_active_subscription(t):
            continue
        created = _created_dt(t)
        if not created:
            continue

        ts = trial_status(t)
        days_elapsed = (now - created).days

        kind = flag = None
        if ts["trial_expired"] and not t.get("trial_email_ended_sent"):
            kind, flag = "ended", "trial_email_ended_sent"
        elif ts["trial_active"] and ts["trial_days_remaining"] <= 1 and not t.get("trial_email_day6_sent"):
            kind, flag = "ending", "trial_email_day6_sent"
        elif ts["trial_active"] and days_elapsed >= 3 and not t.get("trial_email_day3_sent"):
            kind, flag = "active", "trial_email_day3_sent"

        if not kind:
            continue

        try:
            await send_trial_reminder_email(
                to=email,
                business_name=t.get("business_name") or "there",
                kind=kind,
                tenant_id=t["id"],
                days_remaining=ts["trial_days_remaining"],
            )
            await db.update_tenant(t["id"], {flag: True})
            sent[kind] += 1
            processed += 1
        except Exception as e:
            logger.error("trial reminder send failed for tenant %s: %s", t.get("id"), e)

    logger.info("trial reminders sent: %s", sent)
    return sent
