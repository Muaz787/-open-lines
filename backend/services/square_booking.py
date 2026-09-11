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
import sys
from datetime import datetime, timedelta, date as date_type, timezone as dt_timezone
from zoneinfo import ZoneInfo

import httpx

from services import square_service as sq_svc
from services import caller_identity
from services import location_scope
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
                    # W3: where this variation may actually be booked. Presence lives
                    # on BOTH the item and the variation in Square, so the effective
                    # scope is their intersection — resolved once here rather than by
                    # every future consumer. Dark: nothing filters on it yet.
                    **location_scope.resolve_service_scope(o, v),
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
            members.append({
                "square_team_member_id": m["id"],
                "display_name": name or "Team member",
                # W3: where this member may be booked. ALL_CURRENT_AND_FUTURE stays a
                # flag rather than today's id list, so a location opened later is
                # still covered. Dark: no roster filters on it yet.
                **location_scope.resolve_staff_scope(m),
            })
        return members


async def search_customers_by_phone(token: str, phone: str) -> list[dict]:
    """Every Square customer with this exact phone. Raises on transport failure.

    W6B needs the FULL list, not the first hit. Several customers sharing a phone
    is an ambiguity to refuse, and the old code could not tell that apart from a
    clean single match because it returned found[0] either way.

    The exception is deliberate: a search that failed is not the same as a search
    that found nothing, and collapsing them is how uncertainty becomes a duplicate.
    """
    if not phone:
        return []
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/customers/search",
            json={"query": {"filter": {"phone_number": {"exact": phone}}}},
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        res.raise_for_status()
        return res.json().get("customers") or []


async def create_customer(
    token: str, *, phone: str, given_name: str = "", idempotency_key: str = "",
) -> str | None:
    """CreateCustomer. Returns the id, or None on a DEFINITIVE provider rejection.

    Raises on an ambiguous outcome (timeout, dropped connection, 5xx) so the caller
    can tell "Square said no" from "we don't know" — the second must never be
    retried under a fresh identity.

    idempotency_key is supplied by the caller, never invented here: W6B derives it
    from the durable provider_customers row id, which survives takeover and crash.
    Square honours it, so replaying a request that may already have been committed
    converges on the original customer instead of making a second one.
    """
    payload: dict = {}
    # W5.2: no invented name. Square accepts a customer identified by phone alone
    # (verified against the live API), and an absent name is honest where "Caller"
    # is an echo of our own prompt masquerading as identity. Re-checked here rather
    # than left to the caller: this is the last point before the value becomes a
    # permanent customer record.
    if given_name and not caller_identity.is_placeholder_name(given_name):
        payload["given_name"] = given_name.strip()
    if phone:
        payload["phone_number"] = phone
    if not payload:
        logger.warning("Square create customer: no name and no phone — refusing")
        return None
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{sq_svc._api_base()}/v2/customers",
            json=payload, headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if res.status_code >= 500:
            res.raise_for_status()          # unknown: may or may not have committed
        if not res.is_success:
            logger.warning("Square create customer %s: %s", res.status_code, res.text[:300])
            return None
        return (res.json().get("customer") or {}).get("id")


async def resolve_customer(
    *, tenant_id: str, token: str, phone: str,
) -> tuple[str, str | None]:
    """W6B entry point: (status, customer_id) via the durable local mapping.

    Takes no name on purpose. Identity here is the phone number; a name would make
    the idempotent creation payload vary between attempts, which is the one thing
    a stable idempotency key cannot survive.
    """
    from services import customer_identity
    return await customer_identity.resolve_customer_id(
        tenant_id=tenant_id, token=token, phone=phone, square=sys.modules[__name__])


async def find_or_create_customer(token: str, *, given_name: str, phone: str) -> str | None:
    """LEGACY shim — search-then-create, with W6B's race still present.

    Kept only for paths that have no tenant context. Anything with a tenant_id
    must use resolve_customer(); this function cannot own an identity because it
    has nowhere to write one down.
    """
    try:
        found = await search_customers_by_phone(token, phone)
    except Exception as e:
        # Fail closed. A search that errored is not a search that found nothing,
        # and creating on that uncertainty is how duplicates are born.
        logger.warning("Square customer search failed: %s", e)
        return None
    if found:
        return found[0]["id"]
    try:
        return await create_customer(token, phone=phone, given_name=given_name)
    except Exception as e:
        logger.warning("Square create customer failed: %s", e)
        return None


