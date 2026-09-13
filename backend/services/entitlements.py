"""
Central plan-entitlement resolver for AI Overflow Handling & AI Call Routing.

Single server-side source of truth for which subscription tiers get which
capabilities and limits — so gating is enforced in one place instead of the
ad-hoc per-feature plan checks used elsewhere (cf. services/kb_limits.py,
routers/square_connect.py, routers/stripe_connect.py).

SAFETY — DARK LAUNCH:
  * The entire capability set is inert unless ROUTING_ENABLED is truthy (a master
    kill switch, mirroring services/zapier.py). With it unset, every tenant
    resolves to "no overflow, no routing" and production behaves exactly as today.
  * On top of the master switch, a tenant must ALSO be individually opted in
    (tenants.routing_enabled — added in a later migration). Until that column
    exists / is true, callers get nothing. This lets us test on our OWN tenant
    first, before any paying customer's calls are ever affected.

Capabilities/limits follow Section 4 of the approved plan. Pro is deliberately
NOT a degraded transfer experience — warm/bridged transfer + safe fallback are
available to Pro; Business differs by ROUTING SCALE (many destinations, groups,
schedules, named/CRM routing), not call safety.
"""
from __future__ import annotations

import os

# A subscription counts as active for entitlement purposes in these states
# (same set kb_limits.py already uses).
_ACTIVE_SUB_STATUSES = {"active", "trialing", "past_due", "canceling"}


class EntitlementError(PermissionError):
    """Raised when a tenant is not entitled to a requested capability."""


