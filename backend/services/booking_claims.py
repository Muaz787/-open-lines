"""
One booking per slot per call, safe across concurrent requests, retries and crashes.

A Google or Outlook booking made during a call claims its slot before touching the
calendar (migration 045). The claim decides who may create the event; its attempt
number decides the event's id, so the calendar itself refuses a second copy:

  * Google: the event is inserted with that id, and a second insert is a 409.
  * Outlook: the id is sent as transactionId, which Graph uses to drop repeats.

Outcomes of acquire():
  ACQUIRED     this request owns the slot and may create the event
  BOOKED       the slot is already booked in this call: return it, create nothing
  IN_PROGRESS  another request is booking this slot right now
  CALL_BUSY    another slot in this call is being booked right now
  ERROR        the claim store could not be read or written: book nothing

A pending claim older than STALE_SECONDS belongs to a request that died. It is
taken over at the SAME attempt, so the takeover re-sends the same event id and
finds the event if the dead request had already made it.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from db import booking_claims as db_bc

logger = logging.getLogger(__name__)

ACQUIRED, BOOKED, IN_PROGRESS, CALL_BUSY, ERROR = (
    "acquired", "booked", "in_progress", "call_busy", "error")

# Longer than the booking tool's 35-second timeout, so a live request is never
# taken over, and short enough that a crashed one doesn't block the call.
STALE_SECONDS = 90


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slot_key(start_dt: datetime) -> str:
    return start_dt.astimezone(timezone.utc).isoformat()


def event_id(claim: dict) -> str:
    """Deterministic calendar event id for this claim's attempt.

    Google requires 5-1024 characters from base32hex (0-9, a-v); Outlook accepts
    any string as transactionId. Same claim and attempt, same id.
    """
    raw = f"{claim['tenant_id']}|{claim['vapi_call_id']}|{claim['slot_start']}|{claim['attempt']}"
    digest = base64.b32hexencode(hashlib.sha256(raw.encode()).digest()).decode().lower().rstrip("=")
    return "ol" + digest[:40]


def _age_seconds(claim: dict) -> float:
    try:
        at = datetime.fromisoformat(str(claim["updated_at"]).replace("Z", "+00:00"))
    except Exception:
        return 0.0
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (_now() - at).total_seconds()


async def acquire(tenant_id: str, call_id: str, caller_phone: str,
                  start_dt: datetime) -> tuple[str, dict | None]:
    slot = slot_key(start_dt)
    try:
        if await db_bc.insert_pending({"tenant_id": tenant_id, "vapi_call_id": call_id,
                                       "slot_start": slot, "caller_phone": caller_phone,
                                       "attempt": 1}):
            return ACQUIRED, await db_bc.get(tenant_id, call_id, slot)
        existing = await db_bc.get(tenant_id, call_id, slot)
        if existing is None:
            return CALL_BUSY, None            # the per-call index refused it
        if existing["state"] == "booked":
            return BOOKED, existing
        if existing["state"] == "failed":
            # A definite failure created nothing: try again with a fresh event id.
            won = await db_bc.transition(existing, {"state": "pending",
                                                    "attempt": existing["attempt"] + 1})
            return (ACQUIRED, won) if won else (IN_PROGRESS, existing)
        if _age_seconds(existing) < STALE_SECONDS:
            return IN_PROGRESS, existing
        # Abandoned. Same attempt, so the same event id: if the dead request made
        # the event, creating it again returns that one instead of a second.
        won = await db_bc.transition(existing, {"state": "pending"})
        if won:
            logger.warning("booking_claims: took over a stale claim for call %s slot %s",
                           call_id, slot)
            return ACQUIRED, won
        return IN_PROGRESS, existing
    except Exception as e:
        logger.error("booking_claims: claim store failed for call %s: %s", call_id, e)
        return ERROR, None


async def restart(claim: dict) -> tuple[str, dict | None]:
    """A booked slot whose appointment was later cancelled in this call can be
    booked again, under a new attempt and so a new event id."""
    try:
        won = await db_bc.transition(claim, {"state": "pending", "attempt": claim["attempt"] + 1,
                                             "appointment_id": None, "provider_event_id": None})
    except Exception as e:
        logger.error("booking_claims: restart failed for call %s: %s", claim.get("vapi_call_id"), e)
        return ERROR, None
    return (ACQUIRED, won) if won else (IN_PROGRESS, claim)


def _same_instant(a: str, b: str) -> bool:
    try:
        return (datetime.fromisoformat(str(a).replace("Z", "+00:00"))
                == datetime.fromisoformat(str(b).replace("Z", "+00:00")))
    except Exception:
        return False


async def settle_from_appointments(tenant_id: str, call_id: str, appointments: list[dict]) -> None:
    """A pending claim whose appointment already exists was left by a request that
    wrote the row and died before marking it booked. Mark it booked now, so it
    can't hold up the call's other bookings or be mistaken for one in flight."""
    try:
        pending = await db_bc.pending_for_call(tenant_id, call_id)
    except Exception as e:
        logger.warning("booking_claims: could not read pending claims for call %s: %s", call_id, e)
        return
    for claim in pending:
        appt = next((a for a in appointments
                     if _same_instant(a.get("appointment_datetime"), claim["slot_start"])), None)
        if appt:
            try:
                if await db_bc.transition(claim, {"state": "booked", "appointment_id": appt["id"]}):
                    logger.warning("booking_claims: settled an abandoned claim for call %s slot %s",
                                   call_id, claim["slot_start"])
            except Exception as e:
                logger.warning("booking_claims: could not settle claim for call %s: %s", call_id, e)


async def note_event(claim: dict, provider_event_id: str) -> dict:
    """Record the event while still pending, so a recovery can see it was made."""
    try:
        return await db_bc.transition(claim, {"provider_event_id": provider_event_id}) or claim
    except Exception as e:
        logger.warning("booking_claims: could not record event for call %s: %s",
                       claim.get("vapi_call_id"), e)
        return claim


async def mark_booked(claim: dict, appointment_id: str | None) -> None:
    try:
        if not await db_bc.transition(claim, {"state": "booked", "appointment_id": appointment_id}):
            logger.error("booking_claims: claim for call %s changed before it could be marked booked",
                         claim.get("vapi_call_id"))
    except Exception as e:
        # Left pending: a later request takes it over at the same attempt and finds
        # the event, so nothing is created twice.
        logger.error("booking_claims: could not mark call %s booked: %s", claim.get("vapi_call_id"), e)


async def mark_failed(claim: dict) -> None:
    """Only for a DEFINITE failure: the calendar is known not to have the event."""
    try:
        await db_bc.transition(claim, {"state": "failed"})
    except Exception as e:
        logger.error("booking_claims: could not mark call %s failed: %s", claim.get("vapi_call_id"), e)
