#!/usr/bin/env python3
"""
P0 SPIKE — Square Appointments (Bookings API) feasibility check.   THROWAWAY.

Goal: de-risk the integration before we build it, by exercising the real
Square Bookings API against a SANDBOX account:

  1. Locations            -> GET  /v2/locations
  2. Booking profile      -> GET  /v2/bookings/business-booking-profile   (is Appointments on?)
  3. Service catalog      -> POST /v2/catalog/search   (APPOINTMENTS_SERVICE variations + VERSION)
  4. Team members         -> POST /v2/team-members/search (ACTIVE)
  5. Availability          -> POST /v2/bookings/availability/search   (does Square compute slots? 32-day window?)
  6. (optional --book)    -> find/create customer + POST /v2/bookings   (CreateBooking round-trip + idempotency)
  7. (optional --cancel)  -> POST /v2/bookings/{id}/cancel              (clean up the test booking)

This does NOT touch our app code, DB, or OAuth. It only reads SQUARE_SANDBOX_ACCESS_TOKEN.

SETUP (one-time, in the Square *sandbox* you already have):
  - Square Developer Dashboard -> your app -> Sandbox -> open a Test Account's Seller Dashboard
  - Enable **Appointments**, add ONE service and ONE team member (assign the member to the service)
  - Copy that test account's **Sandbox Access token**
  - export SQUARE_SANDBOX_ACCESS_TOKEN=EAAA...           (sandbox token, starts with EAAA)

RUN:
  python scripts/square_appointments_spike.py              # read-only (safe)
  python scripts/square_appointments_spike.py --book       # also creates a test booking
  python scripts/square_appointments_spike.py --book --cancel   # creates then cancels it

Notes:
  - A sandbox access token has full permissions, so this validates API *mechanics*, not
    OAuth scope granularity (esp. APPOINTMENTS_ALL_WRITE for managing other staff's calendars).
    That gets validated in P1 with a real OAuth token requesting specific scopes.
"""
from __future__ import annotations

import os
import sys
import uuid
import argparse
from datetime import datetime, timedelta, timezone

import httpx

API_BASE = os.environ.get("SQUARE_API_BASE", "https://connect.squareupsandbox.com")
SQUARE_VERSION = os.environ.get("SQUARE_VERSION", "2024-11-20")
TOKEN = os.environ.get("SQUARE_SANDBOX_ACCESS_TOKEN") or os.environ.get("SQUARE_ACCESS_TOKEN")


def _client() -> httpx.Client:
    if not TOKEN:
        sys.exit("ERROR: set SQUARE_SANDBOX_ACCESS_TOKEN (sandbox access token, starts with EAAA).")
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
        print(f"  !! {method} {path} -> {r.status_code}")
        print(f"     {r.text[:800]}")
        r.raise_for_status()
    return r.json() if r.text else {}


