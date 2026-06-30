"""
Square Appointments (Bookings API) — P1: read availability from a merchant's
own Square calendar, plus sync their service catalog + team roster.

This is a third booking provider alongside Google (`services/calendar.py`) and
Microsoft (`services/ms_calendar.py`). Unlike those, **Square computes
availability itself** — we pass through `SearchAvailability`, we do not calculate
slots. See docs/square-appointments-p0-findings.md.

P1 is read-only. CreateBooking/Cancel land in P2. The live dispatch switch
(`tenants.square_appointments_enabled`) stays OFF until P2 wires booking.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date as date_type, timezone as dt_timezone
from zoneinfo import ZoneInfo

import httpx

from services import square_service as sq_svc
from services.security import decrypt
from db import supabase as db

logger = logging.getLogger(__name__)

# Square caps the availability query window at 32 days (confirmed in P0).
MAX_WINDOW_DAYS = 32


# ---------------------------------------------------------------------------
# Access token (decrypt + refresh-if-near-expiry)
# ---------------------------------------------------------------------------

async def get_access_token(tenant: dict) -> str | None:
    """Return a usable Square access token for the tenant, refreshing it if it is
    within ~3 days of expiry. Returns None if the tenant has no Square connection."""
    enc = tenant.get("square_access_token")
    if not enc:
        return None
    token = decrypt(enc)

    expires_at = tenant.get("square_token_expires_at")
    refresh_enc = tenant.get("square_refresh_token")
    if expires_at and refresh_enc:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt_timezone.utc)
            if exp - datetime.now(dt_timezone.utc) < timedelta(days=3):
                data = await sq_svc.refresh_access_token(decrypt(refresh_enc))
                new_token = data.get("access_token")
                if new_token:
                    from services.security import encrypt
                    await db.update_tenant(tenant["id"], {
                        "square_access_token": encrypt(new_token),
                        "square_token_expires_at": data.get("expires_at") or None,
                    })
                    logger.info("Square token refreshed for tenant %s", tenant.get("id"))
                    return new_token
        except Exception as e:  # refresh is best-effort; fall back to the stored token
            logger.warning("Square token refresh failed for tenant %s: %s", tenant.get("id"), e)
    return token


# ---------------------------------------------------------------------------
# Raw Bookings API calls
# ---------------------------------------------------------------------------

async def retrieve_booking_profile(token: str) -> dict:
    """RetrieveBusinessBookingProfile. `booking_enabled` is authoritative for WRITES
    (reads work without it) and `booking_policy` decides instant-confirm vs PENDING."""
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{sq_svc._api_base()}/v2/bookings/business-booking-profile",
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            logger.warning("Square booking profile %s: %s", res.status_code, res.text[:300])
            return {}
        return res.json().get("business_booking_profile", {})


async def list_services(token: str) -> list[dict]:
    """Return bookable APPOINTMENTS_SERVICE variations as flat dicts."""
    out: list[dict] = []
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/catalog/search",
            json={"object_types": ["ITEM"]},
            headers=sq_svc._sq_headers(token), timeout=20.0,
        )
        res.raise_for_status()
        for o in res.json().get("objects", []):
            item = o.get("item_data", {})
            if item.get("product_type") != "APPOINTMENTS_SERVICE":
                continue
            for v in item.get("variations", []):
                vd = v.get("item_variation_data", {})
                dur_ms = vd.get("service_duration") or 0
                price = vd.get("price_money") or {}
                out.append({
                    "square_variation_id": v["id"],
                    "square_item_id": o.get("id"),
                    "name": f"{item.get('name', '')} — {vd.get('name', '')}".strip(" —"),
                    "duration_minutes": int(dur_ms) // 60000 if dur_ms else None,
                    "price_cents": price.get("amount"),
                    "currency": price.get("currency"),
                    "variation_version": v.get("version"),
                    "team_member_ids": vd.get("team_member_ids") or [],
                    "available_for_booking": bool(vd.get("available_for_booking", True)),
                })
    return out


async def list_team_members(token: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/team-members/search",
            json={"query": {"filter": {"status": "ACTIVE"}}},
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        res.raise_for_status()
        members = []
        for m in res.json().get("team_members", []):
            name = f"{m.get('given_name', '')} {m.get('family_name', '')}".strip()
            members.append({"square_team_member_id": m["id"], "display_name": name or "Team member"})
        return members


async def find_or_create_customer(token: str, *, given_name: str, phone: str) -> str | None:
    """Return a Square customer id for the caller, searching by phone first."""
    async with httpx.AsyncClient() as client:
        if phone:
            res = await client.post(
                f"{sq_svc._api_base()}/v2/customers/search",
                json={"query": {"filter": {"phone_number": {"exact": phone}}}},
                headers=sq_svc._sq_headers(token), timeout=15.0,
            )
            if res.is_success:
                found = res.json().get("customers") or []
                if found:
                    return found[0]["id"]
        payload: dict = {"given_name": given_name or "Caller"}
        if phone:
            payload["phone_number"] = phone
        res = await client.post(
            f"{sq_svc._api_base()}/v2/customers",
            json=payload, headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            logger.warning("Square create customer %s: %s", res.status_code, res.text[:300])
            return None
        return (res.json().get("customer") or {}).get("id")


async def get_customer(token: str, customer_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{sq_svc._api_base()}/v2/customers/{customer_id}",
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            return {}
        return res.json().get("customer", {})


async def create_booking(
    token: str, *, location_id: str, start_at_iso: str, customer_id: str,
    team_member_id: str, service_variation_id: str, service_variation_version,
    duration_minutes: int | None, note: str = "",
) -> dict:
    """CreateBooking. Returns the booking object (id, status, ...). Raises on HTTP error."""
    import uuid
    seg: dict = {
        "team_member_id": team_member_id,
        "service_variation_id": service_variation_id,
    }
    if service_variation_version is not None:
        seg["service_variation_version"] = int(service_variation_version)
    if duration_minutes:
        seg["duration_minutes"] = int(duration_minutes)
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "booking": {
            "location_id": location_id,
            "start_at": start_at_iso,
            "customer_id": customer_id,
            "appointment_segments": [seg],
        },
    }
    if note:
        body["booking"]["customer_note"] = note
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/bookings",
            json=body, headers=sq_svc._sq_headers(token), timeout=20.0,
        )
        if not res.is_success:
            logger.warning("Square create_booking %s: %s", res.status_code, res.text[:400])
            res.raise_for_status()
        return res.json().get("booking", {})


async def get_booking(token: str, booking_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{sq_svc._api_base()}/v2/bookings/{booking_id}",
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            return {}
        return res.json().get("booking", {})


async def cancel_booking(token: str, booking_id: str) -> bool:
    """Cancel a Square booking (retrieves current version first). Returns True on success."""
    import uuid
    booking = await get_booking(token, booking_id)
    version = booking.get("version")
    body: dict = {"idempotency_key": str(uuid.uuid4())}
    if version is not None:
        body["booking_version"] = version
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/bookings/{booking_id}/cancel",
            json=body, headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            logger.warning("Square cancel_booking %s: %s", res.status_code, res.text[:300])
        return res.is_success


async def search_availability(
    token: str, location_id: str, service_variation_id: str,
    team_member_ids: list[str], start_at_iso: str, end_at_iso: str,
) -> list[dict]:
    """SearchAvailability — returns Square-computed availability objects."""
    body = {"query": {"filter": {
        "start_at_range": {"start_at": start_at_iso, "end_at": end_at_iso},
        "location_id": location_id,
        "segment_filters": [{
            "service_variation_id": service_variation_id,
            "team_member_id_filter": {"any": team_member_ids},
        }],
    }}}
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/bookings/availability/search",
            json=body, headers=sq_svc._sq_headers(token), timeout=20.0,
        )
        if not res.is_success:
            logger.warning("Square availability %s: %s", res.status_code, res.text[:300])
            res.raise_for_status()
        return res.json().get("availabilities", [])


# ---------------------------------------------------------------------------
# High-level: sync + availability-as-slot-strings
# ---------------------------------------------------------------------------

def _fmt_slot(dt: datetime) -> str:
    """Match the Google/MS provider format: '2:00 PM'."""
    h = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h}:{dt.minute:02d} {ampm}"


async def resolve_slot(
    token: str, location_id: str, service_variation_id: str,
    team_member_ids: list[str], start_dt: datetime,
) -> dict | None:
    """Confirm the exact requested time is bookable and return the segment to book
    {team_member_id, service_variation_version, duration_minutes, start_at}. Square is
    the source of truth — this also picks a free team member when several are eligible."""
    start_utc = start_dt.astimezone(dt_timezone.utc)
    end_utc = start_utc + timedelta(minutes=2)

    def _z(dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    try:
        avails = await search_availability(
            token, location_id, service_variation_id, team_member_ids, _z(start_utc), _z(end_utc))
    except Exception as e:
        logger.warning("resolve_slot: availability search failed: %s", e)
        return None
    for a in avails:
        try:
            sdt = datetime.fromisoformat(a["start_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if abs((sdt - start_utc).total_seconds()) < 60:
            seg = (a.get("appointment_segments") or [{}])[0]
            return {
                "team_member_id": seg.get("team_member_id"),
                "service_variation_version": seg.get("service_variation_version"),
                "duration_minutes": seg.get("duration_minutes"),
                "start_at": a["start_at"],
            }
    return None


async def sync(tenant_id: str) -> dict:
    """Pull the merchant's location tz, booking profile, services, and team into
    our cache. Returns a summary for the API/frontend. Best-effort per call."""
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant:
        return {"ok": False, "error": "tenant_not_found"}
    token = await get_access_token(tenant)
    if not token:
        return {"ok": False, "error": "not_connected"}

    location_id = tenant.get("square_location_id") or ""
    location_tz = tenant.get("square_location_timezone")
    try:
        locations = await sq_svc.list_locations(token)
        if locations:
            location_id = location_id or locations[0].get("id", "")
            location_tz = next((l.get("timezone") for l in locations if l.get("id") == location_id), None) \
                or locations[0].get("timezone") or location_tz
    except Exception as e:
        logger.warning("Square sync: locations failed for %s: %s", tenant_id, e)

    profile = await retrieve_booking_profile(token)
    bookable = bool(profile.get("booking_enabled"))

    services = await list_services(token)
    staff = await list_team_members(token)

    await db.replace_square_services(tenant_id, services)
    await db.replace_square_staff(tenant_id, staff)
    await db.update_tenant(tenant_id, {
        "square_location_id": location_id or None,
        "square_location_timezone": location_tz or None,
        "square_appointments_bookable": bookable,
        "square_booking_synced_at": datetime.now(dt_timezone.utc).isoformat(),
    })
    logger.info("Square Appointments sync for %s: %d services, %d staff, bookable=%s",
                tenant_id, len(services), len(staff), bookable)
    return {
        "ok": True, "bookable": bookable, "booking_policy": profile.get("booking_policy"),
        "services": services, "staff": staff, "location_timezone": location_tz,
    }


async def available_slot_strings(
    tenant: dict, *, date_str: str, timezone: str,
    service_variation_id: str, team_member_ids: list[str],
) -> list[str]:
    """Return Square-computed open slots for a single day as ['2:00 PM', ...]."""
    token = await get_access_token(tenant)
    location_id = tenant.get("square_location_id") or ""
    if not token or not location_id:
        return []
    tz = ZoneInfo(timezone)
    day = date_type.fromisoformat(date_str)
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    # Square requires the range start to be in the future.
    now = datetime.now(dt_timezone.utc)
    start = max(day_start.astimezone(dt_timezone.utc), now + timedelta(minutes=1))
    end = (day_start + timedelta(days=1)).astimezone(dt_timezone.utc)
    if start >= end:
        return []

    def _z(dt: datetime) -> str:
        return dt.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")

    avails = await search_availability(
        token, location_id, service_variation_id, team_member_ids, _z(start), _z(end))
    times: list[str] = []
    for a in avails:
        try:
            sdt = datetime.fromisoformat(a["start_at"].replace("Z", "+00:00")).astimezone(tz)
            times.append(_fmt_slot(sdt))
        except Exception:
            continue
    # de-dupe (multiple team members can yield the same slot time) while preserving order
    seen: set[str] = set()
    return [t for t in times if not (t in seen or seen.add(t))]


# ---------------------------------------------------------------------------
# P3 — two-way sync from Square webhooks (booking.* / catalog.version.updated)
# ---------------------------------------------------------------------------

async def handle_catalog_update(event: dict) -> None:
    """A service was added/edited/removed in Square → refresh our cached menu."""
    tenant = await db.get_tenant_by_square_merchant_id(event.get("merchant_id", ""))
    if tenant and tenant.get("square_access_token"):
        await sync(tenant["id"])
        logger.info("Square sync: catalog refreshed for tenant %s", tenant["id"])


async def handle_booking_event(event: dict) -> None:
    """Mirror a Square booking into our appointments table so the dashboard reflects
    web/walk-in bookings too. Idempotent; skips the echo of our own phone bookings."""
    tenant = await db.get_tenant_by_square_merchant_id(event.get("merchant_id", ""))
    if not tenant or not tenant.get("square_appointments_enabled"):
        return
    tid = tenant["id"]
    data = event.get("data") or {}
    booking = (data.get("object") or {}).get("booking") or {}
    booking_id = booking.get("id") or data.get("id", "")
    if not booking_id:
        return

    status = (booking.get("status") or "").upper()
    existing = await db.get_appointment_by_event_id(tid, booking_id)

    # Cancellation / decline made in Square → cancel our mirror.
    if "CANCELLED" in status or status == "DECLINED":
        if existing and existing.get("status") != "cancelled":
            await db.update_appointment(existing["id"], {**existing, "status": "cancelled"})
            logger.info("Square sync: cancelled mirror appt %s (booking %s)", existing["id"], booking_id)
        return

    seg = (booking.get("appointment_segments") or [{}])[0]
    start_at = booking.get("start_at", "")

    # Existing mirror (ours or previously synced) → update time on reschedule.
    if existing:
        if start_at and existing.get("appointment_datetime") != start_at:
            await db.update_appointment(existing["id"], {**existing, "appointment_datetime": start_at})
            logger.info("Square sync: rescheduled mirror appt %s (booking %s)", existing["id"], booking_id)
        return

    # Echo of our own just-created phone booking — the tool path owns that row.
    if "Open Lines" in (booking.get("customer_note") or ""):
        return

    # External booking (website / walk-in / Square dashboard) → create a mirror row.
    services = {s["square_variation_id"]: s for s in await db.get_square_services(tid, bookable_only=False)}
    staff = {s["square_team_member_id"]: s.get("display_name") for s in await db.get_square_staff(tid)}
    svc = services.get(seg.get("service_variation_id"), {})

    name, phone = "", ""
    token = await get_access_token(tenant)
    if token and booking.get("customer_id"):
        try:
            c = await get_customer(token, booking["customer_id"])
            name = f"{c.get('given_name', '')} {c.get('family_name', '')}".strip()
            phone = c.get("phone_number", "") or ""
        except Exception as e:
            logger.warning("Square sync: customer fetch failed for %s: %s", booking_id, e)

    appt = {
        "tenant_id": tid, "caller_name": name, "caller_phone": phone,
        "service": svc.get("name") or "Appointment", "appointment_datetime": start_at,
        "duration_minutes": seg.get("duration_minutes") or svc.get("duration_minutes") or 60,
        "status": "confirmed", "google_event_id": booking_id, "source": "square",
    }
    sm = staff.get(seg.get("team_member_id"))
    if sm:
        appt["staff_name"] = sm
    await db.insert_appointment(appt)
    logger.info("Square sync: mirrored external booking %s for tenant %s", booking_id, tid)
