"""Prove the usage ledger against real processes, Postgres and Stripe test mode.

    python scripts/usage_race_test.py

Reads ~/.openlines-test. Refuses the production project and any key but sk_test_, and
only touches tenants named "TEST race1", "TEST race2" and "TEST race3". Run after
applying migration 042 to the test project.
"""
import asyncio
import json
import os
import random
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
T = Path.home() / ".openlines-test"
PRODUCTION_REF = "gsylobklnpytitaqcley"


def load_env():
    ref = (T / "ref").read_text().strip()
    keys = {k.get("name"): k["api_key"] for k in json.loads((T / "api-keys.json").read_text())}
    stripe_env = dict(l.strip().split("=", 1) for l in (T / "stripe.env").read_text().splitlines() if "=" in l)
    ids = dict(l.strip().split("=", 1) for l in (T / "stripe-ids.env").read_text().splitlines() if "=" in l)
    secret = stripe_env["STRIPE_TEST_SECRET_KEY"]
    if ref == PRODUCTION_REF or not secret.startswith("sk_test_"):
        raise SystemExit("Refusing: this only runs on the test project with a test key.")
    os.environ.update({
        "SUPABASE_URL": f"https://{ref}.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": keys["service_role"],
        "STRIPE_SECRET_KEY": secret, "STRIPE_CALL_MINUTES_PRICE_ID": ids["STRIPE_CALL_MINUTES_PRICE_ID"],
        "APP_ENV": "test",
    })
    return ids


IDS = load_env()
sys.path.insert(0, str(ROOT))
import stripe  # noqa: E402

from db import supabase as db  # noqa: E402
from services import usage  # noqa: E402

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
USERS = json.loads((T / "test-users.json").read_text())


def iso(moment):
    return moment.isoformat()


def worker_calls(tenant, prefix, count, ended_at, secs, pause):
    async def run():
        for i in range(count):
            await usage.record_call_minutes(tenant, secs, call_id=f"{prefix}-{i}", ended_at=ended_at)
            if pause:
                await asyncio.sleep(random.random() * pause)
    asyncio.run(run())


def worker_crash(tenant, call_id, ended_at, secs, where):
    """Die for real at the worst moment."""
    if where == "after-stripe":
        db.usage_overage_reported = lambda *a, **k: os._exit(9)
    else:
        def die(*a, **k):
            os._exit(9)
        stripe.billing.MeterEvent.create = die
    asyncio.run(usage.record_call_minutes(tenant, secs, call_id=call_id, ended_at=ended_at))


def worker_no_id(tenant, ended_at):
    asyncio.run(usage.record_call_minutes(tenant, 60, call_id="", ended_at=ended_at))


def worker_retry():
    usage.OVERAGE_RETRY_AFTER = timedelta(0)
    print(json.dumps(asyncio.run(usage.retry_pending_overage())))


