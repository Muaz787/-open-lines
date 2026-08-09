"""Reclaiming phone numbers from tenants who have gone.

release_due_at() is the whole safety story. A false positive here permanently
destroys a real business's phone line — Twilio reassigns released numbers — so
the tests that matter are the ones proving it refuses: protected subscriptions,
comps, missing anchors, and anything already released.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import number_reclaim as nr
import db.supabase as _supabase_mod  # noqa: F401  (registers the dotted path for patch())


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _tenant(**over):
    """A lapsed card-free trial: created 40 days ago, never subscribed."""
    return {
        "id": "t1", "business_name": "Acme", "email": "a@b.com",
        "twilio_phone_number": "+14165550100",
        "subscription_status": "none",
        "created_at": _iso(days=-40),
        **over,
    }


@pytest.fixture(autouse=True)
def _armed(monkeypatch):
    monkeypatch.setenv("NUMBER_RECLAIM_ENABLED", "true")
    monkeypatch.setenv("NUMBER_RECLAIM_DRY_RUN", "false")


# ── The switches ─────────────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NUMBER_RECLAIM_ENABLED", raising=False)
    assert nr.enabled() is False


def test_dry_run_is_the_default_even_once_enabled(monkeypatch):
    """Turning the feature on must not be enough to release anything — it takes a
    second, separate decision, because the operation cannot be undone."""
    monkeypatch.delenv("NUMBER_RECLAIM_DRY_RUN", raising=False)
    assert nr.dry_run() is True


@pytest.mark.asyncio
async def test_master_switch_off_does_nothing(monkeypatch):
    monkeypatch.delenv("NUMBER_RECLAIM_ENABLED", raising=False)
    with patch("db.supabase.get_client") as client:
        out = await nr.run_reclaim()
    assert out == {"enabled": False}
    client.assert_not_called()


# ── Who is eligible ──────────────────────────────────────────────────────────

def test_lapsed_trial_is_due_after_30_days():
    """Trial ended 33 days ago (created 40 days back, 7-day trial)."""
    assert nr.release_due_at(_tenant()) is not None
    assert nr.classify(_tenant()) == "release"


def test_lapsed_trial_is_not_due_before_30_days():
    t = _tenant(created_at=_iso(days=-20))   # trial ended 13 days ago
    assert nr.classify(t) == ""


def test_a_former_customer_gets_60_days_not_30():
    """Paid at least once, so they earn the longer grace."""
    t = _tenant(
        subscription_status="canceled",
        first_paid_at=_iso(days=-200),
        subscription_canceled_at=_iso(days=-40),
    )
    assert nr.classify(t) == ""          # 40 days in — still protected
    t["subscription_canceled_at"] = _iso(days=-70)
    assert nr.classify(t) == "release"


def test_card_trial_end_date_beats_the_derived_one():
    t = _tenant(created_at=_iso(days=-200), stripe_trial_ends_at=_iso(days=-10))
    # Stripe says the trial ended 10 days ago, so it is not yet due despite the
    # ancient created_at.
    assert nr.classify(t) == ""


# ── Who is protected ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "canceling"])
def test_live_subscriptions_are_never_touched(status):
    assert nr.release_due_at(_tenant(subscription_status=status)) is None


def test_comps_are_never_touched():
    assert nr.release_due_at(_tenant(billing_exempt=True)) is None


def test_a_tenant_with_no_number_is_skipped():
    assert nr.release_due_at(_tenant(twilio_phone_number=None)) is None


def test_an_already_released_number_is_not_released_again():
    """The row keeps its history, and a number reissued later must not be
    swept up by a stale timestamp."""
    assert nr.release_due_at(_tenant(number_released_at=_iso(days=-5))) is None


def test_a_former_customer_with_no_cancellation_date_is_left_alone():
    """Rows from before migration 011 have no anchor. Guessing one could release
    a number 60 days too early, so the answer is never."""
    t = _tenant(subscription_status="canceled", first_paid_at=_iso(days=-300),
                created_at=_iso(days=-400))
    assert nr.release_due_at(t) is None


def test_no_usable_dates_at_all_means_never():
    t = _tenant(created_at=None)
    assert nr.release_due_at(t) is None


def test_an_admin_closure_anchors_the_clock():
    t = _tenant(created_at=_iso(days=-5), closed_at=_iso(days=-35))
    assert nr.classify(t) == "release"


# ── Warnings ─────────────────────────────────────────────────────────────────

def test_first_warning_fires_14_days_out():
    t = _tenant(created_at=_iso(days=-30))    # trial ended 23d ago; due in 7d
    assert nr.classify(t) == "warn1"


def test_final_warning_fires_3_days_out():
    t = _tenant(created_at=_iso(days=-35), number_release_warn1_sent=True)
    assert nr.classify(t) == "warn2"


def test_a_warning_is_only_sent_once():
    t = _tenant(created_at=_iso(days=-30), number_release_warn1_sent=True)
    assert nr.classify(t) == ""


# ── The sweep ────────────────────────────────────────────────────────────────

def _db_returning(rows):
    q = MagicMock()
    q.select.return_value = q
    q.not_.is_.return_value = q
    q.execute.return_value = MagicMock(data=rows)
    client = MagicMock()
    client.table.return_value = q
    return client


@pytest.mark.asyncio
async def test_dry_run_releases_nothing(monkeypatch):
    monkeypatch.setenv("NUMBER_RECLAIM_DRY_RUN", "true")
    with patch("db.supabase.get_client", return_value=_db_returning([_tenant()])), \
         patch("services.provisioning.release_tenant_number", new=AsyncMock()) as rel:
        out = await nr.run_reclaim()

    assert out["dry_run"] is True
    assert out["released"] == 1     # counted as "would release"
    rel.assert_not_called()         # but nothing actually happened


@pytest.mark.asyncio
async def test_armed_run_releases_and_stamps():
    with patch("db.supabase.get_client", return_value=_db_returning([_tenant()])), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd, \
         patch("services.provisioning.release_tenant_number",
               new=AsyncMock(return_value={"released": True, "steps": {}, "reason": ""})) as rel:
        out = await nr.run_reclaim()

    assert out["released"] == 1 and out["failed"] == 0
    rel.assert_called_once()
    assert "number_released_at" in upd.call_args.args[1]


@pytest.mark.asyncio
async def test_a_failed_release_is_counted_not_swallowed():
    with patch("db.supabase.get_client", return_value=_db_returning([_tenant()])), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.provisioning.release_tenant_number",
               new=AsyncMock(return_value={"released": False, "steps": {}, "reason": "twilio_release_failed"})):
        out = await nr.run_reclaim()
    assert out["released"] == 0 and out["failed"] == 1


@pytest.mark.asyncio
async def test_the_per_run_cap_holds(monkeypatch):
    monkeypatch.setenv("NUMBER_RECLAIM_MAX_PER_RUN", "2")
    monkeypatch.setattr(nr, "MAX_RELEASES_PER_RUN", 2)
    rows = [_tenant(id=f"t{i}") for i in range(10)]
    with patch("db.supabase.get_client", return_value=_db_returning(rows)), \
         patch("db.supabase.update_tenant", new=AsyncMock()), \
         patch("services.provisioning.release_tenant_number",
               new=AsyncMock(return_value={"released": True, "steps": {}, "reason": ""})) as rel:
        out = await nr.run_reclaim()

    assert out["released"] == 2
    assert rel.call_count == 2


@pytest.mark.asyncio
async def test_the_sweep_sends_warnings_and_flags_them():
    warned = _tenant(created_at=_iso(days=-30))
    with patch("db.supabase.get_client", return_value=_db_returning([warned])), \
         patch("db.supabase.update_tenant", new=AsyncMock()) as upd, \
         patch("services.email.send_number_release_warning", new=AsyncMock(return_value=True)) as mail, \
         patch("services.provisioning.release_tenant_number", new=AsyncMock()) as rel:
        out = await nr.run_reclaim()

    assert out["warn1"] == 1
    assert mail.call_args.kwargs["final"] is False
    assert upd.call_args.args[1] == {"number_release_warn1_sent": True}
    rel.assert_not_called()


@pytest.mark.asyncio
async def test_a_db_failure_does_not_raise():
    with patch("db.supabase.get_client", side_effect=RuntimeError("db down")):
        out = await nr.run_reclaim()
    assert out["error"] is True
