"""Deferred Twilio operator-leg reconciliation: sums completed child-leg seconds and
backfills transfer_attempts.duration_secs (visibility only, never billed)."""
import pytest
from unittest.mock import AsyncMock

from services import transfer_reconcile as tr


def test_sum_completed_child_seconds_only_counts_completed():
    calls = [
        {"status": "completed", "duration": "18"},
        {"status": "completed", "duration": "42"},
        {"status": "in-progress", "duration": None},   # live leg -> 0
        {"status": "completed", "duration": None},      # missing -> 0
        {"status": "completed", "duration": "oops"},    # non-numeric -> 0
    ]
    assert tr.sum_completed_child_seconds(calls) == 60


def test_sum_completed_child_seconds_empty():
    assert tr.sum_completed_child_seconds([]) == 0
    assert tr.sum_completed_child_seconds(None) == 0


TENANT = {"id": "t1", "twilio_subaccount_sid": "ACsub", "twilio_auth_token": "tok"}


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(tr.db, "get_tenant_by_id", AsyncMock(return_value=dict(TENANT)))
    monkeypatch.setattr(tr, "get_tenant_vapi_key", lambda tenant: None)
    monkeypatch.setattr(tr, "get_call_details",
                        AsyncMock(return_value={"phoneCallProviderId": "CAinbound"}))
    setter = AsyncMock()
    monkeypatch.setattr(tr.rdb, "set_attempt_duration", setter)
    return monkeypatch, setter


@pytest.mark.asyncio
async def test_reconcile_backfills_duration_from_operator_leg(wired):
    mp, setter = wired
    mp.setattr(tr.rdb, "list_attempts_needing_duration",
               AsyncMock(return_value=[{"id": "a1", "tenant_id": "t1", "vapi_call_id": "vc1"}]))
    mp.setattr(tr, "_fetch_child_legs",
               AsyncMock(return_value=[{"status": "completed", "duration": "18"}]))
    out = await tr.reconcile_pending()
    assert out == {"candidates": 1, "updated": 1, "skipped": 0, "failed": 0}
    setter.assert_awaited_once_with("a1", 18)


@pytest.mark.asyncio
async def test_reconcile_skips_when_leg_not_completed_yet(wired):
    mp, setter = wired
    mp.setattr(tr.rdb, "list_attempts_needing_duration",
               AsyncMock(return_value=[{"id": "a1", "tenant_id": "t1", "vapi_call_id": "vc1"}]))
    mp.setattr(tr, "_fetch_child_legs",
               AsyncMock(return_value=[{"status": "in-progress", "duration": None}]))
    out = await tr.reconcile_pending()
    assert out["updated"] == 0 and out["skipped"] == 1
    setter.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_skips_when_no_twilio_subaccount(wired):
    mp, setter = wired
    mp.setattr(tr.db, "get_tenant_by_id", AsyncMock(return_value={"id": "t1"}))  # no sub creds
    mp.setattr(tr.rdb, "list_attempts_needing_duration",
               AsyncMock(return_value=[{"id": "a1", "tenant_id": "t1", "vapi_call_id": "vc1"}]))
    out = await tr.reconcile_pending()
    assert out["updated"] == 0 and out["skipped"] == 1
    setter.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_isolates_failures(wired):
    mp, setter = wired
    mp.setattr(tr.rdb, "list_attempts_needing_duration",
               AsyncMock(return_value=[{"id": "a1", "tenant_id": "t1", "vapi_call_id": "vc1"}]))
    mp.setattr(tr, "_fetch_child_legs", AsyncMock(side_effect=RuntimeError("twilio down")))
    out = await tr.reconcile_pending()
    assert out == {"candidates": 1, "updated": 0, "skipped": 0, "failed": 1}
