"""
Free-trial status + reminders.

Single source of truth for: is a tenant inside a trial, how long is left, is the
line allowed to take calls, and which reminder email (if any) is due.

There are TWO trial kinds, and they coexist:

  1. CARD TRIAL (current signups) — a real Stripe subscription in `trialing`
     status with a card on file and a plan chosen up front. Stripe owns the
     lifecycle; we mirror the end date into tenants.stripe_trial_ends_at.
       * 7 days, then Stripe charges the card automatically.
       * Soft-capped at CARD_TRIAL_MINUTES. Crossing the cap does NOT gate the
         line — it AUTO-CONVERTS the trial early (ends the Stripe trial, charges
         the card, starts the plan), so the line stays up and the tenant gets
         their full plan allocation. That conversion is triggered from
         services/usage.record_call_minutes; see the safety-net note below.

  2. DERIVED TRIAL (legacy, card-free) — no Stripe subscription at all. Computed
     from tenant.created_at + TRIAL_DAYS and capped at TRIAL_MINUTES. Kept for
     tenants provisioned before the card requirement shipped, and as the
     degraded fallback if subscription creation fails during provisioning.
       * Trial ends when EITHER the 7 days pass OR 30 minutes are used, and the
         line IS gated at that point (there is no card to charge).

An active paid subscription always keeps the line live regardless of either.

HOT PATH: trial_status() is called on every inbound call (routers/webhooks.py)
to decide whether the AI answers. It must stay pure and DB-only — never add a
Stripe API call, a DB query, or anything else that can block or fail here.
"""
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

TRIAL_DAYS = 7
TRIAL_MINUTES = 30

# Minutes included in a card trial before it auto-converts to the paid plan.
# Sized as a demo budget, not a free tier: enough to prove the AI works on real
# calls, bounded enough that a trial which never converts can't erode margin.
CARD_TRIAL_MINUTES = 60

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


def is_card_trial(tenant: dict) -> bool:
    """True when the tenant is inside a Stripe trial with a card on file.

    Relies on `trialing` being stored VERBATIM in subscription_status. The Stripe
    webhook used to collapse trialing -> 'active', which made card trials
    indistinguishable from paying customers (and inflated MRR); see
    routers/billing.py.
    """
    return (tenant.get("subscription_status") or "").strip().lower() == "trialing"


def _parse_dt(value) -> datetime | None:
    """Parse a DB timestamp into an aware UTC datetime. None on anything unparseable."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def _created_dt(tenant: dict) -> datetime | None:
    return _parse_dt(tenant.get("created_at"))


def _card_trial_status(tenant: dict) -> dict:
    """Status for a Stripe `trialing` subscription (card on file, plan chosen)."""
    now     = datetime.now(timezone.utc)
    ends_at = _parse_dt(tenant.get("stripe_trial_ends_at"))

    # FAIL OPEN on a missing end date. The billing webhook mirrors trial_end into
    # this column, but if that ever hasn't landed yet, Stripe is still the
    # authority and will end the trial on schedule by itself. Serving a few extra
    # calls is far cheaper than gating the line of someone who has already handed
    # us a card because of a column we failed to write.
    time_active    = (ends_at is None) or (ends_at > now)
    days_remaining = max(0, (ends_at.date() - now.date()).days) if ends_at else TRIAL_DAYS

    minutes_used      = int(tenant.get("minutes_used_this_period") or 0)
    minutes_remaining = max(0, CARD_TRIAL_MINUTES - minutes_used)
    minutes_exhausted = minutes_used >= CARD_TRIAL_MINUTES

    # SAFETY NET, not the primary mechanism. Crossing the minute cap is supposed
    # to AUTO-CONVERT the trial (services/usage.record_call_minutes ends the
    # Stripe trial early, which flips subscription_status to 'active' and resets
    # the minute counter), so in the happy path a card trial never reaches this
    # branch — it stops being a card trial first. This only bites if that
    # conversion failed outright, and it stops an unbounded free line.
    line_active = time_active and not minutes_exhausted

    return {
        "card_trial":              True,
        "plan":                    tenant.get("subscription_plan"),
        "trial_active":            line_active,
        "trial_expired":           not time_active,
        "trial_days_total":        TRIAL_DAYS,
        "trial_days_remaining":    days_remaining,
        "trial_ends_at":           ends_at.isoformat() if ends_at else None,
        "trial_minutes_total":     CARD_TRIAL_MINUTES,
        "trial_minutes_used":      minutes_used,
        "trial_minutes_remaining": minutes_remaining,
        "has_active_subscription": True,
        "line_active":             line_active,
        # They already have a card and a plan — nothing to ask for.
        "subscription_required":   False,
    }


def _derived_trial_status(tenant: dict) -> dict:
    """Status for the legacy card-free trial, derived from created_at."""
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
        "card_trial":              False,
        "plan":                    tenant.get("subscription_plan"),
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


def trial_status(tenant: dict) -> dict:
    """Compute the full trial/line status for a tenant.

    Both branches return the SAME key set, so every caller (the call gate, the
    dashboard banner, /onboarding/status) can read one shape without caring which
    kind of trial it is.

    Billing-exempt tenants are routed to the derived branch FIRST, even if they
    also carry a `trialing` subscription (e.g. a trial tenant later comped by
    hand). has_active_subscription() short-circuits them there to a permanently
    live line, whereas the card branch would apply the 60-minute cap — a comp
    must never have its line gated.
    """
    if is_card_trial(tenant) and not is_billing_exempt(tenant):
        return _card_trial_status(tenant)
    return _derived_trial_status(tenant)


def blocked_reason(tenant: dict) -> str:
    """Human-readable reason a call is blocked (for logs). Empty if the line is live."""
    ts = trial_status(tenant)
    if ts["line_active"]:
        return ""
    if ts["trial_minutes_used"] >= ts["trial_minutes_total"]:
        # On a card trial this means auto-conversion did not happen — the tenant
        # has a card on file and should have been charged. Worth alerting on.
        return "card_trial_minutes_exhausted" if ts["card_trial"] else "trial_minutes_exhausted"
    return "card_trial_days_expired" if ts["card_trial"] else "trial_days_expired"


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
        # Card trials are excluded here by has_active_subscription() (a `trialing`
        # subscription counts as active). That is deliberate — they need a
        # different sequence, one that names the amount and date of an imminent
        # CHARGE rather than an expiring free trial. See process_card_trial_reminders.
        if not email or has_active_subscription(t):
            continue
        # CASL: trial nudges are commercial messages — respect an unsubscribe.
        if t.get("marketing_unsubscribed_at"):
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
            ok = await send_trial_reminder_email(
                to=email,
                business_name=t.get("business_name") or "there",
                kind=kind,
                tenant_id=t["id"],
                days_remaining=ts["trial_days_remaining"],
            )
            # Only mark sent on success, so a transient failure retries next run.
            if ok:
                await db.update_tenant(t["id"], {flag: True})
                sent[kind] += 1
                processed += 1
        except Exception as e:
            logger.error("trial reminder send failed for tenant %s: %s", t.get("id"), e)

    logger.info("trial reminders sent: %s", sent)
    return sent
