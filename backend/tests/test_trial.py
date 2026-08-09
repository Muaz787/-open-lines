"""Trial status: the two trial kinds, the call gate, and the minute caps.

trial_status() decides whether an inbound call is answered (routers/webhooks.py),
so a regression here silently takes phone lines down for real businesses. These
tests pin both branches and, critically, the boundaries between them.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import trial
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())


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


# ── Unpaid trial conversion (the narrow past_due gate) ───────────────────────

def _converted(unpaid, status="past_due", **over):
    """A tenant whose trial has ended and been charged."""
    return {
        "id": "t_conv", "subscription_status": status, "subscription_plan": "starter",
        "trial_converted_reason": "minutes", "trial_conversion_unpaid": unpaid,
        "minutes_used_this_period": 12, "created_at": _iso(days=-9),
        **over,
    }


def test_bounced_first_charge_gates_the_line():
    """Burned the trial, card then bounced: service consumed, nothing paid."""
    t = _converted(unpaid=True)
    ts = trial.trial_status(t)
    assert ts["line_active"] is False
    assert ts["payment_required"] is True
    assert trial.blocked_reason(t) == "trial_conversion_unpaid"


def test_established_customer_past_due_keeps_line():
    """The whole point of the separate flag: someone who converted cleanly months
    ago and later has a card expire is in ordinary dunning and must NOT be cut off.
    trial_converted_reason alone stays set forever and would wrongly gate them."""
    t = _converted(unpaid=False, created_at=_iso(days=-200))
    ts = trial.trial_status(t)
    assert ts["line_active"] is True
    assert ts["payment_required"] is False
    assert trial.blocked_reason(t) == ""


def test_unpaid_flag_alone_does_not_gate_an_active_subscription():
    """Only past_due gates. A paid-and-active tenant whose flag has not yet been
    cleared by the webhook must keep serving calls."""
    assert trial.trial_status(_converted(unpaid=True, status="active"))["line_active"] is True


def test_billing_exempt_beats_the_unpaid_gate():
    assert trial.trial_status(_converted(unpaid=True, billing_exempt=True))["line_active"] is True


def test_conversion_payment_failed_predicate():
    assert trial.conversion_payment_failed(_converted(unpaid=True)) is True
    assert trial.conversion_payment_failed(_converted(unpaid=False)) is False
    assert trial.conversion_payment_failed(_converted(unpaid=True, status="active")) is False
    assert trial.conversion_payment_failed({}) is False


# ── convert_card_trial ───────────────────────────────────────────────────────

def _stripe_sub(status="active", period_start=1_760_000_000):
    sub = MagicMock()
    sub.status = status
    sub.current_period_start = period_start
    return sub


@pytest.mark.asyncio
async def test_convert_charges_and_resets_counters():
    t = _card_trial(minutes=60, plan="starter", id="t1", stripe_subscription_id="sub_1")
    with patch("stripe.Subscription.modify", return_value=_stripe_sub("active")) as modify, \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await trial.convert_card_trial(t, reason="minutes")

    assert res["converted"] is True and res["status"] == "active"
    # Ends the trial rather than creating anything new, and is replay-safe.
    assert modify.call_args.args[0] == "sub_1"
    assert modify.call_args.kwargs["trial_end"] == "now"
    assert modify.call_args.kwargs["idempotency_key"] == "convert-trial-sub_1"

    wrote = upd.call_args.args[1]
    assert wrote["subscription_status"] == "active"
    assert wrote["trial_converted_reason"] == "minutes"
    assert wrote["stripe_trial_ends_at"] is None
    # The paid month starts clean — trial minutes are not billed against it.
    assert wrote["minutes_used_this_period"] == 0
    assert wrote["overage_minutes_reported"] == 0
    assert wrote["billing_period_anchor"]
    # Cleared only by the first paid invoice.
    assert wrote["trial_conversion_unpaid"] is True


@pytest.mark.asyncio
async def test_convert_records_a_failed_charge_as_unpaid():
    """Stripe accepted the trial_end change but the card declined. The tenant must
    end up gated, not silently served."""
    t = _card_trial(minutes=60, id="t2", stripe_subscription_id="sub_2")
    with patch("stripe.Subscription.modify", return_value=_stripe_sub("past_due")), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await trial.convert_card_trial(t, reason="minutes")

    assert res["converted"] is True and res["status"] == "past_due"
    wrote = upd.call_args.args[1]
    assert wrote["trial_conversion_unpaid"] is True
    assert trial.conversion_payment_failed({**t, **wrote}) is True


@pytest.mark.asyncio
async def test_convert_is_a_noop_when_already_converted():
    t = _card_trial(id="t3", stripe_subscription_id="sub_3", trial_converted_reason="time")
    with patch("stripe.Subscription.modify") as modify, \
         patch("db.supabase.update_tenant", new=AsyncMock()):
        res = await trial.convert_card_trial(t, reason="minutes")
    assert res["converted"] is False and res["already"] is True
    modify.assert_not_called()


@pytest.mark.asyncio
async def test_convert_is_a_noop_for_a_paying_tenant():
    t = {"id": "t4", "subscription_status": "active", "stripe_subscription_id": "sub_4"}
    with patch("stripe.Subscription.modify") as modify:
        res = await trial.convert_card_trial(t, reason="manual")
    assert res["converted"] is False
    modify.assert_not_called()


@pytest.mark.asyncio
async def test_convert_swallows_stripe_errors():
    """Called from the call-recording path — a Stripe outage must never make us
    lose a recorded call or raise into the webhook handler."""
    t = _card_trial(minutes=60, id="t5", stripe_subscription_id="sub_5")
    with patch("stripe.Subscription.modify", side_effect=RuntimeError("stripe down")), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd:
        res = await trial.convert_card_trial(t, reason="minutes")
    assert res["converted"] is False
    assert res["reason"] == "stripe_error"
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_convert_requires_a_subscription_id():
    t = _card_trial(minutes=60, id="t6", stripe_subscription_id="")
    with patch("stripe.Subscription.modify") as modify:
        res = await trial.convert_card_trial(t, reason="minutes")
    assert res["converted"] is False and res["reason"] == "no_subscription"
    modify.assert_not_called()


# ── Status mapping ───────────────────────────────────────────────────────────

def test_stripe_status_map_keeps_trialing_distinct():
    assert trial.map_stripe_status("trialing") == "trialing"
    assert trial.map_stripe_status("active") == "active"
    assert trial.map_stripe_status("unpaid") == "past_due"
    assert trial.map_stripe_status("incomplete_expired") == "canceled"
    # Per-call-site extras and passthrough for anything Stripe adds later.
    assert trial.map_stripe_status("paused", {"paused": "paused"}) == "paused"
    assert trial.map_stripe_status("some_new_status") == "some_new_status"


# ── Deactivation ─────────────────────────────────────────────────────────────

def test_deactivated_tenant_takes_no_calls():
    """`Deactivate Tenant` used to set a flag nothing on the call path read, so a
    closed account kept answering and kept storing caller data."""
    t = _card_trial(minutes=5, is_active=False)
    ts = trial.trial_status(t)
    assert ts["line_active"] is False
    assert ts["deactivated"] is True
    assert trial.blocked_reason(t) == "tenant_deactivated"


def test_deactivation_beats_a_paying_subscription():
    ts = trial.trial_status({
        "id": "t_x", "subscription_status": "active", "subscription_plan": "pro",
        "minutes_used_this_period": 10, "created_at": _iso(days=-40), "is_active": False,
    })
    assert ts["line_active"] is False


def test_deactivation_beats_a_comp():
    """An admin switching an account off should not be overridden by billing_exempt."""
    ts = trial.trial_status({
        "id": "t_c", "subscription_status": "none", "billing_exempt": True,
        "minutes_used_this_period": 0, "created_at": _iso(days=-400), "is_active": False,
    })
    assert ts["line_active"] is False


def test_missing_or_null_is_active_does_not_gate():
    """THE test that matters. is_active defaults true, but an older row or a
    partial select can hand us None — and a falsy check would read that as "off"
    and take every live line down at once."""
    for value in (None, True):
        t = _card_trial(minutes=5, is_active=value)
        assert trial.trial_status(t)["line_active"] is True, value
    # Key absent entirely
    t = _card_trial(minutes=5)
    t.pop("is_active", None)
    assert trial.trial_status(t)["line_active"] is True


def test_reactivating_restores_the_line():
    t = _card_trial(minutes=5, is_active=False)
    assert trial.trial_status(t)["line_active"] is False
    t["is_active"] = True
    assert trial.trial_status(t)["line_active"] is True


# ── Shape contract ───────────────────────────────────────────────────────────

def test_both_branches_return_the_same_keys():
    """Every caller (call gate, dashboard banner, /onboarding/status) reads one
    shape without knowing which trial kind it got."""
    assert set(trial.trial_status(_card_trial())) == set(trial.trial_status(_derived_trial()))
