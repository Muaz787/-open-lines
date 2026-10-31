"""Plan labels must not imply a paid subscription that doesn't exist."""
from services.account_state import account_state

SUB = {"stripe_subscription_id": "sub_1", "subscription_plan": "pro"}


def test_paid_subscription():
    out = account_state({**SUB, "subscription_status": "active"})
    assert (out["source"], out["subscription"], out["plan"]) == ("subscription", "active", "pro")
    assert out["has_provider_subscription"] is True


def test_card_trial():
    out = account_state({**SUB, "subscription_status": "trialing"})
    assert (out["source"], out["subscription"]) == ("subscription", "trialing")


def test_manually_set_plan_is_not_a_subscription():
    out = account_state({"subscription_plan": "pro", "subscription_status": "active"})
    assert out["source"] == "manual"
    assert out["plan"] == "pro"
    assert out["has_provider_subscription"] is False


def test_comped_tenant():
    out = account_state({"billing_exempt": True})
    assert out["source"] == "complimentary"
    assert out["plan"] is None
    assert out["line_active"] is True


def test_comp_with_a_plan_stays_complimentary():
    out = account_state({"billing_exempt": True, "subscription_plan": "pro", "subscription_status": "active"})
    assert (out["source"], out["plan"]) == ("complimentary", "pro")


def test_canceled_subscription_keeps_its_status():
    out = account_state({**SUB, "subscription_status": "canceled"})
    assert (out["source"], out["subscription"]) == ("subscription", "canceled")


def test_past_due_subscription():
    out = account_state({**SUB, "subscription_status": "past_due"})
    assert out["subscription"] == "past_due"


def test_no_subscription_and_expired_trial():
    out = account_state({"created_at": "2020-01-01T00:00:00+00:00"})
    assert (out["source"], out["subscription"]) == ("none", "none")


def test_unknown_status_is_not_passed_through():
    out = account_state({"subscription_status": "incomplete", "created_at": "2020-01-01T00:00:00+00:00"})
    assert out["subscription"] == "none"
