"""The shared period definition, including the boundaries that break naive date maths."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from routers import calls as calls_router
from routers import leads
from routers.leads import _period_window
from services import date_ranges

TORONTO = ZoneInfo("America/Toronto")
ST_JOHNS = ZoneInfo("America/St_Johns")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_seven_days_is_today_plus_the_six_before_it():
    now = utc(2026, 10, 30, 16, 0)     # noon in Toronto
    assert date_ranges.period_start(7, TORONTO, now) == utc(2026, 10, 24, 4, 0)


def test_today_starts_at_local_midnight_not_utc_midnight():
    now = utc(2026, 10, 31, 2, 0)      # still Oct 30, 10pm in Toronto
    assert date_ranges.period_start(1, TORONTO, now) == utc(2026, 10, 30, 4, 0)


def test_a_call_just_after_local_midnight_is_today():
    now = utc(2026, 10, 31, 12, 0)
    start = date_ranges.period_start(1, TORONTO, now)
    assert start <= utc(2026, 10, 31, 4, 1)
    assert not start <= utc(2026, 10, 31, 3, 59)


def test_window_crossing_the_clock_change_keeps_local_midnight():
    # Toronto left daylight time on Sunday 1 November 2026.
    now = utc(2026, 11, 3, 17, 0)
    start = date_ranges.period_start(7, TORONTO, now)
    assert start == utc(2026, 10, 28, 4, 0)     # midnight EDT, not EST
    assert date_ranges.day_index(utc(2026, 11, 3, 5, 30), start, TORONTO) == 6


def test_spring_forward_keeps_seven_calendar_days():
    now = utc(2026, 3, 10, 16, 0)
    start = date_ranges.period_start(7, TORONTO, now)
    assert start == utc(2026, 3, 4, 5, 0)       # midnight EST
    assert date_ranges.day_index(now, start, TORONTO) == 6


def test_half_hour_zone():
    now = utc(2026, 10, 30, 12, 0)
    assert date_ranges.period_start(1, ST_JOHNS, now) == utc(2026, 10, 30, 2, 30)


def test_today_buckets_cover_a_25_hour_day():
    now = utc(2026, 11, 2, 4, 30)      # 11:30pm on the fall-back day in Toronto
    start, buckets, index = _period_window("today", TORONTO, now)
    assert start == utc(2026, 11, 1, 4, 0)
    assert buckets == 25
    assert index(now) == 24


def test_seven_day_buckets_use_local_days():
    now = utc(2026, 10, 30, 16, 0)
    start, buckets, index = _period_window("7d", TORONTO, now)
    assert buckets == 7
    assert index(utc(2026, 10, 25, 3, 0)) == 0  # 11pm on the 24th, locally
    assert index(utc(2026, 10, 25, 4, 0)) == 1  # midnight on the 25th, locally


def test_bad_or_missing_timezone_falls_back_to_utc():
    assert str(date_ranges.tenant_zone({"calendar_timezone": "Mars/Base"})) == "UTC"
    assert str(date_ranges.tenant_zone({})) == "UTC"
    assert str(date_ranges.tenant_zone({"calendar_timezone": "America/Toronto"})) == "America/Toronto"


@pytest.mark.asyncio
async def test_overview_and_call_history_use_the_same_window(monkeypatch):
    """The reason 7d showed 2 on the overview and 4 in Calls: one started at UTC
    midnight six days ago, the other a rolling 7 x 24 hours back."""
    tenant = {"calendar_timezone": "America/Toronto"}
    seen = {}

    async def stats_sql(_tenant_id, start_iso, _bucket):
        seen["overview"] = start_iso
        return []

    async def calls(_tenant_id, since=None, limit=100):
        seen.setdefault("history", since.isoformat())
        return []

    monkeypatch.setattr(leads.db, "get_tenant_by_id", AsyncMock(return_value=tenant))
    monkeypatch.setattr(leads, "_stats_series_sql", stats_sql)
    monkeypatch.setattr(calls_router.db, "get_calls_with_leads", calls)

    await leads.get_stats("t1", "7d")
    await calls_router.list_calls("t1", days=7)
    await calls_router.get_analytics("t1", days=7)
    assert seen["overview"] == seen["history"]


@pytest.mark.asyncio
async def test_all_calls_has_no_start(monkeypatch):
    captured = []

    async def calls(_tenant_id, since=None, limit=100):
        captured.append(since)
        return []

    monkeypatch.setattr(calls_router.db, "get_tenant_by_id", AsyncMock(return_value={}))
    monkeypatch.setattr(calls_router.db, "get_calls_with_leads", calls)
    await calls_router.list_calls("t1", days=0)
    assert captured == [None]