def spawn(*args):
    return subprocess.Popen([sys.executable, __file__, "--worker", *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


client = db.get_client()


def tenant_row(tid):
    return client.table("tenants").select("*").eq("id", tid).single().execute().data


def reset(tid, **fields):
    client.table("usage_events").delete().eq("tenant_id", tid).execute()
    client.table("usage_quarantine").delete().eq("tenant_id", tid).execute()
    client.table("tenants").update({
        "minutes_used_this_period": 0, "overage_minutes_reported": 0, "billing_exempt": False,
        "subscription_status": "active", "subscription_plan": "starter", "stripe_subscription_id": None,
        "stripe_customer_id": None, "paid_transition_expires_at": None, "paid_transition_subscription_id": None,
        "billing_period_anchor": fields.pop("anchor", None), "billing_period_started_at": fields.pop("started", None),
        **fields,
    }).eq("id", tid).execute()


def events(tid):
    return client.table("usage_events").select("*").eq("tenant_id", tid).execute().data


FAILED = []


def expect(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}", flush=True)
    if not ok:
        FAILED.append(name)


def concurrent_workers(tid):
    reset(tid)
    procs = [spawn("calls", tid, f"w{w}", 30, iso(datetime.now(timezone.utc)), 60, 0) for w in range(6)]
    shared = [spawn("calls", tid, "shared", 20, iso(datetime.now(timezone.utc)), 60, 0) for _ in range(3)]
    [p.wait() for p in procs + shared]
    got = tenant_row(tid)["minutes_used_this_period"]
    expect("9 processes, 3 retrying the same calls", got == 200 and len(events(tid)) == 200, f"{got} minutes, {len(events(tid))} rows of 200")


def kill_and_retry(tid):
    reset(tid)
    ended = iso(datetime.now(timezone.utc))
    procs = [spawn("calls", tid, f"k{w}", 40, ended, 60, 0.02) for w in range(5)]
    time.sleep(2.5)
    killed = 0
    for p in procs[:3]:
        if p.poll() is None:
            p.send_signal(signal.SIGKILL)
            killed += 1
    [p.wait() for p in procs]
    partial = tenant_row(tid)["minutes_used_this_period"]
    again = [spawn("calls", tid, f"k{w}", 40, ended, 60, 0) for w in range(5)]
    [p.wait() for p in again]
    got = tenant_row(tid)["minutes_used_this_period"]
    expect("kill -9 then retry everything", got == 200, f"{killed} killed, {partial} before retry, {got} after, of 200")


def rollover_race(tid, run):
    old = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    new = datetime(2026, 2, 1, 9, tzinfo=timezone.utc)
    reset(tid, anchor="2026-01-01", started=iso(old))
    # No Stripe lookup is possible here, which is the outage case.
    procs = [spawn("calls", tid, f"new{w}", 25, iso(new + timedelta(hours=1)), 60, 0.01) for w in range(4)]
    procs += [spawn("calls", tid, f"old{w}", 25, iso(new - timedelta(hours=1)), 60, 0.01) for w in range(2)]

    async def webhooks():
        await asyncio.sleep(random.random() * 2)
        return await asyncio.gather(*[db.usage_roll_period(tid, iso(new)) for _ in range(4)],
                                    db.usage_roll_period(tid, iso(old)))
    results = asyncio.run(webhooks())
    [p.wait() for p in procs]
    row = tenant_row(tid)
    resets = sum(1 for r in results if r["rolled"])
    expect(f"rollover race {run}", row["minutes_used_this_period"] == 100 and resets == 1,
           f"new-period minutes {row['minutes_used_this_period']} of 100, resets {resets}")


def missing_call_id(tid):
    reset(tid)
    ended = iso(datetime.now(timezone.utc))
    procs = [spawn("noid", tid, ended) for _ in range(3)]
    [p.wait() for p in procs]
    held = client.table("usage_quarantine").select("minutes, reason").eq("tenant_id", tid).execute().data
    row = tenant_row(tid)
    expect("3 processes, same call with no id", row["minutes_used_this_period"] == 0 and not events(tid) and len(held) == 3,
           f"counter {row['minutes_used_this_period']}, ledger {len(events(tid))}, quarantined {len(held)}")


def missing_end_time(tid):
    reset(tid)
    asyncio.run(usage.record_call_minutes(tid, 60, call_id="no-end", ended_at=None))
    rows = events(tid)
    expect("no end time", rows[0]["ended_at_estimated"] and tenant_row(tid)["minutes_used_this_period"] == 1, "recorded at processing time and flagged")


def duplicate_response():
    """Stripe's real errors, not a copy of them."""
    customer = stripe.Customer.create(name="Duplicate probe", email="race@openlines-test.example")
    identifier = f"ol-probe-{uuid.uuid4().hex}"
    event = dict(event_name="call_minutes", identifier=identifier, timestamp=int(time.time()),
                 payload={"value": "1", "stripe_customer_id": customer.id})
    stripe.billing.MeterEvent.create(**event)
    try:
        stripe.billing.MeterEvent.create(**event)
        expect("Stripe refuses a repeat", False, "no error raised")
    except stripe.InvalidRequestError as e:
        expect("Stripe's duplicate matches", usage._stripe_already_has(e, identifier), f"HTTP {e.http_status}, code {e.code}")
        expect("Same error, another identifier", not usage._stripe_already_has(e, identifier + "x"), "not treated as ours")
    try:
        stripe.billing.MeterEvent.create(event_name="", identifier=f"ol-probe-{uuid.uuid4().hex}", payload={"value": "1"})
    except stripe.InvalidRequestError as e:
        expect("Unrelated Stripe 400", not usage._stripe_already_has(e, identifier), f"HTTP {e.http_status}: stays pending")
    stripe.Customer.delete(customer.id)


def delayed_call(tid):
    new = datetime(2026, 2, 1, 9, tzinfo=timezone.utc)
    reset(tid, anchor="2026-02-01", started=iso(new))
    asyncio.run(usage.record_call_minutes(tid, 60, call_id="delayed", ended_at=iso(new - timedelta(minutes=5))))
    row, rows = tenant_row(tid), events(tid)
    expect("delayed old-period call", row["minutes_used_this_period"] == 0 and not rows[0]["counted"], "kept in the ledger, not charged to the new allowance")


def start_paid(tid):
    start = datetime(2026, 2, 1, 9, tzinfo=timezone.utc)
    reset(tid, anchor="2026-02-01")
    client.table("tenants").update({"minutes_used_this_period": 0}).eq("id", tid).execute()
    asyncio.run(usage.record_call_minutes(tid, 60, call_id="before", ended_at=iso(start - timedelta(minutes=1))))
    procs = [spawn("calls", tid, f"p{w}", 10, iso(start + timedelta(minutes=1)), 60, 0.01) for w in range(3)]
    time.sleep(1)
    result = asyncio.run(db.usage_roll_period(tid, iso(start), start_paid=True))
    [p.wait() for p in procs]
    repeat = asyncio.run(db.usage_roll_period(tid, iso(start), start_paid=True))
    got = tenant_row(tid)["minutes_used_this_period"]
    expect("trial conversion or paid start racing calls", got == 30 and result["rolled"] and not repeat["rolled"], f"{got} of 30 kept, same-day start worked, repeat did nothing")


def meter_total(meter, customer, start, wanted, seconds=900):
    end = start + timedelta(hours=2)
    deadline = time.time() + seconds
    total = None
    while time.time() < deadline:
        data = stripe.billing.Meter.list_event_summaries(
            meter, customer=customer, start_time=int(start.timestamp()), end_time=int(end.timestamp())).data
        total = sum(s.aggregated_value for s in data)
        print(f"      meter reads {total}", flush=True)
        if total >= wanted:
            # Give any double count time to land too.
            time.sleep(90)
            data = stripe.billing.Meter.list_event_summaries(
                meter, customer=customer, start_time=int(start.timestamp()), end_time=int(end.timestamp())).data
            return sum(s.aggregated_value for s in data)
        time.sleep(15)
    return total


def overage_crash(tid):
    price = stripe.Price.retrieve(IDS["STRIPE_CALL_MINUTES_PRICE_ID"])
    meter = price.recurring.meter
    customer = stripe.Customer.create(name="Usage crash test", email="race@openlines-test.example", payment_method="pm_card_visa",
                                      metadata={"tenant_id": tid})
    pm = stripe.PaymentMethod.list(customer=customer.id, type="card").data[0].id
    stripe.Customer.modify(customer.id, invoice_settings={"default_payment_method": pm})
    sub = stripe.Subscription.create(customer=customer.id, items=[{"price": IDS["STRIPE_PRICE_STARTER"]}, {"price": price.id}])
    started = datetime.fromtimestamp(sub.current_period_start, tz=timezone.utc)
    reset(tid, stripe_customer_id=customer.id, stripe_subscription_id=sub.id, started=iso(started), anchor=started.date().isoformat())
    client.table("tenants").update({"minutes_used_this_period": 150}).eq("id", tid).execute()

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    ended = iso(datetime.now(timezone.utc))
    # 7 minutes dies after Stripe accepts; 5 minutes dies before Stripe is called.
    # Identifiers stay unique at Stripe for at least a day, so each run needs its own.
    after, before = f"after-{uuid.uuid4().hex}", f"before-{uuid.uuid4().hex}"
    spawn("crash", tid, after, ended, 420, "after-stripe").wait()
    spawn("crash", tid, before, ended, 300, "before-stripe").wait()
    rows = {e["call_id"]: e for e in events(tid)}
    expect("crashes left work pending", rows[after]["overage_state"] == "pending" and rows[before]["overage_state"] == "pending",
           f"after-stripe {rows[after]['overage_minutes']} min, before-stripe {rows[before]['overage_minutes']} min")

    outs = [spawn("retry") for _ in range(4)]
    [p.wait() for p in outs]
    states = [e["overage_state"] for e in events(tid)]
    expect("4 workers retry at once", states == ["reported", "reported"], str(states))
    row = tenant_row(tid)
    expect("reported total", row["overage_minutes_reported"] == 12, f"{row['overage_minutes_reported']} of 12")

    total = meter_total(meter, customer.id, now, 12)
    expect("Stripe's own meter total", total == 12, f"{total} of 12: the crashed call was not billed twice")
    invoice = stripe.Invoice.create_preview(subscription=sub.id, customer=customer.id)
    metered = [line.quantity for line in invoice.lines.data if "0.69" in line.description]
    expect("Stripe's next invoice", metered == [12], f"{metered} metered minutes")

    stripe.Subscription.cancel(sub.id)
    stripe.Customer.delete(customer.id)
    reset(tid)


def main():
    a, b = USERS["race1"]["id"], USERS["race2"]["id"]
    if "--overage-only" in sys.argv:
        overage_crash(b)
        return 1 if FAILED else 0
    concurrent_workers(a)
    kill_and_retry(a)
    for run in range(1, 4):
        rollover_race(a, run)
    delayed_call(a)
    start_paid(a)
    missing_call_id(a)
    missing_end_time(a)
    duplicate_response()
    overage_crash(b)
    reset(a)
    return 1 if FAILED else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        kind, *rest = sys.argv[2:]
        if kind == "calls":
            worker_calls(rest[0], rest[1], int(rest[2]), rest[3], int(rest[4]), float(rest[5]))
        elif kind == "crash":
            worker_crash(rest[0], rest[1], rest[2], int(rest[3]), rest[4])
        elif kind == "noid":
            worker_no_id(rest[0], rest[1])
        elif kind == "retry":
            worker_retry()
    else:
        sys.exit(main())
