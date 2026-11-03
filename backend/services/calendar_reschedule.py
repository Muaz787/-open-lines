"""
Move a Google or Outlook appointment to a new time, in place.

Both providers move an event with one PATCH: the event, the appointment row and
anything linked to that row (a deposit, a payment link) stay exactly as they were.
That is why this is not Square's create-then-cancel engine: there is no second
booking to create, nothing to cancel, and no payment to carry across.

Every move:
  1. is for an appointment the caller chose from a list (appointment_ref) and
     that is still theirs, still active and still at the time they heard;
  2. keeps its service, duration and team member, and targets a time the
     business is open, the team member is free and the calendar is free;
  3. owns the appointment (migration 021) under a durable operation (046), so
     concurrent and retried requests cannot both move it;
  4. settles an earlier unknown outcome by READING the event before anything
     else is sent;
  5. reports success only after re-reading the event and our row and finding
     both at the new time.

Payment status is never touched, nothing is charged and nothing is refunded.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from db import calendar_moves as db_cm
from db import mutation_claims as db_mc
from db import supabase as db
from services import appointment_refs, mutation_ownership, relative_dates
from services import calendar as cal_svc
from services import ms_calendar as ms_cal_svc
from services.calendar import CalendarTokenExpiredError
from services.ms_calendar import MsCalendarTokenExpiredError

logger = logging.getLogger(__name__)

# Outcomes.
COMPLETED = "completed"
ALREADY_THERE = "already_there"
NOT_FREE = "not_free"
CLOSED = "closed"
BUSY = "busy"
FAILED = "failed"              # provider refused; the original stands
UNKNOWN = "unknown"            # provider outcome unknown; nothing more may be sent
LOCAL_PENDING = "local_pending"  # moved at the provider; our row not yet updated
STALE = "stale"                # this worker no longer owns the operation; it did nothing
INVALID_REF = "invalid_ref"
EXPIRED_REF = "expired_ref"
NOT_ELIGIBLE = "not_eligible"
CHANGED = "changed"            # the appointment changed since it was listed
DATE_REFUSED = "date_refused"
TEMPORARY = "temporary"

STALE_SECONDS = 120
_ACTIVE = ("confirmed", "pending_payment")
_NO_RETRY = (" Do NOT call reschedule_appointment, book_appointment or cancel_appointment "
             "again for this appointment in this call.")


def _provider(tenant: dict) -> tuple[str | None, str]:
    if tenant.get("square_appointments_enabled"):
        return None, ""
    if tenant.get("google_refresh_token"):
        return tenant["google_refresh_token"], "google"
    if tenant.get("microsoft_refresh_token"):
        return tenant["microsoft_refresh_token"], "microsoft"
    return None, ""


def supported(tenant: dict) -> bool:
    return bool(_provider(tenant)[0])


def _svc(provider: str):
    return ms_cal_svc if provider == "microsoft" else cal_svc


def _start(appt: dict) -> datetime:
    dt = datetime.fromisoformat(str(appt.get("appointment_datetime") or "").replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _spoken(dt: datetime, tz) -> str:
    d = dt.astimezone(tz)
    h = d.hour % 12 or 12
    return f"{d.strftime('%A, %B')} {d.day} at {h}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def _same_instant(a: datetime | None, b: datetime | None) -> bool:
    return bool(a and b) and a.astimezone(timezone.utc) == b.astimezone(timezone.utc)


def _age_seconds(op: dict) -> float:
    try:
        at = datetime.fromisoformat(str(op["updated_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return 0.0
    return (datetime.now(timezone.utc) - at).total_seconds()


def _definite_failure(e: Exception) -> bool:
    if isinstance(e, (CalendarTokenExpiredError, MsCalendarTokenExpiredError)):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return 400 <= code < 500 and code not in (408, 409, 429)
    return False


# ── availability for THIS appointment at the new time ───────────────────────

async def slot_problem(tenant: dict, tenant_id: str, appt: dict, new_start: datetime,
                       refresh_token: str, provider: str) -> str | None:
    """None when the appointment can move there; otherwise CLOSED or NOT_FREE.

    Same rules as booking, with the appointment itself left out: its own event
    and its own seat must not stop it moving a few minutes."""
    from routers.tools import _parse_business_days
    tz = relative_dates.tenant_tz(tenant)
    local = new_start.astimezone(tz)
    duration = int(appt.get("duration_minutes") or tenant.get("appointment_duration_minutes") or 60)
    end = local + timedelta(minutes=duration)
    if local.weekday() not in _parse_business_days(tenant.get("business_days")):
        return CLOSED
    open_h = int(tenant.get("business_hours_start") or 9)
    close_h = int(tenant.get("business_hours_end") or 17)
    day_open = local.replace(hour=open_h, minute=0, second=0, microsecond=0)
    day_close = local.replace(hour=close_h, minute=0, second=0, microsecond=0)
    if local < day_open or end > day_close:
        return CLOSED
    bs, be = tenant.get("break_start"), tenant.get("break_end")
    if bs is not None and be is not None and int(be) > int(bs):
        b0 = local.replace(hour=int(bs), minute=0, second=0, microsecond=0)
        b1 = local.replace(hour=int(be), minute=0, second=0, microsecond=0)
        if local < b1 and end > b0:
            return CLOSED

    # Our own appointments: same staff member, or pooled capacity.
    day0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
    others = [a for a in await db.get_active_appointments_between(
                  tenant_id, day0.isoformat(), (day0 + timedelta(days=1)).isoformat())
              if str(a.get("id")) != str(appt["id"])]
    ranges, ours = [], {str(appt.get("google_event_id") or "")}
    for a in others:
        s = _start(a)
        e = s + timedelta(minutes=int(a.get("duration_minutes") or duration))
        if a.get("google_event_id"):
            ours.add(str(a["google_event_id"]))
        if appt.get("staff_id") and a.get("staff_id") != appt.get("staff_id"):
            continue
        ranges.append((s.astimezone(tz), e.astimezone(tz)))
    if appt.get("staff_id"):
        capacity = 1
    else:
        staff = await db.get_active_staff(tenant_id)
        capacity = len(staff) if staff else max(1, int(tenant.get("slot_capacity") or 1))
    if sum(1 for s, e in ranges if local < e and end > s) >= capacity:
        return NOT_FREE

    # The calendar itself, with this appointment's own event ignored.
    slots = await _svc(provider).list_free_slots(
        refresh_token=refresh_token, date_str=local.date().isoformat(),
        duration_minutes=duration, timezone=str(tz),
        exclude_event_id=str(appt.get("google_event_id") or "") or None,
        business_hours_start=open_h, business_hours_end=close_h,
        business_days=_parse_business_days(tenant.get("business_days")),
        break_start=int(bs) if bs is not None else None,
        break_end=int(be) if be is not None else None,
        slot_capacity=capacity, booked_ranges=ranges, our_event_ids=ours)
    return None if cal_svc._fmt_slot(local) in slots else NOT_FREE


# ── settling an operation by reading the provider ───────────────────────────

async def _read_square(tenant: dict, op: dict) -> tuple[str, dict]:
    """('ok', shape) | ('missing', {}) | ('unknown', {}) for a Square booking."""
    from services import square_booking
    try:
        token = await square_booking.get_access_token(tenant)
    except Exception as e:
        logger.warning("calendar_reschedule: no Square token for operation %s: %s", op["id"], e)
        return "unknown", {}
    if not token:
        return "unknown", {}
    status, booking = await square_booking.get_booking_detailed(token, op["provider_event_id"])
    if status == square_booking.FETCH_NOT_FOUND:
        return "missing", {}
    if status != square_booking.FETCH_FOUND:
        return "unknown", {}
    shape = square_booking.booking_shape(booking)
    if "CANCELLED" in shape["status"] or shape["status"] == "DECLINED":
        return "missing", shape
    return "ok", shape


async def _read_event_start(tenant: dict, op: dict) -> tuple[str, datetime | None]:
    """('ok', start) | ('missing', None) | ('unknown', None)."""
    if op["provider"] == "square":
        status, shape = await _read_square(tenant, op)
        return status, (shape.get("start") if status == "ok" else None)
    refresh_token, provider = _provider(tenant)
    if not refresh_token or provider != op["provider"]:
        return "unknown", None
    try:
        ev = await _svc(provider).get_event(refresh_token, op["provider_event_id"])
    except Exception as e:
        logger.warning("calendar_reschedule: could not read event for operation %s: %s", op["id"], e)
        return "unknown", None
    if not ev or ev.get("status") == "cancelled" or ev.get("isCancelled"):
        return "missing", None
    return "ok", _svc(provider).event_start(ev)


async def _release(op: dict) -> None:
    try:
        await db_mc.release_claim(op["appointment_id"], op["claim_token"], op["claimed_at"])
    except Exception as e:
        logger.error("calendar_reschedule: could not release appointment %s: %s",
                     op["appointment_id"], e)


async def verify_provider(tenant: dict, op: dict) -> str:
    """Re-read the event: 'ok' when it is active and starts AND ends exactly where
    this operation moved it; otherwise 'unreadable', 'missing' or 'mismatch'.

    For Square the team member and service must also be the ones frozen on the
    operation: a booking someone else changed is not proof of our move."""
    if op["provider"] == "square":
        status, shape = await _read_square(tenant, op)
        if status == "unknown":
            return "unreadable"
        if status == "missing":
            return "missing"
        to = datetime.fromisoformat(str(op["to_start_utc"]).replace("Z", "+00:00"))
        end = to + timedelta(minutes=int(op["duration_minutes"]))
        same_parts = (shape["segments"] == 1
                      and shape["team_member_id"] == (op.get("team_member_id") or "")
                      and shape["service_variation_id"] == (op.get("service_variation_id") or ""))
        if same_parts and _same_instant(shape["start"], to) and _same_instant(shape["end"], end):
            return "ok"
        return "mismatch"
    refresh_token, provider = _provider(tenant)
    if not refresh_token or provider != op["provider"]:
        return "unreadable"
    try:
        ev = await _svc(provider).get_event(refresh_token, op["provider_event_id"])
    except Exception as e:
        logger.warning("calendar_reschedule: could not re-read event for operation %s: %s", op["id"], e)
        return "unreadable"
    if not ev or ev.get("status") == "cancelled" or ev.get("isCancelled"):
        return "missing"
    to = datetime.fromisoformat(str(op["to_start_utc"]).replace("Z", "+00:00"))
    end = to + timedelta(minutes=int(op["duration_minutes"]))
    if _same_instant(_svc(provider).event_start(ev), to) and _same_instant(_svc(provider).event_end(ev), end):
        return "ok"
    return "mismatch"


async def _finish_local(tenant: dict, op: dict) -> str:
    """The provider reports the new time. Prove it by re-reading the event, then
    write our row, re-read it, and only then complete.

    Anything short of proof keeps the operation live and the appointment owned,
    for recovery or a person to settle."""
    checked = await verify_provider(tenant, op)
    if checked != "ok":
        if checked != "unreadable":
            logger.error("calendar_reschedule: INCIDENT — after moving, operation %s finds the "
                         "event %s; leaving it for a person", op["id"], checked)
            await db_cm.transition(op, ("provider_moved",), {"detail": f"provider {checked}"})
        return UNKNOWN
    # Write, complete and release in ONE transaction, and only while this
    # operation still owns the appointment. A worker that paused after reading the
    # provider can't overwrite a newer move or a cancellation, release a newer
    # claim, or go on to send a confirmation.
    try:
        result = await db_cm.finish(op["id"], op["claim_token"])
    except Exception as e:
        logger.error("calendar_reschedule: RECONCILIATION REQUIRED — appointment %s moved at the "
                     "provider; finishing failed: %s", op["appointment_id"], e)
        return LOCAL_PENDING
    if result in ("not_owner", "missing"):
        logger.warning("calendar_reschedule: operation %s is no longer the owner (%s); not writing",
                       op["id"], result)
        return STALE
    if result != "completed":
        logger.error("calendar_reschedule: INCIDENT — operation %s could not finish (%s)",
                     op["id"], result)
        return UNKNOWN
    to = datetime.fromisoformat(str(op["to_start_utc"]).replace("Z", "+00:00"))
    appt = await db.get_appointment_by_id(op["appointment_id"])
    if not appt or not _same_instant(_start(appt), to):
        return UNKNOWN
    return COMPLETED


async def settle(tenant: dict, op: dict, *, known_stale: bool = False) -> str:
    """Bring a live operation to an outcome by reading, never by re-sending."""
    if op["state"] == "provider_moved":
        return await _finish_local(tenant, op)
    status, start = await _read_event_start(tenant, op)
    to = datetime.fromisoformat(str(op["to_start_utc"]).replace("Z", "+00:00"))
    frm = datetime.fromisoformat(str(op["from_start_utc"]).replace("Z", "+00:00"))
    if status == "ok" and _same_instant(start, to):
        moved = await db_cm.transition(op, ("in_progress", "unknown"), {"state": "provider_moved"})
        return await _finish_local(tenant, moved) if moved else UNKNOWN
    if status == "ok" and _same_instant(start, frm):
        # Still at the old time. Only an operation old enough that no request
        # can still be in flight is declared failed; a fresh one stays unknown.
        if known_stale or _age_seconds(op) >= STALE_SECONDS:
            if await db_cm.transition(op, ("in_progress", "unknown"), {"state": "failed",
                                                                       "detail": "not applied"}):
                await _release(op)
                return FAILED
        return UNKNOWN
    if status != "unknown":
        logger.error("calendar_reschedule: INCIDENT — operation %s finds the event %s "
                     "(start %s); leaving it for a person", op["id"], status, start)
    return UNKNOWN


async def run_recovery(limit: int = 10) -> dict:
    """Settle operations a request left behind. Reads only; never re-sends a move."""
    before = (datetime.now(timezone.utc) - timedelta(seconds=STALE_SECONDS)).isoformat()
    try:
        ops = await db_cm.list_stale(before, limit)
    except Exception as e:
        logger.error("calendar_reschedule: recovery scan failed: %s", e)
        return {"error": str(e)[:200]}
    out: dict[str, int] = {}
    for op in ops:
        # One worker per operation per pass: the lease only matches the
        # updated_at this worker read, so a second worker gets nothing.
        leased = await db_cm.lease(op)
        if not leased:
            out["skipped"] = out.get("skipped", 0) + 1
            continue
        tenant = await db.get_tenant_by_id(leased["tenant_id"]) or {}
        # Listed because it was already stale; the lease just refreshed updated_at.
        result = await settle(tenant, leased, known_stale=True)
        out[result] = out.get(result, 0) + 1
    return out


# ── the move ────────────────────────────────────────────────────────────────

async def move(*, tenant: dict, tenant_id: str, call_id: str, caller_phone: str,
               appointment_ref: str, date_str: str, time_str: str,
               date_phrase: str = "") -> tuple[str, str]:
    """Returns (outcome, what the assistant may say)."""
    tz = relative_dates.tenant_tz(tenant)
    refresh_token, provider = _provider(tenant)
    if not refresh_token:
        return NOT_ELIGIBLE, "I can't move appointments for this business on the phone. Take a message for the team."

    ref_status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=call_id, appointment_ref=appointment_ref, tenant_id=tenant_id,
        caller_phone=caller_phone)
    if ref_status == appointment_refs.EXPIRED:
        return EXPIRED_REF, ("That list is out of date. Call reschedule_appointment with no "
                             "arguments to list the caller's appointments again.")
    consumed = ref_status == appointment_refs.ALREADY_CONSUMED and ref
    if ref_status != appointment_refs.OK and not consumed:
        return INVALID_REF, ("I couldn't find that appointment among the ones I listed. List the "
                             "caller's appointments again and confirm which one they mean.")

    checked, problem = relative_dates.check(date_str, date_phrase, tenant)
    if problem:
        return DATE_REFUSED, problem
    new_start, why = relative_dates.local_instant(checked, time_str, tz)
    if why == relative_dates.BAD_FORMAT:
        return DATE_REFUSED, "I need the new time as HH:MM. Confirm it with the caller and try again."
    if why:
        return DATE_REFUSED, (f"{time_str} on {checked} falls in the hour the clocks change, so "
                              "that time is unclear. Nothing has been moved. Ask the caller for "
                              "another time.")
    if new_start <= relative_dates._utcnow():
        return DATE_REFUSED, (f"{_spoken(new_start, tz)} has already passed. Nothing has been "
                              "moved. Ask the caller for a time later today or another day.")

    appt = await db.get_appointment_by_id(ref["appointment_id"])
    if not appt or str(appt.get("tenant_id")) != str(tenant_id) \
            or str(appt.get("caller_phone") or "") != caller_phone:
        return INVALID_REF, "I couldn't verify that appointment. Nothing has changed. Take a message for the team."

    # Anything left unfinished for this appointment is settled first, by reading.
    live = await db_cm.live_for_appointment(appt["id"])
    if live and live["state"] == "in_progress" and _age_seconds(live) < STALE_SECONDS:
        # Another request is moving it right now. Nothing to settle yet.
        return BUSY, ("That appointment is being changed right now, so nothing was done. Ask "
                      "the caller to give us a minute." + _NO_RETRY)
    if live:
        outcome = await settle(tenant, live)
        appt = await db.get_appointment_by_id(appt["id"]) or appt
        if outcome != COMPLETED:
            return outcome, _message(outcome, tz, appt, None)

    if consumed:
        # This reference already moved its appointment in this call. A retry is
        # answered from the re-read row; it never sends a second move.
        if _same_instant(_start(appt), new_start):
            return ALREADY_THERE, (f"Already done, re-read just now: the "
                                   f"{appt.get('service') or 'appointment'} is on "
                                   f"{_spoken(new_start, tz)}. Don't move it again.")
        return CHANGED, ("That appointment was already changed in this call. Nothing more has "
                         "been moved. List the caller's appointments again before any other change.")
    if (appt.get("status") or "") not in _ACTIVE:
        return NOT_ELIGIBLE, ("That appointment isn't active any more, so there's nothing to "
                              "move. Tell the caller, and offer a new booking if they want one.")
    if _same_instant(_start(appt), new_start):
        return ALREADY_THERE, (f"Re-read just now: the {appt.get('service') or 'appointment'} is "
                               f"already on {_spoken(new_start, tz)}. Nothing needs changing.")
    if not appt.get("google_event_id"):
        return NOT_ELIGIBLE, ("I can't move that one automatically. Nothing has changed. Take a "
                              "message for the team.")
    # The time the caller heard when choosing must still be the time it has.
    if str(ref.get("start_at_utc") or "") and not _same_instant(
            _start({"appointment_datetime": ref["start_at_utc"]}), _start(appt)):
        return CHANGED, ("That appointment has changed since I read it out. Nothing has been "
                         "moved. List the caller's appointments again.")

    try:
        problem = await slot_problem(tenant, tenant_id, appt, new_start, refresh_token, provider)
    except Exception as e:
        logger.error("calendar_reschedule: availability check failed for %s: %s", tenant_id, e)
        return TEMPORARY, ("I couldn't check the calendar just now, so nothing has been moved. "
                           "Offer to try again, or take a message for the team.")
    if problem:
        return problem, _message(problem, tz, appt, new_start)

    # ── own it, re-read it, record it, then move it ─────────────────────────
    op_id = str(uuid.uuid4())
    own, claim = await mutation_ownership.acquire_for_reschedule(appt["id"], tenant_id, op_id)
    if own == mutation_ownership.BUSY:
        return BUSY, ("That appointment is being changed right now, so nothing was done. Ask "
                      "the caller to give us a minute." + _NO_RETRY)
    if own != mutation_ownership.ACQUIRED or claim is None:
        return TEMPORARY, "I had trouble with that just now. Nothing has changed. Offer to try again."

    current = await db.get_appointment_by_id(appt["id"])
    if (not current or (current.get("status") or "") not in _ACTIVE
            or not _same_instant(_start(current), _start(appt))
            or str(current.get("google_event_id") or "") != str(appt["google_event_id"])):
        await mutation_ownership.release(claim)
        return CHANGED, ("That appointment changed while I was moving it. Nothing has been moved. "
                         "List the caller's appointments again.")

    duration = int(current.get("duration_minutes") or tenant.get("appointment_duration_minutes") or 60)
    op = await db_cm.insert({
        "id": op_id, "tenant_id": tenant_id, "appointment_id": current["id"],
        "vapi_call_id": call_id or None, "provider": provider,
        "provider_event_id": current["google_event_id"],
        "from_start_utc": _start(current).astimezone(timezone.utc).isoformat(),
        "to_start_utc": new_start.astimezone(timezone.utc).isoformat(),
        "duration_minutes": duration, "state": "in_progress",
        "claim_token": claim.token, "claimed_at": claim.claimed_at})
    if not op:
        await mutation_ownership.release(claim)
        return BUSY, "Another change to that appointment is still being settled. Nothing was done." + _NO_RETRY

    try:
        await _svc(provider).patch_event(refresh_token, current["google_event_id"], new_start,
                                         duration, str(tz))
        moved = await db_cm.transition(op, ("in_progress",), {"state": "provider_moved"})
        outcome = await _finish_local(tenant, moved) if moved else UNKNOWN
    except Exception as e:
        if _definite_failure(e):
            logger.error("calendar_reschedule: provider refused the move for %s: %s", current["id"], e)
            if await db_cm.transition(op, ("in_progress",), {"state": "failed", "detail": str(e)[:200]}):
                await _release(op)
            outcome = FAILED
        else:
            logger.error("calendar_reschedule: move outcome unknown for %s: %s", current["id"], e)
            await db_cm.transition(op, ("in_progress",), {"state": "unknown", "detail": str(e)[:200]})
            fresh = await db_cm.get(op_id) or op
            outcome = await settle(tenant, fresh)

    final = await db.get_appointment_by_id(current["id"]) or current
    if outcome == COMPLETED:
        await appointment_refs.claim(call_id, appointment_ref)
    return outcome, _message(outcome, tz, final, new_start)


def _message(outcome: str, tz, appt: dict, new_start: datetime | None) -> str:
    svc = appt.get("service") or "appointment"
    now_at = _spoken(_start(appt), tz)
    to = _spoken(new_start, tz) if new_start else ""
    return {
        COMPLETED: (f"Done, re-read just now: the {svc} is moved to {now_at}. Tell the caller the "
                    f"new day and time, saying the time exactly as "
                    f"\"{relative_dates.spoken_clock(_start(appt).astimezone(tz))}\"."),
        NOT_FREE: (f"{to} isn't free for this {svc}. Nothing has been moved. Call check_availability "
                   "for that day and offer the caller the open times."),
        CLOSED: (f"We're not open for a {svc} at {to}. Nothing has been moved. Offer a time within "
                 "opening hours."),
        FAILED: (f"The calendar refused the change, so the {svc} is still on {now_at}. Tell the "
                 "caller nothing has changed, and offer another time or a message for the team."),
        UNKNOWN: (f"I couldn't confirm whether the {svc} moved. Tell the caller the team will "
                  "confirm the time with them." + _NO_RETRY),
        LOCAL_PENDING: (f"The business's calendar has the {svc} at {to or now_at}, but our own "
                        "record hasn't caught up. Tell the caller it's moved in the calendar and the "
                        "team will confirm." + _NO_RETRY),
    }.get(outcome, "I had trouble with that just now. Nothing has changed. Offer to try again.")
