"""Auto-conversion of a card trial when its minutes run out.

record_call_minutes() is the only code path that sees a tenant cross the trial
minute cap, so it is where the trial converts into the paid plan. The ordering
assertion here is the important one: conversion zeroes the minute counter, and
running it before the usage write would let that write restore the trial's 60
minutes into the customer's fresh paid allocation.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import trial, usage
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())


def _tenant(minutes_used, status="trialing", **over):
    return {
        "id": "t_usage",
        "subscription_status": status,
        "subscription_plan": "starter",          # 150-minute allocation
        "stripe_subscription_id": "sub_x",
        "stripe_customer_id": "cus_x",
        "minutes_used_this_period": minutes_used,
        "created_at": "2026-08-01T00:00:00+00:00",
        **over,
    }


async def _record(tenant, prior_minutes, duration_secs, calls=None):
    """Drive record_call_minutes with the DB and period check stubbed out."""
    async def _convert(t, reason):
        if calls is not None:
            calls.append(("convert", reason))
        return {"converted": True, "already": False, "reason": reason, "status": "active"}

    async def _update(tenant_id, updates):
        if calls is not None:
            calls.append(("usage_write", updates.get("minutes_used_this_period")))

    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=tenant)), \
         patch("db.supabase.update_tenant", new=_update), \
         patch("services.usage._check_and_reset_period",
               new=AsyncMock(return_value=(prior_minutes, 0, "2026-08-01"))), \
         patch("services.trial.convert_card_trial", side_effect=_convert) as conv:
        await usage.record_call_minutes(tenant["id"], duration_secs)
    return conv


@pytest.mark.asyncio
async def test_crossing_the_cap_converts_the_trial():
    calls = []
    t = _tenant(55)
    conv = await _record(t, prior_minutes=55, duration_secs=360, calls=calls)  # +6 min -> 61

    conv.assert_called_once()
    assert conv.call_args.kwargs["reason"] == "minutes"
    # Usage is persisted BEFORE conversion resets the counter, never after.
    assert [c[0] for c in calls] == ["usage_write", "convert"]
    assert calls[0][1] == 61


@pytest.mark.asyncio
async def test_landing_exactly_on_the_cap_converts():
    conv = await _record(_tenant(50), prior_minutes=50, duration_secs=600)  # +10 -> 60
    conv.assert_called_once()


@pytest.mark.asyncio
async def test_under_the_cap_does_not_convert():
    conv = await _record(_tenant(30), prior_minutes=30, duration_secs=300)  # +5 -> 35
    conv.assert_not_called()


@pytest.mark.asyncio
async def test_paying_tenant_never_auto_converts():
    """A subscriber past 60 minutes is simply using their plan allocation."""
    conv = await _record(_tenant(500, status="active"), prior_minutes=500, duration_secs=600)
    conv.assert_not_called()


@pytest.mark.asyncio
async def test_already_converted_tenant_does_not_convert_again():
    t = _tenant(80, trial_converted_reason="time")
    conv = await _record(t, prior_minutes=80, duration_secs=600)
    conv.assert_not_called()


@pytest.mark.asyncio
async def test_conversion_failure_never_breaks_call_recording():
    """The call has already happened; losing its minutes because Stripe blipped
    would be worse than a trial that converts late."""
    calls = []

    async def _update(tenant_id, updates):
        calls.append(updates.get("minutes_used_this_period"))

    with patch("db.supabase.get_tenant_by_id", new=AsyncMock(return_value=_tenant(58))), \
         patch("db.supabase.update_tenant", new=_update), \
         patch("services.usage._check_and_reset_period",
               new=AsyncMock(return_value=(58, 0, "2026-08-01"))), \
         patch("services.trial.convert_card_trial",
               new=AsyncMock(side_effect=RuntimeError("stripe down"))):
        await usage.record_call_minutes("t_usage", 300)  # +5 -> 63

    assert calls == [63]


def test_cap_constant_is_the_one_the_gate_uses():
    """usage.py and the call gate must read the same number, or a tenant could be
    gated at a threshold that never triggers conversion."""
    assert trial.CARD_TRIAL_MINUTES == 60
