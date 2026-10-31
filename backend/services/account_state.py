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
from services import trial

SUBSCRIPTION_STATUSES = {"trialing", "active", "past_due", "canceling", "canceled"}
LIVE_STATUSES = {"trialing", "active", "past_due", "canceling"}


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
    }
