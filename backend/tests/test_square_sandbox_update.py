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
then it cancels the booking and deletes the customer it created.

Every object it creates is tagged with this run's id (reference_id
"openlines-sandbox-test:<run id>") and written, with the outcome of its cleanup,
to a manifest — SQUARE_SANDBOX_MANIFEST_DIR, default the system temp directory —
as soon as it exists, so a run that stops half-way still says exactly what it
left behind. The manifest never contains the token.

This checks Square's booking-update contract only. It creates no deposit and
touches none of our payment records or webhooks: deposit and payment safety are
covered by the mocked tests in tests/test_square_deposit_reschedule.py.
"""
import json
import os
import tempfile
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


class Manifest:
    """What this run created and what became of it, written after every change."""

    def __init__(self):
        self.run_id = uuid.uuid4().hex[:12]
        self.path = os.path.join(os.getenv("SQUARE_SANDBOX_MANIFEST_DIR") or tempfile.gettempdir(),
                                 f"openlines-square-sandbox-{self.run_id}.json")
        self.data = {"run_id": self.run_id, "started_at": _z(datetime.now(timezone.utc)),
                     "host": SANDBOX, "created": [], "steps": []}
        self.save()

    @property
    def reference(self):
        return f"openlines-sandbox-test:{self.run_id}"

    def created(self, kind, object_id):
        self.data["created"].append({"type": kind, "id": object_id, "cleanup": "pending"})
        self.save()

    def cleaned(self, kind, object_id, outcome):
        for row in self.data["created"]:
            if row["type"] == kind and row["id"] == object_id:
                row["cleanup"] = outcome
        self.save()

    def step(self, name, outcome):
        self.data["steps"].append({"step": name, "outcome": outcome})
        self.save()

    def save(self):
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=1)


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

    m = Manifest()
    print(f"sandbox manifest: {m.path}")
    customer_id = booking = None
    try:
        code, cust = await _sq("POST", "/v2/customers", token, {
            "idempotency_key": str(uuid.uuid4()), "given_name": "Open Lines", "family_name": "Sandbox test",
            "reference_id": m.reference, "note": f"Created by tests/test_square_sandbox_update.py run {m.run_id}"})
        assert code == 200, cust
        customer_id = cust["customer"]["id"]
        m.created("customer", customer_id)

        code, created = await _sq("POST", "/v2/bookings", token, {"idempotency_key": str(uuid.uuid4()), "booking": {
            "start_at": first["start_at"], "location_id": loc, "customer_id": customer_id,
            "appointment_segments": [{"duration_minutes": seg["duration_minutes"], "team_member_id": tm,
                                      "service_variation_id": var,
                                      "service_variation_version": seg["service_variation_version"]}]}})
        if code != 200:
            m.step("create_booking", f"HTTP {code}: {(created.get('errors') or [{}])[0].get('code')}")
        assert code == 200, created
        booking = created["booking"]
        m.created("booking", booking["id"])

        before = sb.booking_shape(booking)
        key = str(uuid.uuid4())

        status, moved, err = await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=second["start_at"],
            idempotency_key=key)
        m.step("update_booking", status)
        assert status == sb.UPDATE_OK, err
        after = sb.booking_shape(moved)
        assert moved["id"] == booking["id"], "1. same booking id"
        assert after["version"] == before["version"] + 1, "2. version up by one"
        for part in ("team_member_id", "service_variation_id", "minutes", "location_id", "customer_id"):
            assert after[part] == before[part], f"2. {part} unchanged"
        assert after["start"] == datetime.fromisoformat(second["start_at"].replace("Z", "+00:00"))

        fetched_status, fetched_booking = await sb.get_booking_detailed(token, booking["id"])
        assert fetched_status == sb.FETCH_FOUND
        readback = sb.booking_shape(fetched_booking)
        assert readback["start"] == after["start"] and readback["version"] == after["version"], \
            "provider read-back agrees"

        await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=second["start_at"],
            idempotency_key=key)
        replayed = sb.booking_shape((await sb.get_booking_detailed(token, booking["id"]))[1])
        assert replayed["version"] == after["version"], "3. a replay doesn't move it again"
        m.step("idempotent_replay", "no second move")

        status, _, code = await sb.update_booking_start(
            token, booking["id"], version=booking["version"], start_at_iso=first["start_at"],
            idempotency_key=str(uuid.uuid4()))
        m.step("stale_version", f"{status} ({code})")
        assert status == sb.UPDATE_FAILED, "4. a stale version is refused"
        print(f"stale-version error code from Square: {code!r}")
    finally:
        if booking:
            latest = (await sb.get_booking_detailed(token, booking["id"]))[1]
            c, _ = await _sq("POST", f"/v2/bookings/{booking['id']}/cancel", token,
                             {"idempotency_key": str(uuid.uuid4()), "booking_version": latest.get("version")})
            m.cleaned("booking", booking["id"], "cancelled" if c == 200 else f"cancel HTTP {c}")
        if customer_id:
            c, _ = await _sq("DELETE", f"/v2/customers/{customer_id}", token)
            m.cleaned("customer", customer_id, "deleted" if c == 200 else f"delete HTTP {c}")
        m.data["finished_at"] = _z(datetime.now(timezone.utc))
        m.save()