async def get_customer(token: str, customer_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{sq_svc._api_base()}/v2/customers/{customer_id}",
            headers=sq_svc._sq_headers(token), timeout=15.0,
        )
        if not res.is_success:
            return {}
        return res.json().get("customer", {})


class BookingOutcomeUnknown(Exception):
    """CreateBooking may or may not have been committed.

    Raised for a transport failure or a 5xx — the cases where Square never told us
    what happened. A definitive 4xx raises the ordinary httpx error instead. The
    distinction matters because the two demand opposite recoveries: a rejection can
    be retried, an unknown outcome must not be, since the current booking body is
    rebuilt from a live resolve_slot and carries a fresh idempotency key, so a
    "retry" would be a second, different request.
    """


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
        try:
            res = await client.post(
                f"{sq_svc._api_base()}/v2/bookings",
                json=body, headers=sq_svc._sq_headers(token), timeout=20.0,
            )
        except Exception as e:
            # Timeout or dropped connection: the request may already be committed.
            raise BookingOutcomeUnknown(str(e)) from e
        if res.status_code >= 500:
            logger.error("Square create_booking %s (unknown outcome): %s",
                         res.status_code, res.text[:400])
            raise BookingOutcomeUnknown(f"HTTP {res.status_code}")
        if not res.is_success:
            logger.warning("Square create_booking %s: %s", res.status_code, res.text[:400])
            res.raise_for_status()          # definitive rejection
        return res.json().get("booking", {})


# Provider READ outcomes. "Square says this booking is gone" and "we could not
# reach Square" are different facts, and a caller that has to infer them from an
# empty dict cannot tell them apart. Under global mutation ownership the two
# demand opposite actions — release the claim, or hold it and reconcile — so the
# distinction has to survive the call, not be reconstructed from `{}`.
FETCH_FOUND = "found"
FETCH_NOT_FOUND = "not_found"
FETCH_UNKNOWN = "unknown"

# Square's error code for a stale booking_version, measured against the live API:
#   HTTP 400 {"errors":[{"category":"INVALID_REQUEST_ERROR",
#                        "code":"VERSION_MISMATCH","detail":"Stale version"}]}
# W6A2 needs to recognise this without parsing exception strings, because after a
# frozen source fingerprint a version mismatch means the MERCHANT changed the
# booking — which must never be resolved by re-fetching and cancelling anyway.
ERR_VERSION_MISMATCH = "VERSION_MISMATCH"


def _first_error_code(res) -> str:
    """Square's first error code, or '' if the body isn't the shape we expect."""
    try:
        return ((res.json().get("errors") or [{}])[0].get("code") or "")
    except Exception:
        return ""


