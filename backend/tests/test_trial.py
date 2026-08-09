"""Trial status: the two trial kinds, the call gate, and the minute caps.

trial_status() decides whether an inbound call is answered (routers/webhooks.py),
so a regression here silently takes phone lines down for real businesses. These
tests pin both branches and, critically, the boundaries between them.
"""
from datetime import datetime, timedelta, timezone

from services import trial


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _card_trial(minutes=0, ends_in_days=5, plan="pro", **over):
    """A tenant mid card-trial: Stripe sub in `trialing`, card on file."""
    return {
        "id": "t_card",
        "subscription_status": "trialing",
        "subscription_plan": plan,
        "stripe_trial_ends_at": _iso(days=ends_in_days),
        "minutes_used_this_period": minutes,
        "created_at": _iso(days=-2),
        **over,
    }


def _derived_trial(minutes=0, age_days=2, **over):
    """A legacy tenant on the card-free trial: no Stripe subscription at all."""
    return {
        "id": "t_derived",
        "subscription_status": "none",
        "subscription_plan": None,
        "minutes_used_this_period": minutes,
        "created_at": _iso(days=-age_days),
        **over,
    }


# ── Card trial ───────────────────────────────────────────────────────────────

def test_card_trial_is_live_within_time_and_cap():
    ts = trial.trial_status(_card_trial(minutes=10))
    assert ts["card_trial"] is True
    assert ts["line_active"] is True
    assert ts["trial_active"] is True
    assert ts["has_active_subscription"] is True
    # They already gave us a card and picked a plan — nothing to ask for.
    assert ts["subscription_required"] is False
    assert ts["plan"] == "pro"


def test_card_trial_uses_60_minute_cap_not_the_legacy_30():
    """The legacy 30-minute cap must not leak into card trials — 40 minutes is
    comfortably past it but still well inside the card-trial budget."""
    ts = trial.trial_status(_card_trial(minutes=40))
    assert ts["trial_minutes_total"] == trial.CARD_TRIAL_MINUTES == 60
    assert ts["trial_minutes_remaining"] == 20
    assert ts["line_active"] is True


def test_card_trial_gate_is_a_safety_net_at_the_cap():
    """Crossing the cap is meant to AUTO-CONVERT (services/usage), which flips the
    status to 'active' and resets the counter. If that never happened, this gate
    is what stops an unbounded free line."""
    ts = trial.trial_status(_card_trial(minutes=60))
    assert ts["line_active"] is False
    assert ts["trial_minutes_remaining"] == 0
    assert trial.blocked_reason(_card_trial(minutes=60)) == "card_trial_minutes_exhausted"


def test_card_trial_gate_holds_past_the_cap():
    assert trial.trial_status(_card_trial(minutes=999))["line_active"] is False


def test_card_trial_expires_on_time():
    t = _card_trial(minutes=5, ends_in_days=-1)
    ts = trial.trial_status(t)
    assert ts["line_active"] is False
    assert ts["trial_expired"] is True
    assert trial.blocked_reason(t) == "card_trial_days_expired"


def test_card_trial_fails_open_when_end_date_missing():
    """The billing webhook mirrors trial_end into stripe_trial_ends_at. If that
    write is ever missed, Stripe still ends the trial on schedule — so we must NOT
    gate the line of someone who has already handed us a card."""
    t = _card_trial(minutes=5)
    t["stripe_trial_ends_at"] = None
    ts = trial.trial_status(t)
    assert ts["line_active"] is True
    assert ts["trial_expired"] is False
    assert ts["trial_days_remaining"] == trial.TRIAL_DAYS


def test_card_trial_days_remaining_counts_down():
    assert trial.trial_status(_card_trial(ends_in_days=5))["trial_days_remaining"] == 5
    assert trial.trial_status(_card_trial(ends_in_days=1))["trial_days_remaining"] == 1


def test_is_card_trial_matches_only_trialing():
    assert trial.is_card_trial({"subscription_status": "trialing"}) is True
    assert trial.is_card_trial({"subscription_status": " Trialing "}) is True
    for status in ("active", "past_due", "canceled", "none", "", None):
        assert trial.is_card_trial({"subscription_status": status}) is False, status
    assert trial.is_card_trial({}) is False


# ── Legacy derived trial (must be unchanged) ─────────────────────────────────

def test_derived_trial_is_live_within_window():
    ts = trial.trial_status(_derived_trial(minutes=5))
    assert ts["card_trial"] is False
    assert ts["line_active"] is True
    assert ts["trial_active"] is True
    assert ts["trial_minutes_total"] == trial.TRIAL_MINUTES == 30
    assert ts["subscription_required"] is False


def test_derived_trial_gated_at_30_minutes():
    t = _derived_trial(minutes=30)
    ts = trial.trial_status(t)
    assert ts["line_active"] is False
    assert ts["trial_expired"] is True
    assert ts["subscription_required"] is True
    assert trial.blocked_reason(t) == "trial_minutes_exhausted"


def test_derived_trial_gated_after_7_days():
    t = _derived_trial(minutes=1, age_days=8)
    ts = trial.trial_status(t)
    assert ts["line_active"] is False
    assert ts["trial_expired"] is True
    assert trial.blocked_reason(t) == "trial_days_expired"


def test_derived_trial_without_created_at_is_not_live():
    ts = trial.trial_status(_derived_trial(created_at=None))
    assert ts["line_active"] is False
    assert ts["trial_ends_at"] is None


# ── Paying + comped tenants ──────────────────────────────────────────────────

def test_paying_tenant_has_no_minute_cap():
    """A paid plan's allocation and overage are handled by services/usage — the
    trial gate must never throttle a paying customer, however many minutes."""
    t = {
        "id": "t_paid", "subscription_status": "active", "subscription_plan": "starter",
        "minutes_used_this_period": 5000, "created_at": _iso(days=-90),
    }
    ts = trial.trial_status(t)
    assert ts["line_active"] is True
    assert ts["card_trial"] is False
    assert ts["trial_active"] is False
    assert trial.blocked_reason(t) == ""


def test_past_due_keeps_line_live():
    """Existing dunning behaviour: a failed renewal does not cut service."""
    ts = trial.trial_status({
        "id": "t_pd", "subscription_status": "past_due", "subscription_plan": "pro",
        "minutes_used_this_period": 200, "created_at": _iso(days=-90),
    })
    assert ts["line_active"] is True


def test_billing_exempt_tenant_is_always_live():
    ts = trial.trial_status({
        "id": "t_comp", "subscription_status": "none", "billing_exempt": True,
        "minutes_used_this_period": 9999, "created_at": _iso(days=-400),
    })
    assert ts["line_active"] is True
    assert ts["has_active_subscription"] is True


def test_billing_exempt_beats_card_trial_cap():
    """A trial tenant comped by hand keeps `trialing` on the subscription. The
    comp must win — otherwise the 60-minute cap would gate a line we promised
    would never be gated."""
    t = _card_trial(minutes=9999, billing_exempt=True)
    ts = trial.trial_status(t)
    assert ts["line_active"] is True
    assert ts["card_trial"] is False
    assert trial.blocked_reason(t) == ""


# ── Shape contract ───────────────────────────────────────────────────────────

def test_both_branches_return_the_same_keys():
    """Every caller (call gate, dashboard banner, /onboarding/status) reads one
    shape without knowing which trial kind it got."""
    assert set(trial.trial_status(_card_trial())) == set(trial.trial_status(_derived_trial()))
