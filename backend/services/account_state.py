"""One description of a tenant's plan and how they came to have it.

Three facts that are easy to run together and must stay separate:

  * phone line: is there a number, and may it take calls?
  * features: which plan's features are in force?
  * subscription: how is the plan paid for?

An admin can give a tenant paid-tier features with no Stripe subscription, a comped
tenant has a live line with neither, and a tenant can have a working line while
billing is unverified. Every dashboard surface reads this, so none of them has to
infer one fact from another.

Pure and built from the tenant row: no Stripe call. Whether Stripe agrees is
reported separately by /billing/subscription-details.
"""
from datetime import datetime, timezone

from services import trial

SUBSCRIPTION_STATUSES = {"trialing", "active", "past_due", "canceling", "canceled"}
LIVE_STATUSES = {"trialing", "active", "past_due", "canceling"}


def paid_transition_open(tenant: dict) -> bool:
    """An admin has allowed this complimentary or manual account to buy a plan, and
    the window is still open. Fails closed on a missing or unreadable date."""
    raw = str(tenant.get("paid_transition_expires_at") or "")
    if not raw:
        return False
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires > datetime.now(timezone.utc) and transition_eligible(tenant)


def transition_eligible(tenant: dict) -> bool:
    """Complimentary or manual, with no subscription on record to collide with."""
    return (account_state_source(tenant) in ("complimentary", "manual")
            and not str(tenant.get("stripe_subscription_id") or "").strip())


def account_state_source(tenant: dict) -> str:
    status = str(tenant.get("subscription_status") or "").strip().lower()
    if status not in SUBSCRIPTION_STATUSES:
        status = "none"
    if bool(str(tenant.get("stripe_subscription_id") or "").strip()) and status != "none":
        return "subscription"
    if trial.is_billing_exempt(tenant):
        return "complimentary"
    if status in ("active", "canceling", "past_due"):
        return "manual"
    return "trial" if trial.trial_status(tenant).get("trial_active") else "none"


def account_state(tenant: dict) -> dict:
    status = str(tenant.get("subscription_status") or "").strip().lower()
    if status not in SUBSCRIPTION_STATUSES:
        status = "none"
    has_provider = bool(str(tenant.get("stripe_subscription_id") or "").strip())
    plan = str(tenant.get("subscription_plan") or "").strip().lower() or None
    trial_info = trial.trial_status(tenant)

    source = account_state_source(tenant)

    has_number = bool(str(tenant.get("twilio_phone_number") or "").strip())
    if not has_number:
        phone_line = "none"
    else:
        phone_line = "on" if trial_info.get("line_active") else "off"

    return {
        "plan": plan,
        "feature_plan": plan if status in LIVE_STATUSES else None,
        "phone_line": phone_line,
        "source": source,
        "subscription": status,
        "has_provider_subscription": has_provider,
        "line_active": bool(trial_info.get("line_active")),
        "pending_activation": bool(trial_info.get("trial_pending_activation")),
        "paid_transition_open": paid_transition_open(tenant),
    }
