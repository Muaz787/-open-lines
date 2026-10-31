"""One description of a tenant's plan and how they came to have it.

Having a plan and paying for it are different things. An admin can give a tenant
paid-tier features with no Stripe subscription, and a comped tenant has a live line
with neither. Every dashboard surface reads this, so none of them has to infer a
paid subscription from `subscription_status` alone.

Pure and built from the tenant row: no Stripe call. Whether Stripe agrees is
reported separately by /billing/subscription-details.
"""
from services import trial

SUBSCRIPTION_STATUSES = {"trialing", "active", "past_due", "canceling", "canceled"}


def account_state(tenant: dict) -> dict:
    status = str(tenant.get("subscription_status") or "").strip().lower()
    if status not in SUBSCRIPTION_STATUSES:
        status = "none"
    has_provider = bool(str(tenant.get("stripe_subscription_id") or "").strip())
    plan = str(tenant.get("subscription_plan") or "").strip().lower() or None
    trial_info = trial.trial_status(tenant)

    if has_provider and status != "none":
        source = "subscription"
    elif trial.is_billing_exempt(tenant):
        source = "complimentary"
    elif status in ("active", "canceling", "past_due"):
        source = "manual"
    elif trial_info.get("trial_active"):
        source = "trial"
    else:
        source = "none"

    return {
        "plan": plan,
        "source": source,
        "subscription": status,
        "has_provider_subscription": has_provider,
        "line_active": bool(trial_info.get("line_active")),
        "pending_activation": bool(trial_info.get("trial_pending_activation")),
    }
