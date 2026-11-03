"""
Real Square API test for issue #179, against a SANDBOX seller only.

Skipped unless these are set in the environment (never in the repo):
  SQUARE_SANDBOX_TOKEN                 sandbox access token (starts EAAA...)
  SQUARE_SANDBOX_LOCATION_ID
  SQUARE_SANDBOX_SERVICE_VARIATION_ID  a bookable service variation
  SQUARE_SANDBOX_TEAM_MEMBER_ID        a team member who can perform it

It refuses to run against production: every request goes to
connect.squareupsandbox.com, and the token is checked there first.

What it proves about the real API, through our own update_booking_start:
  1. UpdateBooking moves a booking and keeps its id;
  2. the version goes up by one and the segments (team member, service,
     duration) and location are unchanged;
  3. replaying the same idempotency key doesn't move it again;
  4. a stale version is refused (and records Square's error code);
then it cancels the booking it created.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from services import square_booking as sb, square_service as sq_svc

SANDBOX = "https://connect.squareupsandbox.com"
NEEDED = ("SQUARE_SANDBOX_TOKEN", "SQUARE_SANDBOX_LOCATION_ID",
          "SQUARE_SANDBOX_SERVICE_VARIATION_ID", "SQUARE_SANDBOX_TEAM_MEMBER_ID")

pytestmark = pytest.mark.skipif(not all(os.getenv(k) for k in NEEDED),
                                reason="Square sandbox credentials not set")


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _sq(method, path, token, body=None):
    async with httpx.AsyncClient() as c:
        r = await c.request(method, SANDBOX + path, json=body, timeout=20.0,
                            headers={"Authorization": f"Bearer {token}", "Square-Version": "2024-11-20",
                                     "Content-Type": "application/json"})
    return r.status_code, (r.json() if r.content else {})


async def test_update_booking_moves_in_place_on_the_real_sandbox_api(monkeypatch):
    token = os.environ["SQUARE_SANDBOX_TOKEN"]
    loc = os.environ["SQUARE_SANDBOX_LOCATION_ID"]
    var = os.environ["SQUARE_SANDBOX_SERVICE_VARIATION_ID"]
    tm = os.environ["SQUARE_SANDBOX_TEAM_MEMBER_ID"]
    monkeypatch.setattr(sq_svc, "_api_base", lambda: SANDBOX)

    code, _ = await _sq("GET", "/v2/locations", token)
    assert code == 200, "the token must be a sandbox token"

    # two free slots for this team member, a day or more ahead
    start = datetime.now(timezone.utc) + timedelta(days=2)
    code, avail = await _sq("POST", "/v2/bookings/availability/search", token, {"query": {"filter": {
        "start_at_range": {"start_at": _z(start), "end_at": _z(start + timedelta(days=7))},
        "location_id": loc,
        "segment_filters": [{"service_variation_id": var, "team_member_id_filter": {"any": [tm]}}]}}})
    assert code == 200, avail
    slots = [a for a in avail.get("availabilities", [])]
    assert len(slots) >= 2, "the sandbox seller needs open availability for this team member"
    first, second = slots[0], slots[-1]
    seg = first["appointment_segments"][0]

    code, cust = await _sq("POST", "/v2/customers", token, {
        "idempotency_key": str(uuid.uuid4()), "given_name": "Open Lines", "family_name": "Sandbox test"})
    assert code == 200, cust
    code, created = await _sq("POST", "/v2/bookings", token, {"idempotency_key": str(uuid.uuid4()), "booking": {
        "start_at": first["start_at"], "location_id": loc, "customer_id": cust["customer"]["id"],
        "appointment_segments": [{"duration_minutes": seg["duration_minutes"], "team_member_id": tm,
                                  "service_variation_id": var,
                                  "service_variation_version": seg["service_variation_version"]}]}})
    assert code == 200, created
    booking = created["booking"]
    try:
        before = sb.booking_shape(booking)
        key = str(uuid.uuid4())

        status, moved, err = await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=second["start_at"],
            idempotency_key=key)
        assert status == sb.UPDATE_OK, err
        after = sb.booking_shape(moved)
        assert moved["id"] == booking["id"], "1. same booking id"
        assert after["version"] == before["version"] + 1, "2. version up by one"
        for part in ("team_member_id", "service_variation_id", "minutes", "location_id", "customer_id"):
            assert after[part] == before[part], f"2. {part} unchanged"
        assert after["start"] == datetime.fromisoformat(second["start_at"].replace("Z", "+00:00"))

        status, again, _ = await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=second["start_at"],
            idempotency_key=key)
        fetched = sb.booking_shape((await sb.get_booking_detailed(token, booking["id"]))[1])
        assert fetched["version"] == after["version"], "3. a replay doesn't move it again"

        status, _, code = await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=first["start_at"],
            idempotency_key=str(uuid.uuid4()))
        assert status == sb.UPDATE_FAILED, "4. a stale version is refused"
        print(f"stale-version error code from Square: {code!r}")
    finally:
        latest = (await sb.get_booking_detailed(token, booking["id"]))[1]
        await _sq("POST", f"/v2/bookings/{booking['id']}/cancel", token,
                  {"idempotency_key": str(uuid.uuid4()), "booking_version": latest.get("version")})
