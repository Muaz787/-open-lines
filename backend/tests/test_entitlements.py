"""Entitlements: dark by default, correct Pro/Business boundary, server-side gate."""
import pytest

from services import entitlements as ent


def _tenant(plan="pro", status="active", opted_in=True):
    return {"subscription_plan": plan, "subscription_status": status, "routing_enabled": opted_in}


def test_dark_when_master_off(monkeypatch):
    monkeypatch.delenv("ROUTING_ENABLED", raising=False)
    r = ent.resolve(_tenant("business"))
    assert r["tier"] == "off"
    assert r["overflow"] is False and r["routing"] is False


def test_dark_when_tenant_not_opted_in(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    r = ent.resolve(_tenant("pro", opted_in=False))
    assert r["tier"] == "off"
    assert ent.has_feature(_tenant("pro", opted_in=False), "overflow") is False


def test_pro_boundary(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    t = _tenant("pro")
    assert ent.has_feature(t, "overflow") is True
    assert ent.has_feature(t, "routing") is True
    assert ent.has_feature(t, "warm_transfer") is True          # NOT degraded for Pro
    assert ent.has_feature(t, "callback_fallback") is True
    # scale features are Business-only
    for f in ("named_routing", "ring_groups", "sequential_routing", "schedules", "crm_routing"):
        assert ent.has_feature(t, f) is False, f
    assert ent.limit_for(t, "max_routing_rules") == 5
    assert ent.limit_for(t, "max_destinations") == 2
    assert ent.resolve(t)["analytics"] == "basic"


def test_business_boundary(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    t = _tenant("business")
    for f in ("overflow", "routing", "warm_transfer", "named_routing", "ring_groups",
              "sequential_routing", "schedules", "holidays", "crm_routing", "vip_routing"):
        assert ent.has_feature(t, f) is True, f
    assert ent.limit_for(t, "max_routing_rules") == 50
    assert ent.limit_for(t, "max_destinations") == 50
    assert ent.resolve(t)["analytics"] == "full"


def test_starter_and_trial_get_nothing(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    for plan in ("starter", "trial", None):
        assert ent.has_feature(_tenant(plan), "overflow") is False


def test_inactive_subscription_downgrades_to_off(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    # a Business plan with a canceled subscription is treated as no-capability
    t = _tenant("business", status="canceled")
    assert ent.tier_for(t) == "starter"
    assert ent.has_feature(t, "ring_groups") is False


def test_require_raises(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    with pytest.raises(ent.EntitlementError):
        ent.require(_tenant("pro"), "ring_groups")           # Pro not entitled
    ent.require(_tenant("business"), "ring_groups")          # ok, no raise


def test_downgrade_business_to_pro_disables_scale(monkeypatch):
    monkeypatch.setenv("ROUTING_ENABLED", "true")
    # same tenant row, plan flips business -> pro: scale features disabled at eval time
    t = _tenant("pro")
    assert ent.has_feature(t, "ring_groups") is False
    assert ent.limit_for(t, "max_destinations") == 2
