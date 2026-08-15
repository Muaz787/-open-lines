"""Card-trial notices and the stalled-conversion sweep.

Two things are load-bearing here:
  * the day-6 notice must go out even to a tenant who unsubscribed from
    marketing — it announces a charge, which is transactional, and suppressing
    it is what turns a trial into a negative-option billing complaint;
  * the stalled-conversion sweep is the ONLY recovery path for a tenant whose
    auto-conversion failed, because their line is gated and calls are exactly
    what would otherwise trigger the retry.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import trial
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _row(**over):
    return {
        "id": "t1", "business_name": "Acme", "email": "a@b.com",
        "subscription_status": "trialing", "subscription_plan": "pro",
        "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
        "stripe_trial_ends_at": _iso(days=5),
        "minutes_used_this_period": 12,
        "card_trial_day3_sent": False, "card_trial_day6_sent": False,
        **over,
    }


def _db_returning(rows):
    """Stub the chained supabase query builder used by the sweeps."""
    q = MagicMock()
    for m in ("select", "eq", "is_", "gte", "limit"):
        getattr(q, m).return_value = q
    q.execute.return_value = MagicMock(data=rows)
    client = MagicMock()
    client.table.return_value = q
    return client


async def _run_reminders(rows, charge=None):
    sends: list[dict] = []

    async def _send(**kw):
        sends.append(kw)
        return True

    with patch("db.supabase.get_client", return_value=_db_returning(rows)), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd, \
         patch("services.subscriptions.upcoming_charge",
               return_value=charge or {"amount_text": "$224.87 CAD (incl. tax)", "card_last4": "4242"}), \
         patch("services.email.send_card_trial_email", new=_send):
        result = await trial.process_card_trial_reminders()
    return result, sends, upd


# ── Reminder sweep ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_day6_notice_names_the_amount_date_and_card():
    result, sends, upd = await _run_reminders([_row(stripe_trial_ends_at=_iso(days=1))])

    assert result["day6"] == 1
    assert sends[0]["kind"] == "day6"
    assert sends[0]["amount_text"] == "$224.87 CAD (incl. tax)"
    assert sends[0]["card_last4"] == "4242"
    assert sends[0]["charge_date"]          # the date the charge lands
    assert upd.call_args.args[1] == {"card_trial_day6_sent": True}


@pytest.mark.asyncio
async def test_day3_notice_reports_trial_minutes():
    result, sends, _ = await _run_reminders([_row(stripe_trial_ends_at=_iso(days=4))])
    assert result["day3"] == 1
    assert sends[0]["kind"] == "day3"
    assert sends[0]["minutes_used"] == 12
    assert sends[0]["minutes_total"] == trial.CARD_TRIAL_MINUTES


@pytest.mark.asyncio
async def test_charge_notice_is_not_suppressed_by_a_marketing_unsubscribe():
    """Transactional, not marketing. process_trial_reminders() skips unsubscribed
    tenants; this sweep must not, or we would silently stop telling someone their
    card is about to be charged."""
    row = _row(stripe_trial_ends_at=_iso(days=1), marketing_unsubscribed_at=_iso(days=-3))
    result, sends, _ = await _run_reminders([row])
    assert result["day6"] == 1 and len(sends) == 1


@pytest.mark.asyncio
async def test_each_notice_is_sent_once():
    result, sends, _ = await _run_reminders([
        _row(stripe_trial_ends_at=_iso(days=1), card_trial_day6_sent=True),
        _row(id="t2", stripe_trial_ends_at=_iso(days=4), card_trial_day3_sent=True),
    ])
    assert result == {"day3": 0, "day6": 0}
    assert sends == []


@pytest.mark.asyncio
async def test_a_failed_send_is_not_flagged_so_it_retries_tomorrow():
    with patch("db.supabase.get_client", return_value=_db_returning([_row(stripe_trial_ends_at=_iso(days=1))])), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd, \
         patch("services.subscriptions.upcoming_charge", return_value={"amount_text": "", "card_last4": ""}), \
         patch("services.email.send_card_trial_email", new=AsyncMock(return_value=False)):
        result = await trial.process_card_trial_reminders()
    assert result["day6"] == 0
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_comped_tenants_get_no_charge_notice():
    """A comp is never billed, so warning them about a charge would be a lie."""
    result, sends, _ = await _run_reminders([
        _row(stripe_trial_ends_at=_iso(days=1), billing_exempt=True),
    ])
    assert sends == [] and result["day6"] == 0


@pytest.mark.asyncio
async def test_mid_trial_tenants_get_nothing_yet():
    result, sends, _ = await _run_reminders([_row(stripe_trial_ends_at=_iso(days=6))])
    assert sends == [] and result == {"day3": 0, "day6": 0}


# ── Stalled-conversion sweep ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_converts_a_gated_tenant():
    """Auto-conversion failed at end-of-call, so the tenant is over the cap, still
    trialing, and their line is gated. No further call can retry it — this sweep
    is the only way back."""
    stalled = {
        "id": "t9", "subscription_status": "trialing", "subscription_plan": "pro",
        "stripe_subscription_id": "sub_9", "minutes_used_this_period": 74,
        "trial_converted_reason": None,
    }
    with patch("db.supabase.get_client", return_value=_db_returning([stalled])), \
         patch("services.trial.convert_card_trial",
               new=AsyncMock(return_value={"converted": True, "already": False,
                                           "reason": "minutes", "status": "active"})) as conv:
        out = await trial.retry_stalled_conversions()

    assert out == {"converted": 1, "failed": 0}
    assert conv.call_args.kwargs["reason"] == "minutes"


@pytest.mark.asyncio
async def test_sweep_reports_a_still_failing_conversion():
    stalled = {
        "id": "t10", "subscription_status": "trialing", "stripe_subscription_id": "sub_10",
        "minutes_used_this_period": 61, "trial_converted_reason": None,
    }
    with patch("db.supabase.get_client", return_value=_db_returning([stalled])), \
         patch("services.trial.convert_card_trial",
               new=AsyncMock(return_value={"converted": False, "already": False,
                                           "reason": "stripe_error", "status": None})):
        out = await trial.retry_stalled_conversions()
    assert out == {"converted": 0, "failed": 1}


@pytest.mark.asyncio
async def test_sweep_skips_comped_tenants():
    stalled = {
        "id": "t11", "subscription_status": "trialing", "stripe_subscription_id": "sub_11",
        "minutes_used_this_period": 900, "trial_converted_reason": None, "billing_exempt": True,
    }
    with patch("db.supabase.get_client", return_value=_db_returning([stalled])), \
         patch("services.trial.convert_card_trial", new=AsyncMock()) as conv:
        out = await trial.retry_stalled_conversions()
    assert out == {"converted": 0, "failed": 0}
    conv.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_survives_a_db_failure():
    with patch("db.supabase.get_client", side_effect=RuntimeError("db down")):
        out = await trial.retry_stalled_conversions()
    assert out["error"] is True


# ── Legacy nudge vs the card trial (no contradictory emails) ─────────────────

def _legacy(**over):
    """A pre-cutover tenant on the derived card-free trial, about to lapse."""
    return {
        "id": "t_legacy", "business_name": "Acme", "email": "info@acme.ai",
        "subscription_status": "none", "created_at": _iso(days=-6),
        "minutes_used_this_period": 2,
        "trial_email_day3_sent": True, "trial_email_day6_sent": False,
        "trial_email_ended_sent": False,
        **over,
    }


async def _run_legacy(rows):
    sends = []

    async def _send(**kw):
        sends.append(kw)
        return True

    with patch("db.supabase.get_client", return_value=_db_returning(rows)), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.email.send_trial_reminder_email", new=_send):
        result = await trial.process_trial_reminders()
    return result, sends


@pytest.mark.asyncio
async def test_a_lapsing_legacy_trial_still_gets_its_nudge():
    result, sends = await _run_legacy([_legacy()])
    assert result["ending"] == 1 and sends[0]["kind"] == "ending"


@pytest.mark.asyncio
async def test_no_contradictory_pair_when_one_person_owns_two_tenants():
    """The real incident: an abandoned pre-cutover test account and the card trial
    the same person later signed up for, sharing one email. Each row is judged
    correctly on its own, so the human got 'we'll charge your card tomorrow' and
    'add a plan to avoid interruption' in the same minute."""
    card_trial = {
        "id": "t_card", "business_name": "Acme", "email": "INFO@acme.ai",
        "subscription_status": "trialing", "created_at": _iso(days=-6),
        "minutes_used_this_period": 0,
    }
    result, sends = await _run_legacy([_legacy(), card_trial])

    assert sends == []
    assert result["ending"] == 0


@pytest.mark.asyncio
async def test_a_comped_tenant_gets_no_legacy_nudge():
    """billing_exempt was not in the select list, so has_active_subscription()
    could not see it and comps were nudged to buy a plan they already have free."""
    result, sends = await _run_legacy([_legacy(billing_exempt=True)])
    assert sends == [] and result["ending"] == 0


@pytest.mark.asyncio
async def test_an_unsubscribed_tenant_is_respected():
    """CASL. The loop always tested marketing_unsubscribed_at, but the column was
    never fetched — so the check silently passed for everyone."""
    result, sends = await _run_legacy([_legacy(marketing_unsubscribed_at=_iso(days=-2))])
    assert sends == [] and result["ending"] == 0
