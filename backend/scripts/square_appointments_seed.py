#!/usr/bin/env python3
"""
P0 SEED — create a bookable Square Appointments setup via API.   THROWAWAY.

Solves the fiddly sandbox-dashboard steps by creating, against your SANDBOX account:
  1. A team member            -> POST /v2/team-members           (CreateTeamMember)
  2. Mon-Fri 9-5 location hours -> PUT  /v2/locations/{id}        (so availability isn't empty)
  3. A bookable service        -> POST /v2/catalog/object         (APPOINTMENTS_SERVICE, assigned to the member)
Then reports whether Appointments is enabled.

PREREQ: Appointments must be ON for the account (the one dashboard step that has no API).
        Set SQUARE_SANDBOX_ACCESS_TOKEN to the same test account's token (starts with EAAA).

RUN:
  cd backend
  export SQUARE_SANDBOX_ACCESS_TOKEN=EAAA...
  venv/bin/python scripts/square_appointments_seed.py
  # then:
  venv/bin/python scripts/square_appointments_spike.py --book --cancel
"""
from __future__ import annotations

import os
import sys
import uuid

import httpx

API_BASE = os.environ.get("SQUARE_API_BASE", "https://connect.squareupsandbox.com")
SQUARE_VERSION = os.environ.get("SQUARE_VERSION", "2024-11-20")
TOKEN = os.environ.get("SQUARE_SANDBOX_ACCESS_TOKEN") or os.environ.get("SQUARE_ACCESS_TOKEN")


def _client() -> httpx.Client:
    if not TOKEN:
        sys.exit("ERROR: set SQUARE_SANDBOX_ACCESS_TOKEN (sandbox token, starts with EAAA).")
    return httpx.Client(
        base_url=API_BASE,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Square-Version": SQUARE_VERSION,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def _call(c: httpx.Client, method: str, path: str, **kw) -> dict:
    r = c.request(method, path, **kw)
    if r.status_code >= 400:
        print(f"  !! {method} {path} -> {r.status_code}\n     {r.text[:800]}")
        r.raise_for_status()
    return r.json() if r.text else {}


def main() -> None:
    with _client() as c:
        # location + currency
        locs = _call(c, "GET", "/v2/locations").get("locations", [])
        if not locs:
            sys.exit("No locations on this account.")
        loc = locs[0]
        location_id, currency = loc["id"], loc.get("currency", "USD")
        print(f"location_id={location_id}  currency={currency}  tz={loc.get('timezone')}")

        # 1. team member -------------------------------------------------
        existing = _call(c, "POST", "/v2/team-members/search",
                         json={"query": {"filter": {"status": "ACTIVE"}}}).get("team_members", [])
        seeded = next((m for m in existing if m.get("given_name") == "Sam" and m.get("family_name") == "Barber"), None)
        if seeded:
            team_id = seeded["id"]
            print(f"team member already exists -> {team_id}")
        else:
            tm = _call(c, "POST", "/v2/team-members", json={
                "idempotency_key": str(uuid.uuid4()),
                "team_member": {
                    "given_name": "Sam", "family_name": "Barber", "status": "ACTIVE",
                    "assigned_locations": {"assignment_type": "ALL_CURRENT_AND_FUTURE_LOCATIONS"},
                },
            })["team_member"]
            team_id = tm["id"]
            print(f"created team member -> {team_id}")

        # 2. location business hours (Mon-Fri 9-5) -----------------------
        days = ["MON", "TUE", "WED", "THU", "FRI"]
        try:
            _call(c, "PUT", f"/v2/locations/{location_id}", json={"location": {"business_hours": {
                "periods": [{"day_of_week": d, "start_local_time": "09:00:00", "end_local_time": "17:00:00"} for d in days]
            }}})
            print("set location business hours Mon-Fri 09:00-17:00")
        except httpx.HTTPStatusError:
            print("  (could not set location hours via API — may need to set staff availability in dashboard)")

        # 3. bookable service assigned to the member ---------------------
        obj = _call(c, "POST", "/v2/catalog/object", json={
            "idempotency_key": str(uuid.uuid4()),
            "object": {
                "type": "ITEM", "id": "#haircut", "present_at_all_locations": True,
                "item_data": {
                    "name": "Haircut", "product_type": "APPOINTMENTS_SERVICE",
                    "variations": [{
                        "type": "ITEM_VARIATION", "id": "#haircut_std", "present_at_all_locations": True,
                        "item_variation_data": {
                            "item_id": "#haircut", "name": "Standard",
                            "pricing_type": "FIXED_PRICING",
                            "price_money": {"amount": 3000, "currency": currency},
                            "available_for_booking": True,
                            "service_duration": 1800000,          # 30 min in ms
                            "team_member_ids": [team_id],
                        },
                    }],
                },
            },
        })["catalog_object"]
        var = obj["item_data"]["variations"][0]
        print(f"created service 'Haircut / Standard'  variation={var['id']}  version={var.get('version')}  "
              f"assigned team={team_id}")

        # report Appointments status
        try:
            prof = _call(c, "GET", "/v2/bookings/business-booking-profile").get("business_booking_profile", {})
            print(f"\nbooking_enabled={prof.get('booking_enabled')}  "
                  f"(if False -> turn Appointments ON in the seller dashboard, then re-run the spike)")
        except httpx.HTTPStatusError:
            print("\n  booking profile unavailable — enable Appointments in the dashboard first.")

    print("\nDone. Now run:  venv/bin/python scripts/square_appointments_spike.py --book --cancel")


if __name__ == "__main__":
    main()
