"""An in-memory copy of migration 042's rules, for tests that don't need Postgres.

It can't prove locking. backend/scripts/usage_race_test.py does that against a real
database.
"""
from unittest.mock import patch


class UsageRow:
    def __init__(self, row: dict):
        self.row = row

    async def add(self, _tenant_id, minutes, anchor):
        row = self.row
        stored = row.get("billing_period_anchor")
        rolled = bool(anchor and stored and anchor > stored)
        row["minutes_used_this_period"] = minutes if rolled else (row.get("minutes_used_this_period") or 0) + minutes
        if rolled:
            row["overage_minutes_reported"] = 0
        if anchor and (not stored or rolled):
            row["billing_period_anchor"] = anchor
        return {"minutes_used": row["minutes_used_this_period"], "overage_reported": row.get("overage_minutes_reported") or 0,
                "period_anchor": row.get("billing_period_anchor"), "rolled": rolled}

    async def roll(self, _tenant_id, anchor):
        row = self.row
        stored = row.get("billing_period_anchor")
        if not stored:
            row["billing_period_anchor"] = anchor
            return {"rolled": False, "anchored": True, "cleared_minutes": 0}
        if anchor > stored:
            cleared = row.get("minutes_used_this_period") or 0
            row.update(minutes_used_this_period=0, overage_minutes_reported=0, billing_period_anchor=anchor)
            return {"rolled": True, "anchored": False, "cleared_minutes": cleared}
        return {"rolled": False, "anchored": False, "cleared_minutes": 0}

    async def add_overage(self, _tenant_id, minutes, anchor):
        if self.row.get("billing_period_anchor") == anchor:
            self.row["overage_minutes_reported"] = (self.row.get("overage_minutes_reported") or 0) + minutes

    def patches(self):
        return (patch("db.supabase.usage_add_minutes", new=self.add),
                patch("db.supabase.usage_roll_period", new=self.roll),
                patch("db.supabase.usage_add_overage_reported", new=self.add_overage))
