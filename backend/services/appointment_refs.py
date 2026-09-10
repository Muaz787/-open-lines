"""
W6A1 — the caller says which appointment, and only that one can be cancelled.

THE PROBLEM THIS SOLVES
cancel_appointment took no arguments at all. It read the caller's number, took
the earliest active appointment, and cancelled it. For a single-location tenant
that is usually the right guess. For DANI it means a caller with a Cork
consultation and a Dublin fitting loses whichever is sooner, silently, and finds
out by turning up.

THE SHAPE OF THE FIX
Listing writes down each appointment it offered, with the identifiers the
cancellation will need. The model names a short opaque ref and nothing else; it
never sees an appointment UUID, a Square booking id or a Square location id, so
it cannot ask us to destroy something we did not offer.

Refs are monotonic across the call ('appt_1', 'appt_2', …), like slot refs, so a
ref never means two things inside one conversation.

The ref is consumed only once the provider confirms the cancellation. A failed
cancel leaves it usable — the caller should be able to try the same appointment
again rather than be told it has gone when it hasn't.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db import appointment_refs as db_ar

logger = logging.getLogger(__name__)

# Long enough to talk it through, short enough that nothing is destroyed on the
# strength of a list read out several minutes ago.
REF_TTL_MINUTES = 15

# A caller with more than this many live appointments is not going to be served
# by reading them all out; the assistant should take a message instead.
MAX_REFS_PER_CALL = 10

OK = "ok"
NOT_FOUND = "not_found"
EXPIRED = "expired"
ALREADY_CONSUMED = "already_consumed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_refs(
    *, vapi_call_id: str, tenant_id: str, caller_phone: str, appointments: list[dict],
) -> list[dict]:
    """Persist the candidates being offered. Returns the rows, each with its ref."""
    if not (vapi_call_id and tenant_id and caller_phone and appointments):
        return []

    try:
        offset = await db_ar.count_refs(vapi_call_id)
    except Exception as e:
        logger.warning("appointment_refs: could not count existing refs for %s: %s", vapi_call_id, e)
        offset = 0

    expires = (_now() + timedelta(minutes=REF_TTL_MINUTES)).isoformat()
    rows = []
    for i, a in enumerate(appointments[:MAX_REFS_PER_CALL], start=offset + 1):
        rows.append({
            "appointment_ref": f"appt_{i}",
            "vapi_call_id": vapi_call_id,
            "tenant_id": tenant_id,
            "appointment_id": a["id"],
            "caller_phone": caller_phone,
            "tenant_location_id": a.get("tenant_location_id") or None,
            "provider_location_id": a.get("provider_location_id") or None,
            "provider_booking_id": a.get("google_event_id") or None,
            "service": a.get("service") or None,
            "start_at_utc": a["appointment_datetime"],
            "expires_at": expires,
        })

    try:
        await db_ar.insert_refs(rows)
    except Exception as e:
        # Without refs there is nothing to cancel BY, which is the safe direction:
        # the caller is asked to try again rather than having something guessed.
        logger.error("appointment_refs: persist failed for call %s: %s", vapi_call_id, e)
        return []
    return rows


async def resolve_for_cancel(
    *, vapi_call_id: str, appointment_ref: str, tenant_id: str, caller_phone: str,
) -> tuple[str, dict | None]:
    """Validate a ref. Returns (status, ref_row). Fails closed on every branch.

    Wrong call, wrong tenant and wrong caller are all simply NOT_FOUND — they are
    predicates on the lookup rather than checks after it, so there is no ordering
    in which one of them can be skipped.
    """
    if not (vapi_call_id and appointment_ref and tenant_id and caller_phone):
        return NOT_FOUND, None

    try:
        row = await db_ar.get_ref(vapi_call_id, appointment_ref.strip(), tenant_id, caller_phone)
    except Exception as e:
        logger.error("appointment_refs: lookup failed for %s/%s: %s",
                     vapi_call_id, appointment_ref, e)
        return NOT_FOUND, None
    if not row:
        return NOT_FOUND, None

    if row.get("consumed_at"):
        return ALREADY_CONSUMED, row

    try:
        expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= _now():
            return EXPIRED, row
    except Exception:
        return EXPIRED, row

    return OK, row


async def claim(vapi_call_id: str, appointment_ref: str) -> bool:
    """Take the ref for a destructive act — the boundary two concurrent tool calls
    compete at. Only one can win; the loser must not reach the provider."""
    try:
        return await db_ar.consume_ref(vapi_call_id, appointment_ref)
    except Exception as e:
        logger.error("appointment_refs: claim failed for %s/%s: %s", vapi_call_id, appointment_ref, e)
        return False


async def release(vapi_call_id: str, appointment_ref: str) -> None:
    """Give the ref back after a provider failure, so a retry is possible."""
    try:
        await db_ar.release_ref(vapi_call_id, appointment_ref)
    except Exception as e:
        logger.warning("appointment_refs: release failed for %s/%s: %s",
                       vapi_call_id, appointment_ref, e)


async def clear(vapi_call_id: str) -> None:
    try:
        await db_ar.delete_refs(vapi_call_id)
    except Exception as e:
        logger.warning("appointment_refs: cleanup failed for %s: %s", vapi_call_id, e)


async def purge_expired() -> int:
    try:
        return await db_ar.purge_expired_refs(_now().isoformat())
    except Exception as e:
        logger.error("appointment_refs: TTL purge failed: %s", e)
        return 0


def describe(row: dict, location_name: str, timezone_name: str) -> str:
    """'a Consultation in Cork on Monday, September 14 at 2:00 PM'.

    Location name, service, date and time — the four things a person can actually
    tell two appointments apart by. No identifier of any kind.
    """
    svc = row.get("service") or "appointment"
    when = str(row.get("start_at_utc") or "")
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo(timezone_name or "UTC"))
        h = dt.hour % 12 or 12
        when = (f"{dt.strftime('%A, %B')} {dt.day} at "
                f"{h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}")
    except Exception:
        pass
    where = f" in {location_name}" if location_name else ""
    return f"a {svc}{where} on {when}"


def spoken_list(described: list[tuple[str, str]]) -> str:
    """'a Consultation in Cork on Monday at 2:00 PM [appt_1], a Dress Fitting …'

    The refs are in the tool RESULT, never in anything read aloud; the schema tells
    the model to speak the description and pass the matching ref back.
    """
    return ", ".join(f"{text} [{ref}]" for ref, text in described)