def master_enabled() -> bool:
    """Global dark-launch switch. Read live so toggling the env var needs no deploy."""
    return os.getenv("ROUTING_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def transfer_execution_enabled() -> bool:
    """SEPARATE gate for actually placing live transfers (the telephony layer).
    Off by default even when routing config/decisions are enabled, so we can turn
    on the decision layer (classify/route/callback) and validate it before any real
    call is bridged. The telephony layer flips this ON only after live validation on
    our own tenant."""
    return os.getenv("ROUTING_TRANSFER_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


# Per-tier capability + limit matrix. Booleans are features; ints are limits.
_OFF: dict = {
    "overflow": False, "routing": False, "warm_transfer": False,
    "callback_fallback": False, "urgent_escalation": False,
    "named_routing": False, "ring_groups": False, "sequential_routing": False,
    "schedules": False, "holidays": False, "crm_routing": False, "vip_routing": False,
    "analytics": "none", "max_routing_rules": 0, "max_destinations": 0,
}

_PRO: dict = {
    "overflow": True, "routing": True, "warm_transfer": True,
    "callback_fallback": True, "urgent_escalation": True,
    "named_routing": False, "ring_groups": False, "sequential_routing": False,
    "schedules": False, "holidays": False, "crm_routing": False, "vip_routing": False,
    "analytics": "basic",
    # 1 default human + 1 urgent/on-call destination; a small deterministic rule set.
    "max_routing_rules": 5, "max_destinations": 2,
}

_BUSINESS: dict = {
    "overflow": True, "routing": True, "warm_transfer": True,
    "callback_fallback": True, "urgent_escalation": True,
    "named_routing": True, "ring_groups": True, "sequential_routing": True,
    "schedules": True, "holidays": True, "crm_routing": True, "vip_routing": True,
    "analytics": "full",
    "max_routing_rules": 50, "max_destinations": 50,
}

_TIERS: dict[str, dict] = {
    "trial": _OFF, "starter": _OFF, "pro": _PRO, "business": _BUSINESS,
}


def entitled_plan(tenant: dict) -> str | None:
    """The paid plan IN FORCE for this tenant right now, or None.

    The one definition of "has this customer got the plan they chose", so the
    per-feature gates stop each deciding it for themselves. Square, Stripe
    Connect, deposits and the knowledge-base caps all asked the same question
    four different times, which is why they could disagree.

    A SUBSCRIPTION THAT CANNOT START YET IS NOT A SUBSCRIPTION THEY LACK.
    The ordinary case is a live subscription, `trialing` included -- a card
    trial is a real Stripe subscription and has always passed. But a tenant in a
    regulated country has no billable line until a regulator approves their
    number, so the subscription is deliberately not started at signup and their
    status sits at 'none' for as long as the filing takes. They chose Pro, they
    gave us a card, and the only thing they are waiting on is an authority
    neither they nor we control. Withholding the plan through that wait charges
    them for someone else's queue.

    So the second branch is narrow and evidenced, never "is this tenant Irish":
      * they picked a paid plan, and
      * they completed the payment step -- a Stripe Customer exists, which the
        regulated exit persists precisely so this is knowable, and
      * no trial has begun and none can until a real line exists.

    That last condition stops holding the moment their number goes live, with no
    code change, because it is the same predicate the dashboard banner and the
    trial-reminder sweep already read. And the window is bounded: a filing that
    stalls is suspended by the Ireland lifecycle (30 / 14 / 7 days), so this can
    never become indefinite free access.
    """
    plan = (tenant.get("subscription_plan") or "").lower()
    if plan not in ("pro", "business"):
        return None
    if (tenant.get("subscription_status") or "").lower() in _ACTIVE_SUB_STATUSES:
        return plan
    if _awaiting_activation(tenant):
        return plan
    return None


def _awaiting_activation(tenant: dict) -> bool:
    """Committed to a plan, but the subscription cannot start yet.

    Imported inside the function: services.trial reaches back into onboarding
    lifecycle, and a module-level import here would close the loop.
    """
    if not str(tenant.get("stripe_customer_id") or "").strip():
        return False               # never completed payment; nothing was chosen
    from services import trial as _trial
    return _trial._trial_pending_activation(tenant)


def tier_for(tenant: dict) -> str:
    """Resolve the effective tier, or 'starter'/_OFF when no paid plan is in
    force. Routing-specific; the plan question itself lives in entitled_plan."""
    return entitled_plan(tenant) or "starter"


def _tenant_opted_in(tenant: dict) -> bool:
    # Per-tenant activation. Defaults False when the column is absent (pre-migration)
    # so nothing turns on implicitly.
    return bool(tenant.get("routing_enabled"))


def resolve(tenant: dict) -> dict:
    """Return the effective capability/limit map for a tenant. If the master switch
    is off OR the tenant is not opted in, everything is disabled (dark)."""
    if not master_enabled() or not _tenant_opted_in(tenant):
        return {"tier": "off", **_OFF}
    tier = tier_for(tenant)
    return {"tier": tier, **_TIERS.get(tier, _OFF)}


def can_configure(tenant: dict) -> bool:
    """Plan-gated access to the routing CONFIG surface (owner dashboard/API). True for
    an active Pro/Business subscription while the master switch is on — INDEPENDENT of
    whether the tenant has switched routing on yet.

    Configuring (adding destinations/rules) never changes a customer's calls; only
    opting in — tenants.routing_enabled, see resolve()/has_feature() — attaches the
    assistant's routing tools. Starter/free/inactive -> False (dashboard shows locked)."""
    return master_enabled() and tier_for(tenant) in ("pro", "business")


def config_caps(tenant: dict) -> dict:
    """Tier capability/limit map for CONFIGURATION — plan-based, IGNORES opt-in. Lets a
    Pro/Business tenant set up destinations/rules (with the right limits) before turning
    routing on. Returns _OFF when not master-on / not an eligible plan."""
    if not can_configure(tenant):
        return {"tier": "off", **_OFF}
    tier = tier_for(tenant)
    return {"tier": tier, **_TIERS.get(tier, _OFF)}


def config_limit_for(tenant: dict, name: str) -> int:
    """Plan-based limit for the config surface (independent of opt-in). Use in the
    owner config API so caps are correct before a tenant activates routing."""
    val = config_caps(tenant).get(name, 0)
    return int(val) if isinstance(val, (int, bool)) else 0


def has_feature(tenant: dict, feature: str) -> bool:
    return bool(resolve(tenant).get(feature, False))


def limit_for(tenant: dict, name: str) -> int:
    val = resolve(tenant).get(name, 0)
    return int(val) if isinstance(val, (int, bool)) else 0


def require(tenant: dict, feature: str) -> None:
    """Raise EntitlementError unless the tenant is entitled to `feature`.
    Use at the top of every routing/overflow write path and mid-call tool."""
    if not has_feature(tenant, feature):
        raise EntitlementError(f"tenant not entitled to '{feature}'")
