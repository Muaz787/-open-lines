"""
W5 — slot binding. What availability offered is what booking creates.

THE PROBLEM THIS SOLVES
Before this, availability and booking were two independent derivations from the
caller's words. Booking re-matched the service by name, re-resolved the staff and
re-read the tenant's location pointer. Nothing connected the times a caller HEARD
to the appointment they GOT. For a single-location tenant that was survivable; for
a multi-location one it means hearing Dublin and being booked in Cork, which the
caller discovers by arriving in the wrong city.

THE SHAPE OF THE FIX
Availability writes down each slot it offered, with the exact Square identifiers
Square itself chose for it. Booking takes a short opaque reference and uses ONLY
what is stored against it. The model never sees or supplies a Square id, so it
cannot ask us to create a booking we never offered — not by hallucinating one, not
by mixing two locations, not by drifting mid-call.

Refs are monotonic across the whole call ('slot_1', 'slot_2', …), never restarted
per location: reusing 'slot_1' for Dublin after Cork already had one is precisely
the confusion this exists to prevent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db import locations as db_loc

logger = logging.getLogger(__name__)

# Long enough for a caller to think, short enough that a slot cannot be booked
# from stale information. Square is re-checked at booking time regardless.
OFFER_TTL_MINUTES = 15

# Enough for a full day of half-hourly slots without writing a row per week.
MAX_OFFERS_PER_QUERY = 20

# Why a booking attempt was refused. Stable strings so tests and the tool layer
# agree, and so a caller-facing message is chosen once rather than per call site.
OK = "ok"
NOT_FOUND = "not_found"
EXPIRED = "expired"
WRONG_LOCATION = "wrong_location"
ALREADY_BOOKED = "already_booked"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_offers(
    *, vapi_call_id: str, tenant_id: str, tenant_location_id: str,
    provider_location_id: str, service_variation_id: str, service_name: str,
    slots: list[dict],
) -> list[dict]:
    """Persist what we are about to offer. Returns the rows, each with its ref.

    Refs continue from whatever this call has already issued, so a caller who
    checks Cork then Dublin gets slot_1..slot_n and slot_n+1..slot_m — no ref ever
    means two different things inside one call.
    """
    if not (vapi_call_id and tenant_id and provider_location_id and slots):
        return []

    try:
        offset = await db_loc.count_slot_offers(vapi_call_id)
    except Exception as e:
        logger.warning("slot_offers: could not count existing offers for %s: %s",
                       vapi_call_id, e)
        offset = 0

    expires = (_now() + timedelta(minutes=OFFER_TTL_MINUTES)).isoformat()
    rows = []
    for i, slot in enumerate(slots[:MAX_OFFERS_PER_QUERY], start=offset + 1):
        rows.append({
            "slot_ref": f"slot_{i}",
            "vapi_call_id": vapi_call_id,
            "tenant_id": tenant_id,
            "tenant_location_id": tenant_location_id or None,
            "provider_location_id": provider_location_id,
            "service_variation_id": service_variation_id,
            "service_variation_version": slot.get("service_variation_version"),
            "service_name": service_name or None,
            "team_member_id": slot.get("team_member_id"),
            "start_at_utc": slot["start_at_utc"],
            "duration_minutes": slot.get("duration_minutes"),
            "expires_at": expires,
        })

    try:
        await db_loc.insert_slot_offers(rows)
    except Exception as e:
        # Availability is still useful without refs — the caller hears real times.
        # Booking will simply ask them to pick again rather than book blind.
        logger.error("slot_offers: persist failed for call %s: %s", vapi_call_id, e)
        return []

    # Pair each stored row with its display string for the spoken response.
    for row, slot in zip(rows, slots[:MAX_OFFERS_PER_QUERY]):
        row["display"] = slot.get("display", "")
    return rows


async def resolve_for_booking(
    *, vapi_call_id: str, slot_ref: str, tenant_id: str, active_location_id: str,
) -> tuple[str, dict | None]:
    """Validate a slot_ref for booking. Returns (status, offer).

    Fails closed on every branch. There is deliberately no path here that
    reconstructs a booking from anything the model said — an invalid ref means the
    caller is asked to choose again, never that we guess.
    """
    if not (vapi_call_id and slot_ref and tenant_id):
        return NOT_FOUND, None

    offer = await db_loc.get_slot_offer(vapi_call_id, slot_ref.strip(), tenant_id)
    if not offer:
        # Covers a hallucinated ref, a ref from another call, and a ref belonging
        # to another tenant — all three are simply "not yours".
        return NOT_FOUND, None

    if offer.get("consumed_at") and offer.get("booking_id"):
        # A retried tool call. Idempotency: hand back what already exists.
        return ALREADY_BOOKED, offer

    try:
        expires = datetime.fromisoformat(str(offer["expires_at"]).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= _now():
            return EXPIRED, offer
    except Exception:
        return EXPIRED, offer

    # THE LOCATION LOCK. An offer made for Cork cannot be booked while the call is
    # on Dublin. This is what makes "checked Cork, booked Dublin" impossible rather
    # than merely unlikely — it holds even if the model asks for it explicitly.
    if active_location_id and str(offer.get("tenant_location_id") or "") != str(active_location_id):
        return WRONG_LOCATION, offer

    return OK, offer


async def mark_consumed(vapi_call_id: str, slot_ref: str, booking_id: str) -> None:
    """Only ever called AFTER Square confirms the booking. A failed CreateBooking
    must leave the offer usable — the caller should be able to try the same time
    again rather than be told it is gone."""
    try:
        await db_loc.consume_slot_offer(vapi_call_id, slot_ref, booking_id)
    except Exception as e:
        logger.error("slot_offers: consume failed for %s/%s: %s", vapi_call_id, slot_ref, e)


async def clear(vapi_call_id: str) -> None:
    try:
        await db_loc.delete_slot_offers(vapi_call_id)
    except Exception as e:
        logger.warning("slot_offers: cleanup failed for %s: %s", vapi_call_id, e)


async def purge_expired() -> int:
    try:
        return await db_loc.purge_expired_slot_offers(_now().isoformat())
    except Exception as e:
        logger.error("slot_offers: TTL purge failed: %s", e)
        return 0


def spoken_offer_list(rows: list[dict], limit: int = 6) -> str:
    """'2:00 PM [slot_1], 2:30 PM [slot_2]' — times for the caller, refs for the model.

    The refs are in the tool RESULT, not in anything the assistant reads aloud; the
    prompt tells it to speak times only and pass the matching ref back.
    """
    parts = [f"{r.get('display')} [{r['slot_ref']}]" for r in rows[:limit] if r.get("display")]
    return ", ".join(parts)
