"""Hammer the usage functions on a real database, to prove what a fake can't.

    python scripts/usage_race_test.py

Reads ~/.openlines-test, refuses the production project, and only touches a tenant
named "TEST race1". Run after applying migration 042 to the test project.
"""
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PRODUCTION_REF = "gsylobklnpytitaqcley"
T = Path.home() / ".openlines-test"


def main() -> int:
    ref = (T / "ref").read_text().strip()
    if ref == PRODUCTION_REF:
        raise SystemExit("Refusing to run against production.")
    key = next(k["api_key"] for k in json.loads((T / "api-keys.json").read_text()) if k.get("name") == "service_role")
    tenant = json.loads((T / "test-users.json").read_text())["race1"]["id"]
    base = f"https://{ref}.supabase.co/rest/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "content-type": "application/json"}

    def http(method, url, body=None, retries=4):
        request = Request(url, method=method, headers=headers, data=json.dumps(body).encode() if body is not None else None)
        for attempt in range(retries):
            try:
                with urlopen(request, timeout=30) as r:
                    text = r.read()
                return json.loads(text) if text else None
            except HTTPError as e:
                if e.code < 500 or attempt == retries - 1:
                    raise

    row_url = f"{base}/tenants?id=eq.{tenant}"
    assert http("GET", row_url + "&select=business_name")[0]["business_name"] == "TEST race1"

    def state(minutes=0, anchor="2026-01-01"):
        http("PATCH", row_url, {"minutes_used_this_period": minutes, "overage_minutes_reported": 0, "billing_period_anchor": anchor})

    def read():
        return http("GET", row_url + "&select=minutes_used_this_period,overage_minutes_reported,billing_period_anchor")[0]

    def add(minutes=1, anchor=None):
        return http("POST", f"{base}/rpc/usage_add_minutes", {"p_tenant_id": tenant, "p_minutes": minutes, "p_period_anchor": anchor})[0]

    def roll(anchor):
        return http("POST", f"{base}/rpc/usage_roll_period", {"p_tenant_id": tenant, "p_period_anchor": anchor})[0]

    failures = []

    def expect(name, ok, detail):
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(name)

    with ThreadPoolExecutor(40) as pool:
        state()
        list(pool.map(lambda _: add(), range(200)))
        got = read()["minutes_used_this_period"]
        expect("concurrent calls", got == 200, f"200 one-minute calls recorded {got}")

        for run in range(5):
            # Calls that know the new period, racing duplicate and stale webhooks.
            state(minutes=100)
            jobs = [("add", "2026-02-01")] * 60 + [("roll", "2026-02-01")] * 8 + [("roll", "2026-01-01")] * 4
            random.shuffle(jobs)
            results = list(pool.map(lambda j: add(1, j[1]) if j[0] == "add" else roll(j[1]), jobs))
            end = read()
            rolls = sum(1 for r in results if r.get("rolled"))
            ok = end["minutes_used_this_period"] == 60 and end["billing_period_anchor"] == "2026-02-01" and rolls == 1
            expect(f"rollover race {run + 1}", ok, f"60 new-period calls recorded {end['minutes_used_this_period']}, resets {rolls}")

        for run in range(3):
            # A webhook racing calls that don't know yet: every minute is either cleared
            # with the old period or kept, never lost between the two.
            state(minutes=100)
            jobs = ["add"] * 60 + ["roll"]
            random.shuffle(jobs)
            results = list(pool.map(lambda j: add() if j == "add" else roll("2026-02-01"), jobs))
            cleared = next(r["cleared_minutes"] for r in results if "cleared_minutes" in r)
            kept = read()["minutes_used_this_period"]
            expect(f"accounting {run + 1}", cleared + kept == 160, f"{cleared} cleared + {kept} kept of 160")

    state()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