def hr(title: str) -> None:
    print("\n" + "=" * 70 + f"\n  {title}\n" + "=" * 70)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", action="store_true", help="also create a test booking")
    ap.add_argument("--cancel", action="store_true", help="cancel the booking created by --book")
    ap.add_argument("--days", type=int, default=14, help="availability window (<=32)")
    args = ap.parse_args()
    findings: list[str] = []

    with _client() as c:
        # 1. LOCATIONS ----------------------------------------------------
        hr("1. Locations")
        locs = _call(c, "GET", "/v2/locations").get("locations", [])
        if not locs:
            sys.exit("No locations on this account.")
        loc = locs[0]
        location_id = loc["id"]
        location_tz = loc.get("timezone", "UTC")
        print(f"  location_id={location_id}  name={loc.get('name')}  tz={location_tz}  "
              f"currency={loc.get('currency')}  ({len(locs)} total)")
        findings.append(f"location: {loc.get('name')} ({location_tz}); {len(locs)} location(s)")

        # 2. BOOKING PROFILE — is Appointments enabled? -------------------
        hr("2. Business booking profile")
        try:
            prof = _call(c, "GET", "/v2/bookings/business-booking-profile").get("business_booking_profile", {})
            booking_enabled = prof.get("booking_enabled")
            print(f"  booking_enabled={booking_enabled}  "
                  f"customer_timezone_choice={prof.get('customer_timezone_choice')}  "
                  f"booking_policy={prof.get('booking_policy')}  "
                  f"allow_user_cancel={prof.get('allow_user_cancel')}")
            findings.append(f"booking_enabled={booking_enabled} (Appointments {'ON' if booking_enabled else 'OFF'})")
            if not booking_enabled:
                print("  >> Appointments is OFF for this account. Enable it in the seller dashboard, "
                      "add a service + team member, then re-run.")
        except httpx.HTTPStatusError:
            findings.append("booking profile call FAILED (scope or Appointments not enabled)")

        # 3. CATALOG — appointment services + their VERSION ---------------
        hr("3. Service catalog (APPOINTMENTS_SERVICE)")
        body = {"object_types": ["ITEM"], "include_related_objects": False}
        objs = _call(c, "POST", "/v2/catalog/search", json=body).get("objects", [])
        services = []  # (variation_id, version, name, duration_min, team_ids, bookable)
        for o in objs:
            item = o.get("item_data", {})
            if item.get("product_type") != "APPOINTMENTS_SERVICE":
                continue
            for v in item.get("variations", []):
                vd = v.get("item_variation_data", {})
                dur_ms = vd.get("service_duration") or 0
                services.append((
                    v["id"],
                    v.get("version"),                       # <-- needed by CreateBooking
                    f"{item.get('name')} / {vd.get('name')}",
                    int(dur_ms) // 60000 if dur_ms else None,
                    vd.get("team_member_ids") or [],
                    vd.get("available_for_booking"),
                ))
        if not services:
            print("  (no APPOINTMENTS_SERVICE items found — add a service in the seller dashboard)")
        for s in services:
            print(f"  variation={s[0]}  version={s[1]}  '{s[2]}'  dur={s[3]}min  "
                  f"bookable={s[5]}  team={s[4]}")
        findings.append(f"{len(services)} bookable service variation(s); each carries a `version` "
                        f"({'present' if services and services[0][1] is not None else 'MISSING?'})")

        # 4. TEAM MEMBERS -------------------------------------------------
        hr("4. Team members (ACTIVE)")
        tbody = {"query": {"filter": {"status": "ACTIVE"}}}
        members = _call(c, "POST", "/v2/team-members/search", json=tbody).get("team_members", [])
        for m in members:
            print(f"  team_member={m['id']}  {m.get('given_name','')} {m.get('family_name','')}  "
                  f"is_owner={m.get('is_owner')}")
        findings.append(f"{len(members)} active team member(s)")

        if not services or not members:
            print("\n>> Need at least one bookable service AND one team member to test availability. Stopping.")
            _summary(findings)
            return

        # pick a service + the team members allowed to perform it
        var_id, var_version, var_name, dur_min, allowed_team, _ = services[0]
        team_ids = allowed_team or [m["id"] for m in members]

        # 5. AVAILABILITY — does Square compute the slots for us? ---------
        hr(f"5. Availability  (service='{var_name}', next {args.days} days)")
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(days=min(args.days, 32))
        abody = {"query": {"filter": {
            "start_at_range": {
                "start_at": start.isoformat().replace("+00:00", "Z"),
                "end_at": end.isoformat().replace("+00:00", "Z"),
            },
            "location_id": location_id,
            "segment_filters": [{
                "service_variation_id": var_id,
                "team_member_id_filter": {"any": team_ids},
            }],
        }}}
        avails = _call(c, "POST", "/v2/bookings/availability/search", json=abody).get("availabilities", [])
        print(f"  {len(avails)} slots returned by Square (it computed these from staff schedules + bookings)")
        for a in avails[:8]:
            seg = (a.get("appointment_segments") or [{}])[0]
            print(f"    {a.get('start_at')}  team={seg.get('team_member_id')}  "
                  f"dur={seg.get('duration_minutes')}  ver={seg.get('service_variation_version')}")
        findings.append(f"SearchAvailability returned {len(avails)} slot(s) — Square owns availability logic")

        # try to provoke the 32-day window limit for documentation
        try:
            bad = {"query": {"filter": {
                "start_at_range": {
                    "start_at": start.isoformat().replace("+00:00", "Z"),
                    "end_at": (start + timedelta(days=40)).isoformat().replace("+00:00", "Z"),
                },
                "location_id": location_id,
                "segment_filters": [{"service_variation_id": var_id, "team_member_id_filter": {"any": team_ids}}],
            }}}
            _call(c, "POST", "/v2/bookings/availability/search", json=bad)
            findings.append("40-day window did NOT error (window limit may differ from 32)")
        except httpx.HTTPStatusError:
            findings.append("confirmed: availability window > ~32 days is rejected (must chunk)")

        # 6. CREATE BOOKING ----------------------------------------------
        booking_id = None
        if args.book and avails:
            hr("6. CreateBooking round-trip")
            slot = avails[0]
            seg = (slot.get("appointment_segments") or [{}])[0]

            # find-or-create a sandbox customer (valid E.164; 555 area code is rejected by Square)
            phone = "+12128675309"
            cust = _call(c, "POST", "/v2/customers/search",
                         json={"query": {"filter": {"phone_number": {"exact": phone}}}}).get("customers", [])
            if cust:
                customer_id = cust[0]["id"]
                print(f"  found customer {customer_id}")
            else:
                customer_id = _call(c, "POST", "/v2/customers",
                                    json={"given_name": "OpenLines", "family_name": "Spike",
                                          "phone_number": phone})["customer"]["id"]
                print(f"  created customer {customer_id}")

            bbody = {
                "idempotency_key": str(uuid.uuid4()),
                "booking": {
                    "location_id": location_id,
                    "start_at": slot["start_at"],
                    "customer_id": customer_id,
                    "customer_note": "OpenLines P0 spike — safe to delete",
                    "appointment_segments": [{
                        "team_member_id": seg.get("team_member_id") or team_ids[0],
                        "service_variation_id": var_id,
                        "service_variation_version": seg.get("service_variation_version") or var_version,
                        "duration_minutes": seg.get("duration_minutes") or dur_min,
                    }],
                },
            }
            booking = _call(c, "POST", "/v2/bookings", json=bbody).get("booking", {})
            booking_id = booking.get("id")
            print(f"  CREATED booking {booking_id}  status={booking.get('status')}  start={booking.get('start_at')}")
            findings.append(f"CreateBooking OK -> {booking_id} (status {booking.get('status')})")

        # 7. CANCEL -------------------------------------------------------
        if args.cancel and booking_id:
            hr("7. CancelBooking")
            got = _call(c, "GET", f"/v2/bookings/{booking_id}").get("booking", {})
            cbody = {"idempotency_key": str(uuid.uuid4()), "booking_version": got.get("version")}
            res = _call(c, "POST", f"/v2/bookings/{booking_id}/cancel", json=cbody).get("booking", {})
            print(f"  cancelled -> status={res.get('status')}")
            findings.append(f"CancelBooking OK ({res.get('status')})")
        elif booking_id:
            print(f"\n  NOTE: left test booking {booking_id} in place. Re-run with --book --cancel to clean up.")

    _summary(findings)


def _summary(findings: list[str]) -> None:
    hr("P0 FINDINGS")
    for f in findings:
        print(f"  • {f}")
    print("\n  Open questions this spike informs:")
    print("    - Square computes availability (we pass-through, not calculate) ........ see #5")
    print("    - service_variation `version` is required by CreateBooking ............ see #3/#6")
    print("    - availability window cap (~32 days) -> chunk long ranges ............. see #5")
    print("    - APPOINTMENTS_ALL_WRITE (other staff's calendars) -> validate via OAuth in P1")


if __name__ == "__main__":
    main()