async def get_booking_detailed(token: str, booking_id: str) -> tuple[str, dict]:
    """Read a booking and say how confident we are. Returns (status, booking).

    404 is a definitive answer; 5xx, 429, a timeout or a dropped connection are
    not answers at all. Collapsing the second group into the first is what would
    let a cancellation release its ownership claim on the strength of a provider
    outage.
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{sq_svc._api_base()}/v2/bookings/{booking_id}",
                headers=sq_svc._sq_headers(token), timeout=15.0,
            )
    except Exception as e:
        logger.warning("Square get_booking transport failure for %s: %s", booking_id, e)
        return FETCH_UNKNOWN, {}

    if res.status_code == 404:
        return FETCH_NOT_FOUND, {}
    if res.status_code == 429 or res.status_code >= 500:
        logger.warning("Square get_booking %s (unknown) for %s", res.status_code, booking_id)
        return FETCH_UNKNOWN, {}
    if not res.is_success:
        # Any other 4xx is a definitive refusal to answer about this booking —
        # auth, malformed id. We cannot claim it is absent, so it stays unknown.
        logger.warning("Square get_booking %s: %s", res.status_code, res.text[:200])
        return FETCH_UNKNOWN, {}

    try:
        booking = res.json().get("booking") or {}
    except Exception:
        logger.warning("Square get_booking returned an unparseable body for %s", booking_id)
        return FETCH_UNKNOWN, {}
    if not booking:
        return FETCH_UNKNOWN, {}
    return FETCH_FOUND, booking


async def get_booking(token: str, booking_id: str) -> dict:
    """Compatibility shim: the booking, or {} for anything else.

    Callers that must distinguish "gone" from "we don't know" should use
    get_booking_detailed(); this collapses both to {}.
    """
    status, booking = await get_booking_detailed(token, booking_id)
    return booking if status == FETCH_FOUND else {}


# Cancellation outcomes. A bool cannot carry the difference between "we cancelled
# it", "it was already cancelled" and "we do not know" — and the third of those
# must never be written down as the first.
CANCEL_OK = "cancelled"
CANCEL_ALREADY = "already_cancelled"
CANCEL_NOT_FOUND = "not_found"
CANCEL_FAILED = "failed"
CANCEL_UNKNOWN = "unknown"


async def cancel_booking_detailed(
    token: str, booking_id: str,
) -> tuple[str, dict, str]:
    """Cancel, and say precisely what happened. Returns (status, booking, error_code).

    Square's CancelBooking is naturally idempotent PROVIDED the current version is
    re-fetched first — measured, not assumed: cancelling an already-cancelled
    booking with its current version returns 200 and leaves the version untouched,
    while the same call with a stale version is rejected as VERSION_MISMATCH.

    error_code carries Square's own code for a definitive rejection (notably
    ERR_VERSION_MISMATCH) so a later caller can recognise it structurally rather
    than by matching on exception text.

    The rule that governs every branch: UNKNOWN is never collapsed into FAILED.
    FAILED asserts the booking was NOT cancelled by this request; UNKNOWN asserts
    nothing, and under global ownership that difference decides whether a claim is
    released or held for reconciliation.
    """
    fetch_status, booking = await get_booking_detailed(token, booking_id)
    if fetch_status == FETCH_NOT_FOUND:
        return CANCEL_NOT_FOUND, {}, ""
    if fetch_status == FETCH_UNKNOWN:
        # We could not read the booking, so we cannot say whether it is
        # cancellable, cancelled, or gone. Previously this returned NOT_FOUND,
        # which reads as definitive.
        return CANCEL_UNKNOWN, {}, ""

    status = (booking.get("status") or "").upper()
    if "CANCELLED" in status or status == "DECLINED":
        return CANCEL_ALREADY, booking, ""

    import uuid
    body: dict = {"idempotency_key": str(uuid.uuid4())}
    if booking.get("version") is not None:
        body["booking_version"] = booking["version"]

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                f"{sq_svc._api_base()}/v2/bookings/{booking_id}/cancel",
                json=body, headers=sq_svc._sq_headers(token), timeout=15.0,
            )
        except Exception as e:
            logger.error("Square cancel_booking transport failure for %s: %s", booking_id, e)
            return CANCEL_UNKNOWN, booking, ""

        if res.is_success:
            try:
                cancelled = res.json().get("booking") or {}
            except Exception:
                cancelled = {}
            if not cancelled:
                # 2xx, but nothing we can read back. Success is probable and
                # unproven, and unproven is exactly what UNKNOWN is for.
                logger.warning("Square cancel_booking returned an unreadable body for %s", booking_id)
                return CANCEL_UNKNOWN, booking, ""
            return CANCEL_OK, cancelled, ""

        if res.status_code == 429 or res.status_code >= 500:
            # 429 used to fall through to FAILED because the test was >= 500. A
            # rate-limited request may still have been processed.
            logger.error("Square cancel_booking %s (unknown outcome): %s",
                         res.status_code, res.text[:300])
            return CANCEL_UNKNOWN, booking, ""

        code = _first_error_code(res)
        logger.warning("Square cancel_booking %s (%s): %s",
                       res.status_code, code or "no code", res.text[:300])
        return CANCEL_FAILED, booking, code


async def cancel_booking(token: str, booking_id: str) -> bool:
    """LEGACY bool shim. Prefer cancel_booking_detailed(), which distinguishes
    'already cancelled' and 'unknown' from success — a difference a bool destroys."""
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


# Square rejects a narrower SearchAvailability range outright:
#   400 INVALID_REQUEST_ERROR / INVALID_TIME_RANGE "Min query range is 1 hour."
# The original 2-minute window meant resolve_slot() raised on every real call and
# every booking was refused as "just taken". The window is a Square API floor, NOT
# a widening of what we will book: the match below still accepts only the exact
# requested start, so the extra slots this returns are read and discarded.
RESOLVE_QUERY_WINDOW_MINUTES = 60


async def resolve_slot(
    token: str, location_id: str, service_variation_id: str,
    team_member_ids: list[str], start_dt: datetime,
) -> dict | None:
    """Confirm the exact requested time is bookable and return the segment to book
    {team_member_id, service_variation_version, duration_minutes, start_at}. Square is
    the source of truth — this also picks a free team member when several are eligible.

    Square's minimum query range is an hour, so the request necessarily covers times
    we were not asked about. Everything after the query is a filter, never a choice:
    a caller asking for 13:15 when Square offers 13:00 and 13:30 gets None, not the
    nearest one. Location, variation and team member are re-checked on the returned
    segment rather than trusted to the query filter, so a widened window cannot turn
    into a substitution.
    """
    start_utc = start_dt.astimezone(dt_timezone.utc)
    end_utc = start_utc + timedelta(minutes=RESOLVE_QUERY_WINDOW_MINUTES)

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
        if abs((sdt - start_utc).total_seconds()) >= 60:
            continue                                   # not the time we asked for
        # Square filtered on these already; re-checking them here is what keeps the
        # wider window from becoming a different location, service or person.
        if a.get("location_id") and a["location_id"] != location_id:
            continue
        seg = (a.get("appointment_segments") or [{}])[0]
        if seg.get("service_variation_id") and seg["service_variation_id"] != service_variation_id:
            continue
        if team_member_ids and seg.get("team_member_id") not in team_member_ids:
            continue                                   # exact member required
        if not seg.get("team_member_id"):
            continue                                   # nothing to book against
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
    locations: list[dict] = []
    try:
        locations = await sq_svc.list_locations(token)
        if locations:
            # LEGACY COMPATIBILITY PATH (unchanged, deliberately). Runtime still
            # reads a single tenants.square_location_id, so a first connect still
            # settles on locations[0] exactly as it always has. W2 does not rely on
            # this choice — services/location_sync keys off the stored pointer, never
            # off list order — and W4 is where the single pointer stops being the
            # authority. Do not build anything new on this line.
            location_id = location_id or locations[0].get("id", "")
            location_tz = next((l.get("timezone") for l in locations if l.get("id") == location_id), None) \
                or locations[0].get("timezone") or location_tz
    except Exception as e:
        logger.warning("Square sync: locations failed for %s: %s", tenant_id, e)

    # W2: persist EVERY location, not just the one runtime uses. Dark — nothing
    # reads these rows yet. Best-effort: a failure here must never break the
    # catalog/team sync or the OAuth callback that fires it.
    if locations:
        try:
            from services import location_sync
            await location_sync.sync_square_locations(tenant, locations)
        except Exception as e:
            logger.warning("Square sync: location persistence failed for %s: %s", tenant_id, e)

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


async def available_slots(
    tenant: dict, *, date_str: str, timezone: str,
    service_variation_id: str, team_member_ids: list[str],
    provider_location_id: str,
) -> list[dict]:
    """Square's open slots for one day, with the identifiers a booking needs.

    available_slot_strings() returns display strings and throws the rest away —
    fine when booking re-derived everything, useless once booking must use exactly
    what was offered. Each entry here carries the team member and variation version
    Square itself chose for that slot, so CreateBooking can replay it verbatim.
    """
    token = await get_access_token(tenant)
    location_id = (provider_location_id or "").strip()
    if not token or not location_id:
        return []
    tz = ZoneInfo(timezone)
    day = date_type.fromisoformat(date_str)
    day_start = datetime(day.year, day.month, day.day, tzinfo=tz)
    now = datetime.now(dt_timezone.utc)
    start = max(day_start.astimezone(dt_timezone.utc), now + timedelta(minutes=1))
    end = (day_start + timedelta(days=1)).astimezone(dt_timezone.utc)
    if start >= end:
        return []

    def _z(dt: datetime) -> str:
        return dt.astimezone(dt_timezone.utc).isoformat().replace("+00:00", "Z")

    avails = await search_availability(
        token, location_id, service_variation_id, team_member_ids, _z(start), _z(end))

    out: list[dict] = []
    seen: set[str] = set()
    for a in avails:
        raw = a.get("start_at")
        if not raw or raw in seen:
            continue          # several staff can yield the same time; offer it once
        seen.add(raw)
        try:
            sdt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            continue
        seg = (a.get("appointment_segments") or [{}])[0]
        out.append({
            "start_at_utc": raw,
            "display": _fmt_slot(sdt.astimezone(tz)),
            "team_member_id": seg.get("team_member_id"),
            "service_variation_version": seg.get("service_variation_version"),
            "duration_minutes": seg.get("duration_minutes"),
        })
    return out


async def available_slot_strings(
    tenant: dict, *, date_str: str, timezone: str,
    service_variation_id: str, team_member_ids: list[str],
    provider_location_id: str | None = None,
) -> list[str]:
    """Return Square-computed open slots for a single day as ['2:00 PM', ...].

    provider_location_id is the W4 multi-location path: the caller has named a
    location, the backend resolved it to an immutable Square id, and THAT is what
    Square is asked about. When it is None we are on the legacy single-location
    path and fall back to the tenant pointer, byte-identical to before.
    """
    token = await get_access_token(tenant)
    location_id = (provider_location_id or "").strip() or (tenant.get("square_location_id") or "")
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
    """A service was added/edited/removed in Square → refresh our cached menu.

    Gated on square_appointments_enabled, matching handle_booking_event below.
    Without that gate ANY catalog edit on a merchant rewrites the service and team
    caches of EVERY tenant connected to it, whether or not that tenant books through
    Square. That is not hypothetical: it fired during W3 fixture work and wrote an
    unrelated merchant's services into a live tenant that has Square booking
    switched off.

    Deliberately narrower than the explicit paths. The manual sync endpoint and the
    OAuth callback still sync an unenabled tenant, because a merchant must be able
    to connect and preview its catalog before turning booking on. What changes is
    that an *unsolicited* provider event can no longer do it.
    """
    tenant = await db.get_tenant_by_square_merchant_id(event.get("merchant_id", ""))
    if not tenant or not tenant.get("square_access_token"):
        return
    if not tenant.get("square_appointments_enabled"):
        logger.info(
            "Square sync: catalog event for tenant %s ignored — appointments not "
            "enabled for this tenant", tenant["id"])
        return
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


# ---------------------------------------------------------------------------
# W4.1 — the bookable service menu, as the assistant should see it
# ---------------------------------------------------------------------------

def _display_service_name(cached_name: str) -> str:
    """'Dress Fitting — Regular' -> 'Dress Fitting'.

    Square names a bookable thing as item + variation. A caller says the item
    ("a dress fitting"), never the variation, so the variation suffix is noise in
    a spoken menu. Matching is unaffected: _match_square_service does containment,
    and 'dress fitting' is contained in 'dress fitting — regular'.
    """
    return (cached_name or "").split(" — ")[0].strip() or (cached_name or "").strip()


async def service_menu_block(tenant: dict) -> str:
    """Human-readable bookable services for a Square Appointments tenant.

    Exists because the menu built in provisioning.rebuild_and_push_system_prompt is
    appended to the pushed config but NOT to last_system_prompt, and the per-call
    assistant-request override rebuilds from last_system_prompt — so the menu never
    reached a live call. The location block has the same shape for the same reason.

    Multi-location tenants get the menu grouped BY LOCATION, so the model can tell
    a caller what is bookable where without a tool round-trip.

    Names only. Never a variation id, catalog id or provider location id.
    """
    tenant_id = str(tenant.get("id") or "")
    if not tenant_id or not tenant.get("square_appointments_enabled"):
        return ""
    try:
        services = await db.get_square_services(tenant_id, bookable_only=True)
        if not services:
            return ""

        from services import call_location, location_scope
        multi, adopted = await call_location.is_multi_location(tenant_id)
        eligible = call_location.eligible_for_availability(adopted) if multi else []

        if multi and eligible:
            lines = []
            for loc in eligible:
                pid = (loc.get("_binding") or {}).get("provider_location_id") or ""
                here = location_scope.services_at_location(services, pid)
                names = sorted({_display_service_name(s.get("name")) for s in here if s.get("name")})
                if names:
                    lines.append(f"- {loc.get('name')}: {', '.join(names)}")
            if not lines:
                return ""
            return (
                "\n\nSERVICES (Square Appointments)\n"
                "These are the only bookable services, and they differ by location:\n"
                + "\n".join(lines) +
                "\n- Pass what the caller asked for in the `service` argument of "
                "check_availability, in their own words.\n"
                "- If a caller asks for something not offered at their chosen location, say so "
                "and offer what IS available there, or offer another location. Never quietly "
                "substitute a different service.\n"
                "- Availability is read live from the business's own calendar."
            )

        names = sorted({_display_service_name(s.get("name")) for s in services if s.get("name")})
        return (
            "\n\nSERVICES (Square Appointments)\n"
            f"Offer only these bookable services: {', '.join(names)}.\n"
            "- Pass the caller's chosen service in the `service` argument of check_availability.\n"
            "- Availability is read live from the business's own calendar."
        )
    except Exception as e:
        logger.warning("service_menu_block failed for %s: %s", tenant_id, e)
        return ""
