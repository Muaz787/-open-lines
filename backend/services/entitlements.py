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


def tier_for(tenant: dict) -> str:
    """Resolve the effective tier. Requires an active subscription; otherwise the
    tenant is treated as having no routing capabilities (tier 'starter'/_OFF)."""
    plan = (tenant.get("subscription_plan") or "").lower()
    status = (tenant.get("subscription_status") or "").lower()
    if status in _ACTIVE_SUB_STATUSES and plan in ("pro", "business"):
        return plan
    return "starter"


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
