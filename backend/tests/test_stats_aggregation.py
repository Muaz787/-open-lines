"""
GET /leads/{tenant_id}/stats aggregates in SQL (tenant_stats_series) and keeps a
Python row-counting fallback for when the function isn't deployed yet. These pin
the contract that matters: the two paths return byte-identical output for the same
data, and the fallback triggers only on a missing function, never on empty data.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from routers import leads


class _Builder:
    def __init__(self, data):
        self._data = data
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self): return SimpleNamespace(data=self._data)


class _Rpc:
    def __init__(self, data, exc):
        self._data, self._exc = data, exc
    def execute(self):
        if self._exc:
            raise self._exc
        return SimpleNamespace(data=self._data)


class _Client:
    """Fake Supabase client. table() serves raw rows (fallback path); rpc() serves
    pre-grouped buckets, or raises to simulate the function being absent."""
    def __init__(self, tables=None, rpc_data=None, rpc_exc=None):
        self._tables = tables or {}
        self._rpc_data, self._rpc_exc = rpc_data, rpc_exc
    def table(self, name): return _Builder(self._tables.get(name, []))
    def rpc(self, name, params): return _Rpc(self._rpc_data, self._rpc_exc)


def _rows_and_buckets(period):
    """Synthetic data safely inside buckets, plus the grouping the SQL function
    would produce for it (truncate to hour for 'today', day otherwise)."""
    start, _, _ = leads._period_window(period)
    step = timedelta(hours=1) if period == "today" else timedelta(days=1)
    trunc = ((lambda d: d.replace(minute=0, second=0, microsecond=0)) if period == "today"
             else (lambda d: d.replace(hour=0, minute=0, second=0, microsecond=0)))

    # (offset_units, n_calls, secs_each, n_leads, n_appts)
    plan = [(0, 2, 60, 1, 0), (1, 0, 0, 3, 2), (2, 5, 30, 0, 1)]
    calls, lead_rows, appts = [], [], []
    buckets = {}
    for k, nc, secs, nl, na in plan:
        ts = start + step * k + (timedelta(minutes=20) if period != "today" else timedelta(minutes=20))
        iso = ts.isoformat()
        b = trunc(ts).isoformat()
        for _ in range(nc):
            calls.append({"created_at": iso, "duration_secs": secs})
        for _ in range(nl):
            lead_rows.append({"created_at": iso})
        for _ in range(na):
            appts.append({"created_at": iso})
        if nc:
            buckets[("calls", b)] = {"metric": "calls", "bucket_start": b, "cnt": nc, "secs": nc * secs}
        if nl:
            buckets[("leads", b)] = {"metric": "leads", "bucket_start": b, "cnt": nl, "secs": 0}
        if na:
            buckets[("appts", b)] = {"metric": "appts", "bucket_start": b, "cnt": na, "secs": 0}
    return {"calls": calls, "leads": lead_rows, "appointments": appts}, list(buckets.values())


@pytest.mark.parametrize("period", ["today", "7d", "30d"])
async def test_sql_and_python_paths_agree(monkeypatch, period):
    tables, grouped = _rows_and_buckets(period)

    monkeypatch.setattr(leads.db, "get_client", lambda: _Client(rpc_data=grouped))
    via_sql = await leads.get_stats("t1", period)

    missing_fn = Exception("PGRST202 function not found")
    monkeypatch.setattr(leads.db, "get_client",
                        lambda: _Client(tables=tables, rpc_exc=missing_fn))
    via_python = await leads.get_stats("t1", period)

    assert via_sql == via_python
    # And the numbers are actually right, not merely equal to each other.
    assert via_sql["total_calls"] == 7
    assert via_sql["total_leads"] == 4
    assert via_sql["appointments_booked"] == 3
    assert via_sql["minutes_handled"] == round((2 * 60 + 5 * 30) / 60)


async def test_empty_sql_result_is_not_a_fallback(monkeypatch):
    """A tenant with no data returns [] from the function; that is zeros, and must
    NOT fall through to the row-counting path."""
    calls = {"n": 0}
    real_table = _Client().table
    client = _Client(rpc_data=[])

    def counting_table(name):
        calls["n"] += 1
        return real_table(name)
    client.table = counting_table

    monkeypatch.setattr(leads.db, "get_client", lambda: client)
    out = await leads.get_stats("t1", "7d")
    assert calls["n"] == 0, "empty SQL result must not trigger the row-fetch fallback"
    assert out["total_calls"] == 0 and out["series"]["calls"] == [0] * 7


async def test_missing_function_falls_back_to_row_counting(monkeypatch):
    tables, _ = _rows_and_buckets("7d")
    monkeypatch.setattr(leads.db, "get_client",
                        lambda: _Client(tables=tables, rpc_exc=Exception("PGRST202")))
    out = await leads.get_stats("t1", "7d")
    assert out["total_calls"] == 7 and out["total_leads"] == 4
