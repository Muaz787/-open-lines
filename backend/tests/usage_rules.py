"""An in-memory copy of migration 042's rules, for tests that don't need Postgres.

It can't prove locking. backend/scripts/usage_race_test.py does that against a real
database.
"""
from datetime import datetime, timezone
from unittest.mock import patch


def when(text):
    value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class UsageRow:
    def __init__(self, row: dict):
        self.row = row
        self.events: dict[str, dict] = row.setdefault("_events", {})

    def _start(self):
        row = self.row
        if row.get("billing_period_started_at"):
            return when(row["billing_period_started_at"])
        return when(row["billing_period_anchor"] + "T00:00:00+00:00") if row.get("billing_period_anchor") else None

    def _moved(self, new):
        row = self.row
        if row.get("billing_period_started_at"):
            return when(new) > when(row["billing_period_started_at"])
        anchor = row.get("billing_period_anchor")
        return bool(anchor) and when(new).date().isoformat() > anchor

    def _enter(self, start):
        row, begin = self.row, when(start)
        cleared = row.get("minutes_used_this_period") or 0
        kept = [e for e in self.events.values() if when(e["ended_at"]) >= begin]
        for e in kept:
            e["counted"] = True
            if e["state"] == "pending":
                e.update(overage=0, state="none")
        row["minutes_used_this_period"] = sum(e["minutes"] for e in kept)
        row["overage_minutes_reported"] = sum(e["overage"] for e in kept if e["state"] == "reported")
        row["billing_period_started_at"] = start
        row["billing_period_anchor"] = begin.date().isoformat()
        return cleared - row["minutes_used_this_period"]

    async def record(self, _tenant_id, call_id, minutes, ended_at, period_start, allowance, estimated=False):
        row = self.row
        if call_id in self.events:
            return {"minutes_used": row.get("minutes_used_this_period") or 0, "overage_minutes": 0,
                    "duplicate": True, "counted": False, "rolled": False}
        rolled = False
        if period_start:
            if self._moved(period_start):
                self._enter(period_start)
                rolled = True
            elif not row.get("billing_period_started_at"):
                row["billing_period_started_at"] = period_start
                row["billing_period_anchor"] = when(period_start).date().isoformat()
        start = self._start()
        counted = start is None or when(ended_at) >= start
        previous = row.get("minutes_used_this_period") or 0
        total = previous + minutes if counted else previous
        overage = 0
        if counted and allowance is not None:
            overage = max(0, total - allowance) - max(0, previous - allowance)
        self.events[call_id] = {"minutes": minutes, "ended_at": ended_at, "estimated": estimated, "counted": counted, "overage": overage,
                                "state": "pending" if overage > 0 else "none"}
        row["minutes_used_this_period"] = total
        return {"minutes_used": total, "overage_minutes": overage, "duplicate": False, "counted": counted, "rolled": rolled}

    async def roll(self, _tenant_id, period_start, start_paid=False):
        row = self.row
        moved = self._moved(period_start) or (start_paid and (
            not row.get("billing_period_started_at") or when(period_start) > when(row["billing_period_started_at"])))
        if moved:
            return {"rolled": True, "cleared_minutes": self._enter(period_start)}
        if not row.get("billing_period_started_at") and not row.get("billing_period_anchor"):
            row["billing_period_started_at"] = period_start
            row["billing_period_anchor"] = when(period_start).date().isoformat()
        return {"rolled": False, "cleared_minutes": 0}

    async def reported(self, _tenant_id, call_id):
        event = self.events.get(call_id)
        if event and event["state"] == "pending":
            event["state"] = "reported"
            start = self._start()
            if start is None or when(event["ended_at"]) >= start:
                self.row["overage_minutes_reported"] = (self.row.get("overage_minutes_reported") or 0) + event["overage"]

    def patches(self):
        return (patch("db.supabase.usage_record_call", new=self.record),
                patch("db.supabase.usage_roll_period", new=self.roll),
                patch("db.supabase.usage_overage_reported", new=self.reported))
