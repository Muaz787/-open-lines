"""Compare usage counters with call history. Read-only: it never writes or bills.

    python scripts/usage_reconcile_report.py [--env PATH] [--out PATH]

For each tenant it adds up the calls in the stored billing period, rounded up per call
as billing does, and compares that with the counter. A difference is a question for a
person, not a correction: calls on free test lines and calls from before tracking began
can differ legitimately. See docs/usage-ledger.md.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

parser = argparse.ArgumentParser()
parser.add_argument("--env", default=str(Path(__file__).resolve().parent.parent / ".env"))
parser.add_argument("--out")
args = parser.parse_args()
load_dotenv(args.env)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.supabase import get_client  # noqa: E402

client = get_client()


def table_or_empty(name, columns):
    try:
        return client.table(name).select(columns).limit(100000).execute().data or []
    except Exception:
        return []


tenants = client.table("tenants").select(
    "id, subscription_status, stripe_subscription_id, billing_exempt, minutes_used_this_period, "
    "overage_minutes_reported, billing_period_anchor").execute().data
calls = client.table("calls").select("tenant_id, duration_secs, created_at").limit(100000).execute().data
ledger = table_or_empty("usage_events", "tenant_id, minutes, ended_at, counted, overage_state")

rows = []
for t in tenants:
    anchor = t.get("billing_period_anchor")
    start = datetime.fromisoformat(f"{anchor}T00:00:00+00:00") if anchor else None
    mine = [c for c in calls if c["tenant_id"] == t["id"] and (c.get("duration_secs") or 0) > 0]
    in_period = [c for c in mine if not start or datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")) >= start]
    expected = sum(max(1, math.ceil(c["duration_secs"] / 60)) for c in in_period)
    counter = t.get("minutes_used_this_period") or 0
    events = [e for e in ledger if e["tenant_id"] == t["id"]]
    rows.append({
        "tenant": t["id"], "status": t.get("subscription_status"), "has_subscription": bool(t.get("stripe_subscription_id")),
        "comped": bool(t.get("billing_exempt")), "anchor": anchor, "counter_minutes": counter,
        "calls_in_period": len(in_period), "history_minutes": expected, "difference": counter - expected,
        "overage_reported": t.get("overage_minutes_reported") or 0, "ledger_rows": len(events),
        "ledger_pending": sum(1 for e in events if e["overage_state"] == "pending"),
    })

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(), "tenants": len(rows),
    "matching": sum(1 for r in rows if r["difference"] == 0),
    "counter_higher": sum(1 for r in rows if r["difference"] > 0),
    "counter_lower": sum(1 for r in rows if r["difference"] < 0),
    "with_overage_reported": sum(1 for r in rows if r["overage_reported"]),
    "live_subscription_with_anchor": sum(1 for r in rows if r["has_subscription"] and r["anchor"] and r["status"] in ("active", "trialing", "past_due", "canceling")),
    "ledger_available": bool(ledger), "ledger_pending": sum(r["ledger_pending"] for r in rows),
}
print(json.dumps(summary, indent=1))
if args.out:
    Path(args.out).write_text(json.dumps({"summary": summary, "tenants": rows}, indent=1))
