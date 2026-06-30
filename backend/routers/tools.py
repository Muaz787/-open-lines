"""
Vapi mid-call tool endpoints.

Vapi calls these URLs while a call is in progress.  Each endpoint receives a
POST with the tool-call arguments and must return a { "results": [...] } JSON
response that the AI uses to continue the conversation.
"""

import difflib
import json
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from typing import Annotated
from fastapi import APIRouter, HTTPException, Request, Header, Depends
from services import analytics
from services import calendar as cal_svc
from services.calendar import CalendarTokenExpiredError
from services import ms_calendar as ms_cal_svc
from services.ms_calendar import MsCalendarTokenExpiredError
from services import square_booking
from services import telephony
from services.ratelimit import limiter, tenant_key
from services.security import verify_vapi_server_secret
from db import supabase as db

logger = logging.getLogger(__name__)


async def _require_vapi_secret(x_vapi_secret: Annotated[str | None, Header()] = None) -> None:
    """Mid-call tool endpoints are only ever called by Vapi's servers. Gate the
    whole router on Vapi's shared secret so a tenant UUID alone can't be used to
    trigger bookings, deposits, or SMS (smishing/abuse prevention)."""
    verify_vapi_server_secret(x_vapi_secret)


router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(_require_vapi_secret)])


def _match_staff(requested: str, active_staff: list) -> dict | None:
    """Resolve a caller-requested team member name to a roster member, tolerant of
    AI mis-transcriptions (e.g. 'Shayd' -> 'Shahid'). Returns the canonical staff
    row, or None if there's no confident match (caller should be asked to clarify)."""
    requested = (requested or "").strip().lower()
    if not requested or not active_staff:
        return None
    by_name = {(s.get("name") or "").strip().lower(): s for s in active_staff if s.get("name")}
    # 1) exact match
    if requested in by_name:
        return by_name[requested]
    # 2) first-name / containment match
    req_first = requested.split()[0]
    for nm, s in by_name.items():
        if requested in nm or nm in requested or req_first == nm.split()[0]:
            return s
    # 3) fuzzy (handles mis-hearings); cutoff tuned to accept Shayd->Shahid, reject far names
    close = difflib.get_close_matches(requested, list(by_name.keys()), n=1, cutoff=0.6)
    if close:
        return by_name[close[0]]
    # 4) fuzzy on first names only
    first_map = {nm.split()[0]: s for nm, s in by_name.items()}
    close = difflib.get_close_matches(req_first, list(first_map.keys()), n=1, cutoff=0.6)
    return first_map[close[0]] if close else None

_CALENDAR_ERROR_MSG = (
    "I'm having a little trouble accessing the calendar right now. "
    "I'll make sure the team follows up with you shortly to confirm a time."
)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _parse_business_days(raw) -> list[int]:
    """Normalize a tenant's business_days value to a list of ints (Mon=0..Sun=6).
    Defaults to Mon-Fri when missing/invalid."""
    default = [0, 1, 2, 3, 4]
    if raw is None:
        return default
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return default
    if isinstance(raw, list):
        days = [int(d) for d in raw if isinstance(d, (int, float, str)) and str(d).strip().lstrip("-").isdigit()]
        days = [d for d in days if 0 <= d <= 6]
        return days or default
    return default


def _format_open_days(days: list[int]) -> str:
    """Human-readable open-days phrase, e.g. 'Monday through Friday' or 'Saturday and Sunday'."""
    if not days:
        return "by appointment"
    s = sorted(set(days))
    # Contiguous run → "X through Y"
    if s == list(range(s[0], s[-1] + 1)) and len(s) > 1:
        return f"{_DAY_NAMES[s[0]]} through {_DAY_NAMES[s[-1]]}"
    names = [_DAY_NAMES[d] for d in s]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _parse_tool_call(body: dict) -> tuple[str, str, dict]:
    """Return (tool_call_id, call_id, arguments_dict)."""
    msg = body.get("message", body)
    tool_calls = msg.get("toolCallList", [])
    if not tool_calls:
        raise ValueError("No toolCallList in payload")
    tc = tool_calls[0]
    tc_id    = tc.get("id", "")
    call_id  = (msg.get("call") or {}).get("id", "")
    raw_args = tc.get("function", {}).get("arguments", "{}")
    args     = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    return tc_id, call_id, args


def _result(tc_id: str, text: str) -> dict:
    return {"results": [{"toolCallId": tc_id, "result": text}]}


def _calendar_provider(tenant: dict) -> tuple[str | None, str]:
    """Return (refresh_token, provider) where provider is 'google', 'microsoft', or ''.
    Google takes priority when both are connected."""
    g = tenant.get("google_refresh_token")
    if g:
        return g, "google"
    m = tenant.get("microsoft_refresh_token")
    if m:
        return m, "microsoft"
    return None, ""


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/caller-lookup
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/caller-lookup")
@limiter.limit("60/minute", key_func=tenant_key)
async def caller_lookup(request: Request, tenant_id: str, body: dict):
    try:
        tc_id, _, _ = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/caller-lookup: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    msg = body.get("message", body)
    caller_phone: str = (msg.get("call") or {}).get("customer", {}).get("number", "")

    if not caller_phone:
        return _result(tc_id, "new_caller")

    try:
        lead = await db.get_lead_by_phone(tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/caller-lookup: lead lookup failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "new_caller")

    if not lead:
        logger.info("tools/caller-lookup: new caller %s for tenant %s", caller_phone, tenant_id)
        return _result(tc_id, "new_caller")

    name = lead.get("name") or ""
    summary = lead.get("summary") or ""

    lines = [f"returning_caller: {name}" if name else "returning_caller: (name unknown)"]
    if summary:
        lines.append(f"last_call_summary: {summary}")

    try:
        upcoming = await db.get_upcoming_appointment_by_phone(tenant_id, caller_phone)
        if upcoming:
            tenant = await db.get_tenant_by_id(tenant_id)
            tz_str = (tenant or {}).get("calendar_timezone") or "America/Toronto"
            appt_dt_raw = upcoming.get("appointment_datetime", "")
            service = upcoming.get("service", "appointment")
            try:
                appt_dt = datetime.fromisoformat(appt_dt_raw)
                if appt_dt.tzinfo is None:
                    appt_dt = appt_dt.replace(tzinfo=ZoneInfo("UTC"))
                appt_dt = appt_dt.astimezone(ZoneInfo(tz_str))
                h = appt_dt.hour % 12 or 12
                ampm = "AM" if appt_dt.hour < 12 else "PM"
                friendly = f"{appt_dt.strftime('%A, %B')} {appt_dt.day} at {h}:{appt_dt.minute:02d} {ampm}"
                lines.append(f"upcoming_appointment: {service} on {friendly}")
            except Exception:
                lines.append(f"upcoming_appointment: {service}")
    except Exception as e:
        logger.warning("tools/caller-lookup: appointment lookup failed for tenant %s: %s", tenant_id, e)

    result_text = "\n".join(lines)
    logger.info("tools/caller-lookup: recognized caller %s for tenant %s", caller_phone, tenant_id)
    return _result(tc_id, result_text)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/availability
# ---------------------------------------------------------------------------

def _match_square_service(requested: str, services: list) -> dict | None:
    """Resolve a spoken service name to a cached Square service variation."""
    requested = (requested or "").strip().lower()
    if not services:
        return None
    if not requested:
        return services[0]
    names = {(s.get("name") or "").strip().lower(): s for s in services if s.get("name")}
    for nm, s in names.items():
        if requested in nm or nm in requested:
            return s
    close = difflib.get_close_matches(requested, list(names.keys()), n=1, cutoff=0.5)
    return names[close[0]] if close else services[0]


async def _square_availability_response(
    tc_id: str, tenant: dict, tenant_id: str, args: dict, date_str: str, prefix: str,
):
    """Square Appointments availability path — Square computes the slots; we map a
    spoken service/staff to Square IDs and pass through SearchAvailability."""
    services = await db.get_square_services(tenant_id, bookable_only=True)
    if not services:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    chosen = _match_square_service(args.get("service", ""), services)
    team_ids = list(chosen.get("team_member_ids") or [])

    # Optional "with <name>" — restrict to that team member's calendar.
    staff_rows = await db.get_square_staff(tenant_id)
    if args.get("staff") and staff_rows:
        roster = [{"name": s.get("display_name"), "id": s.get("square_team_member_id")} for s in staff_rows]
        matched = _match_staff(args.get("staff", ""), roster)
        if matched:
            team_ids = [matched["id"]]
    if not team_ids:  # service has no explicit assignees → search across all active staff
        team_ids = [s["square_team_member_id"] for s in staff_rows]
    if not team_ids:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    timezone = tenant.get("square_location_timezone") or tenant.get("calendar_timezone") or "America/Toronto"
    try:
        slots = await square_booking.available_slot_strings(
            tenant, date_str=date_str, timezone=timezone,
            service_variation_id=chosen["square_variation_id"], team_member_ids=team_ids,
        )
    except Exception as e:
        logger.error("tools/availability: Square availability failed for %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        _fmt_date = date_type.fromisoformat(date_str).strftime("%B %d, %Y")
    except ValueError:
        _fmt_date = date_str
    if not slots:
        return _result(tc_id, prefix +
            f"Unfortunately there are no available slots on {_fmt_date}. Would you like to try a different day?")
    times_text = ", ".join(slots)
    return _result(tc_id, prefix +
        f"Available times on {_fmt_date} (full list — {slots[0]} through {slots[-1]}): {times_text}. "
        "If the caller asked for a specific time, check this exact list: confirm it if present, "
        "otherwise offer the closest available times. Do NOT claim a time is unavailable unless "
        "it is genuinely absent from this list. Only read a few options aloud, not the whole list.")


@router.post("/{tenant_id}/availability")
@limiter.limit("30/minute", key_func=tenant_key)
async def check_availability(request: Request, tenant_id: str, body: dict):
    logger.info("tools/availability raw payload for tenant %s: %s", tenant_id, body)
    try:
        tc_id, _, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/availability: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    date_str = args.get("date", "")
    period   = args.get("period", "any")

    if not date_str:
        return _result(tc_id, "I need a date to check availability. What date were you thinking?")

    # Correct past-year dates — guards against LLM training-data year confusion.
    # Silently advances the year to the current year and includes it in the response
    # so the AI knows to use the corrected year when speaking to the caller.
    _year_correction_prefix = ""
    _today_d = date_type.today()
    try:
        _pd = date_type.fromisoformat(date_str)
        if _pd.year < _today_d.year:
            corrected = f"{_today_d.year}-{_pd.month:02d}-{_pd.day:02d}"
            logger.warning(
                "tools/availability: corrected past year %d→%d for tenant %s (original: %s)",
                _pd.year, _today_d.year, tenant_id, date_str,
            )
            _year_correction_prefix = (
                f"[Date corrected: {date_str} is in the past — using {corrected} instead. "
                f"Today is {_today_d.strftime('%B %d, %Y')}.] "
            )
            date_str = corrected
    except ValueError:
        pass

    # Prefer AI-provided caller_phone from tool args (explicit, most reliable for reschedules).
    # Fall back to Vapi payload extraction for new bookings where the AI didn't pass it.
    msg_body   = body.get("message", body)
    _call_obj  = msg_body.get("call") or {}
    _customer  = _call_obj.get("customer") or {}
    caller_phone = (
        args.get("caller_phone", "")
        or _customer.get("number", "")
        or _customer.get("phoneNumber", "")
        or (msg_body.get("customer") or {}).get("number", "")
        or (msg_body.get("customer") or {}).get("phoneNumber", "")
    )

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/availability: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Square Appointments provider — Square owns availability (pass-through).
    # Gated on square_appointments_enabled, which stays OFF until P2 wires booking.
    if tenant.get("square_appointments_enabled"):
        return await _square_availability_response(
            tc_id, tenant, tenant_id, args, date_str, _year_correction_prefix)

    refresh_token, cal_provider = _calendar_provider(tenant)
    if not refresh_token:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    analytics.capture(
        analytics.distinct_id_for(tenant, tenant_id),
        "appointment_booking_started",
        {"tenant_id": tenant_id},
    )

    duration_minutes     = tenant.get("appointment_duration_minutes") or 60
    timezone             = tenant.get("calendar_timezone") or "America/Toronto"
    business_hours_start = int(tenant.get("business_hours_start") or 9)
    business_hours_end   = int(tenant.get("business_hours_end") or 17)
    business_days        = _parse_business_days(tenant.get("business_days"))
    break_start          = tenant.get("break_start")
    break_end            = tenant.get("break_end")
    break_start          = int(break_start) if break_start is not None else None
    break_end            = int(break_end) if break_end is not None else None

    # Closed-day early response — clearer than a generic "no slots" message
    try:
        _req_weekday = date_type.fromisoformat(date_str).weekday()
        if _req_weekday not in business_days:
            return _result(
                tc_id,
                _year_correction_prefix +
                f"We're closed on {_DAY_NAMES[_req_weekday]}s. "
                f"We're open {_format_open_days(business_days)}. Would one of those days work?"
            )
    except ValueError:
        pass

    # If the caller already has an appointment, exclude it from the busy list so the
    # agent doesn't falsely report the rescheduled slot as unavailable.
    # Primary: match by Google event ID (exact). Fallback: match by time range.
    exclude_event_id = None
    exclude_range    = None
    if caller_phone:
        try:
            existing = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
            if existing:
                exclude_event_id = existing.get("google_event_id") or None
                ex_start = datetime.fromisoformat(existing["appointment_datetime"])
                if ex_start.tzinfo is None:
                    ex_start = ex_start.replace(tzinfo=ZoneInfo(timezone))
                ex_end = ex_start + timedelta(minutes=duration_minutes)
                exclude_range = (ex_start, ex_end)
                logger.info(
                    "tools/availability: reschedule detected for %s — excluding event_id=%s (%s to %s)",
                    caller_phone, exclude_event_id, ex_start.isoformat(), ex_end.isoformat(),
                )
        except Exception as e:
            logger.warning("tools/availability: existing-appt check failed: %s", e)

    # Capacity per slot. Named-staff mode (tenant has active staff) sets it to the
    # staff count; otherwise it's the pooled slot_capacity. > 1 counts our own
    # bookings as seats instead of full blocks so the slot stays offerable until
    # all seats are taken. 1 keeps the single-resource behavior unchanged.
    try:
        _active_staff = await db.get_active_staff(tenant_id)
    except Exception:
        _active_staff = []
    # If the caller asked for a specific team member, show THAT person's schedule
    # (capacity 1, counting only their bookings); otherwise capacity = staff count.
    requested_staff = None
    if _active_staff:
        _req = (args.get("staff") or "").strip()
        if _req:
            requested_staff = _match_staff(_req, _active_staff)
        slot_capacity = 1 if requested_staff else len(_active_staff)
    else:
        slot_capacity = max(1, int(tenant.get("slot_capacity") or 1))
    booked_ranges = None
    our_event_ids = None
    if slot_capacity > 1 or requested_staff:
        try:
            _tz = ZoneInfo(timezone)
            _d = date_type.fromisoformat(date_str)
            _day_start = datetime(_d.year, _d.month, _d.day, tzinfo=_tz)
            _appts = await db.get_active_appointments_between(
                tenant_id, _day_start.isoformat(), (_day_start + timedelta(days=1)).isoformat())
            our_event_ids = set()
            booked_ranges = []
            for _a in _appts:
                _eid = _a.get("google_event_id")
                if _eid:
                    our_event_ids.add(_eid)
                # Free the seat of the appointment being rescheduled.
                if exclude_event_id and _eid and _eid == exclude_event_id:
                    continue
                # For a specific requested staff member, only THEIR bookings count.
                if requested_staff and _a.get("staff_id") != requested_staff["id"]:
                    continue
                _s = datetime.fromisoformat(_a["appointment_datetime"])
                if _s.tzinfo is None:
                    _s = _s.replace(tzinfo=_tz)
                _s = _s.astimezone(_tz)
                booked_ranges.append((_s, _s + timedelta(minutes=_a.get("duration_minutes") or duration_minutes)))
        except Exception as e:
            logger.warning("tools/availability: capacity fetch failed for tenant %s: %s", tenant_id, e)
            booked_ranges = our_event_ids = None

    _slot_kwargs = dict(
        refresh_token=refresh_token,
        date_str=date_str,
        duration_minutes=duration_minutes,
        timezone=timezone,
        period=period,
        exclude_event_id=exclude_event_id,
        exclude_range=exclude_range,
        business_hours_start=business_hours_start,
        business_hours_end=business_hours_end,
        business_days=business_days,
        break_start=break_start,
        break_end=break_end,
        slot_capacity=slot_capacity,
        booked_ranges=booked_ranges,
        our_event_ids=our_event_ids,
    )
    try:
        if cal_provider == "microsoft":
            slots = await ms_cal_svc.list_free_slots(**_slot_kwargs)
        else:
            slots = await cal_svc.list_free_slots(**_slot_kwargs)
    except (CalendarTokenExpiredError, MsCalendarTokenExpiredError):
        logger.error("tools/availability: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
        clear_field = "microsoft_refresh_token" if cal_provider == "microsoft" else "google_refresh_token"
        try:
            await db.update_tenant(tenant_id, {clear_field: None})
        except Exception:
            pass
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    except Exception as e:
        logger.error("tools/availability: calendar query failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Format date as "Month DD, YYYY" so the AI says the correct year to the caller
    try:
        _fmt_date = date_type.fromisoformat(date_str).strftime("%B %d, %Y")
    except ValueError:
        _fmt_date = date_str

    if not slots:
        return _result(
            tc_id,
            _year_correction_prefix +
            f"Unfortunately there are no available slots on {_fmt_date}. "
            "Would you like to try a different day?"
        )

    # Return ALL available slots so the AI can directly confirm any specific time
    # the caller requests — previously only the first 2 (then first 6) were returned,
    # causing the AI to wrongly say times later in the day were unavailable.
    times_text = ", ".join(slots)
    msg = (
        _year_correction_prefix +
        f"Available times on {_fmt_date} (full list — {slots[0]} through {slots[-1]}): {times_text}. "
        "If the caller asked for a specific time, check this exact list: confirm it if present, "
        "otherwise offer the closest available times. Do NOT claim a time is unavailable unless "
        "it is genuinely absent from this list. Only read a few options aloud, not the whole list."
    )
    return _result(tc_id, msg)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/book
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/book")
@limiter.limit("10/minute", key_func=tenant_key)
async def book_appointment(request: Request, tenant_id: str, body: dict):
    try:
        tc_id, call_id, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/book: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    # Prefer caller phone from Vapi call metadata (more reliable than AI-provided)
    msg = body.get("message", body)
    caller_phone_from_meta = (msg.get("call") or {}).get("customer", {}).get("number", "")

    caller_name  = args.get("caller_name", "")
    caller_phone = caller_phone_from_meta or args.get("caller_phone", "")
    service      = args.get("service", "Appointment")
    date_str     = args.get("date", "")
    time_str     = args.get("time", "")  # HH:MM 24-hour
    try:
        party_size = max(1, min(20, int(args.get("party_size") or 1)))
    except (TypeError, ValueError):
        party_size = 1

    if not date_str or not time_str:
        return _result(tc_id, "I need both a date and a time to complete the booking. Could you confirm those?")

    # Correct past-year dates — same guard as check_availability
    _today_d = date_type.today()
    try:
        _pd = date_type.fromisoformat(date_str)
        if _pd.year < _today_d.year:
            date_str = f"{_today_d.year}-{_pd.month:02d}-{_pd.day:02d}"
            logger.warning(
                "tools/book: corrected past year %d→%d for tenant %s",
                _pd.year, _today_d.year, tenant_id,
            )
    except ValueError:
        pass

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/book: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Square Appointments: P1 reads availability only — CreateBooking lands in P2.
    # Defensive guard so flipping the flag early can't write to the wrong calendar.
    if tenant.get("square_appointments_enabled"):
        logger.warning("tools/book: square_appointments_enabled but CreateBooking is P2 (tenant %s)", tenant_id)
        return _result(tc_id,
            "I've found that time for you. I'll have the team confirm and finalize your booking shortly.")

    refresh_token, cal_provider = _calendar_provider(tenant)
    duration_minutes = tenant.get("appointment_duration_minutes") or 60
    timezone         = tenant.get("calendar_timezone") or "America/Toronto"
    business_name    = tenant["business_name"]

    if not refresh_token:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        tz = ZoneInfo(timezone)
        naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        start_dt = naive_dt.replace(tzinfo=tz)
    except Exception as e:
        logger.error("tools/book: datetime parse failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "I couldn't parse that date and time. Could you say it again?")

    # Defense-in-depth guards — never book on a closed day or inside the daily break,
    # even if the AI tried to (the availability tool should already prevent this).
    business_days = _parse_business_days(tenant.get("business_days"))
    if start_dt.weekday() not in business_days:
        return _result(
            tc_id,
            f"I'm sorry, we're closed on {_DAY_NAMES[start_dt.weekday()]}s. "
            f"We're open {_format_open_days(business_days)}. Would you like to pick one of those days?"
        )
    _bs = tenant.get("break_start")
    _be = tenant.get("break_end")
    if _bs is not None and _be is not None and int(_be) > int(_bs):
        slot_end = start_dt + timedelta(minutes=duration_minutes)
        brk_start = start_dt.replace(hour=int(_bs), minute=0, second=0, microsecond=0)
        brk_end   = start_dt.replace(hour=int(_be), minute=0, second=0, microsecond=0)
        if start_dt < brk_end and slot_end > brk_start:
            h1 = int(_bs) % 12 or 12; ap1 = "AM" if int(_bs) < 12 else "PM"
            h2 = int(_be) % 12 or 12; ap2 = "AM" if int(_be) < 12 else "PM"
            return _result(
                tc_id,
                f"That time overlaps our daily break ({h1} {ap1}–{h2} {ap2}). "
                "Could we pick a time outside of that?"
            )

    # Look up the caller's existing appointment (reschedule flow) — needed both
    # for the capacity guard and to cancel the old calendar event.
    existing_appt = None
    if caller_phone:
        try:
            existing_appt = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
        except Exception as e:
            logger.warning("tools/book: appointment lookup failed for tenant %s: %s", tenant_id, e)

    # Capacity + staff guard. Named-staff mode (tenant has active staff) sets the
    # slot capacity to the staff count and assigns the booking to a staff member
    # (caller-requested name if free, else first-available). Pooled mode uses
    # slot_capacity. Runs BEFORE we cancel the old event so a full target slot
    # never costs the caller their existing booking.
    try:
        active_staff = await db.get_active_staff(tenant_id)
    except Exception as e:
        logger.warning("tools/book: staff fetch failed for tenant %s: %s", tenant_id, e)
        active_staff = []
    staff_mode = len(active_staff) >= 1
    slot_capacity = len(active_staff) if staff_mode else max(1, int(tenant.get("slot_capacity") or 1))

    chosen_staff = None
    _slot_full_msg = "I'm sorry — that time just filled up. Could we find another time that works for you?"
    try:
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        _day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        _day_appts = await db.get_active_appointments_between(
            tenant_id, _day_start.isoformat(), (_day_start + timedelta(days=1)).isoformat())
        taken = 0
        busy_staff_ids: set[str] = set()
        for _a in _day_appts:
            if existing_appt and _a.get("id") == existing_appt.get("id"):
                continue
            _s = datetime.fromisoformat(_a["appointment_datetime"])
            if _s.tzinfo is None:
                _s = _s.replace(tzinfo=tz)
            _s = _s.astimezone(tz)
            _e = _s + timedelta(minutes=_a.get("duration_minutes") or duration_minutes)
            if start_dt < _e and end_dt > _s:
                taken += 1
                if _a.get("staff_id"):
                    busy_staff_ids.add(_a["staff_id"])
        if taken >= slot_capacity:
            logger.info("tools/book: slot full for tenant %s at %s (taken=%d cap=%d)",
                        tenant_id, start_dt.isoformat(), taken, slot_capacity)
            return _result(tc_id, _slot_full_msg)

        if staff_mode:
            # Honor a caller-requested name: fuzzy-match it to the roster (tolerant
            # of mis-hearings) and store the CANONICAL name. If no confident match,
            # ask rather than guess. Otherwise assign the first staff member free.
            requested = (args.get("staff") or "").strip()
            if requested:
                chosen_staff = _match_staff(requested, active_staff)
                if not chosen_staff:
                    roster = ", ".join(s["name"] for s in active_staff)
                    return _result(
                        tc_id,
                        f"I'm not sure which team member you meant by '{requested}'. "
                        f"We have {roster}. Who would you like to book with?"
                    )
                if chosen_staff["id"] in busy_staff_ids:
                    return _result(
                        tc_id,
                        f"I'm sorry, {chosen_staff['name']} is already booked at that time. "
                        "Would another time work, or shall I book you with whoever's available?"
                    )
            if not chosen_staff:
                chosen_staff = next((s for s in active_staff if s["id"] not in busy_staff_ids), None)
            if not chosen_staff:
                return _result(tc_id, _slot_full_msg)
    except Exception as e:
        logger.warning("tools/book: capacity/staff check failed for tenant %s (allowing booking): %s", tenant_id, e)

    # Reschedule: cancel the old calendar event now that the new slot has room.
    if existing_appt:
        old_event_id = existing_appt.get("google_event_id", "")
        if old_event_id:
            try:
                if cal_provider == "microsoft":
                    await ms_cal_svc.cancel_event(refresh_token, old_event_id)
                else:
                    await cal_svc.cancel_event(refresh_token, old_event_id)
                logger.info("Cancelled old event %s for reschedule (tenant %s)", old_event_id, tenant_id)
            except (CalendarTokenExpiredError, MsCalendarTokenExpiredError):
                logger.error("tools/book: calendar token expired during reschedule for tenant %s — auto-disconnecting", tenant_id)
                clear_field = "microsoft_refresh_token" if cal_provider == "microsoft" else "google_refresh_token"
                try:
                    await db.update_tenant(tenant_id, {clear_field: None})
                except Exception:
                    pass
                return _result(tc_id, _CALENDAR_ERROR_MSG)
            except Exception as e:
                logger.warning("tools/book: could not delete old calendar event %s: %s", old_event_id, e)

    try:
        _staff_line = f"\nTeam member: {chosen_staff['name']}" if chosen_staff else ""
        description = (
            f"Booked via Open Lines AI receptionist.\n"
            f"Service: {service}\n"
            f"Caller: {caller_name}\n"
            f"Phone: {caller_phone}"
            f"{_staff_line}"
        )
        _title = f"{service} — {caller_name}" if caller_name else service
        if chosen_staff:
            _title += f" (with {chosen_staff['name']})"
        _event_kwargs = dict(
            refresh_token=refresh_token,
            title=_title,
            start_dt=start_dt,
            duration_minutes=duration_minutes,
            timezone=timezone,
            description=description,
        )
        if cal_provider == "microsoft":
            event = await ms_cal_svc.create_event(**_event_kwargs)
        else:
            event = await cal_svc.create_event(**_event_kwargs)
        logger.info(
            "Booked appointment for tenant %s: %s on %s at %s (event %s, provider %s)",
            tenant_id, service, date_str, time_str, event.get("id"), cal_provider,
        )
        analytics.capture(
            analytics.distinct_id_for(tenant, tenant_id),
            "calendar_event_created",
            {"tenant_id": tenant_id, "provider": cal_provider},
        )
    except (CalendarTokenExpiredError, MsCalendarTokenExpiredError):
        logger.error("tools/book: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
        clear_field = "microsoft_refresh_token" if cal_provider == "microsoft" else "google_refresh_token"
        try:
            await db.update_tenant(tenant_id, {clear_field: None})
        except Exception:
            pass
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    except Exception as e:
        logger.error("tools/book: calendar event creation failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    from routers.payments import _deposit_provider
    _dep_provider = _deposit_provider(tenant)

    # Rescheduling an appointment whose deposit was already paid must NOT require
    # another deposit. The deposit stays linked to the same appointment row (we
    # update it in place), so a succeeded payment on the existing appointment
    # means the reschedule is already covered.
    already_paid = False
    if existing_appt:
        try:
            _existing_payment = await db.get_payment_by_appointment_id(existing_appt["id"])
            already_paid = _existing_payment is not None
        except Exception as e:
            logger.warning("tools/book: deposit lookup failed for tenant %s (assuming unpaid): %s", tenant_id, e)

    # Conditional/group deposits: a deposit is due for ALL bookings, or only for
    # group bookings of N+ people. (Provider must be active and not already paid.)
    _applies   = (tenant.get("deposit_applies") or "all").lower()
    _group_min = int(tenant.get("deposit_group_min_size") or 2)
    _deposit_due = bool(_dep_provider) and (
        _applies != "group" or party_size >= _group_min
    )
    deposits_mandatory = _deposit_due and bool(tenant.get("stripe_deposit_mandatory", True))
    # A deposit is only requested when due AND this booking isn't already covered
    # by the original appointment's paid deposit.
    needs_deposit = _deposit_due and not already_paid
    appt_status = "pending_payment" if (deposits_mandatory and not already_paid) else "confirmed"
    logger.info("tools/book: tenant %s provider=%s needs_deposit=%s already_paid=%s status=%s",
                tenant_id, _dep_provider, needs_deposit, already_paid, appt_status)

    appt_id = existing_appt["id"] if existing_appt else None
    try:
        appt_data = {
            "tenant_id":             tenant_id,
            "caller_name":           caller_name,
            "caller_phone":          caller_phone,
            "service":               service,
            "appointment_datetime":  start_dt.isoformat(),
            "duration_minutes":      duration_minutes,
            "party_size":            party_size,
            "status":                appt_status,
            "vapi_call_id":          call_id,
            "google_event_id":       event.get("id", ""),
        }
        if chosen_staff:
            appt_data["staff_id"]   = chosen_staff["id"]
            appt_data["staff_name"] = chosen_staff.get("name", "")
        if existing_appt:
            await db.update_appointment(existing_appt["id"], appt_data)
        else:
            _inserted = await db.insert_appointment(appt_data)
            appt_id = (_inserted or {}).get("id")
        # PRIVACY: no caller name/phone/datetime — service type + duration only
        analytics.capture(
            analytics.distinct_id_for(tenant, tenant_id),
            "appointment_booked",
            {
                "tenant_id": tenant_id,
                "service": service,
                "duration_minutes": duration_minutes,
                "is_reschedule": bool(existing_appt),
            },
        )
        try:
            from services import zapier
            await zapier.emit(tenant_id, "appointment_booked", {
                "caller_name": caller_name,
                "caller_phone": caller_phone,
                "service": service,
                "datetime": start_dt.isoformat(),
                "duration_minutes": duration_minutes,
                "status": appt_status,
                "is_reschedule": bool(existing_appt),
            })
        except Exception as e:
            logger.warning("tools/book: Zapier emit failed for tenant %s (non-fatal): %s", tenant_id, e)
    except Exception as e:
        logger.error("tools/book: failed to save appointment for tenant %s: %s", tenant_id, e)
        # Don't fail the whole response — event was created in Google, just log the DB miss

    # Friendly confirmation string for the AI (includes the assigned staff member
    # in named-staff mode, e.g. "… at 2:00 PM with Sam").
    h = start_dt.hour % 12 or 12
    ampm = "AM" if start_dt.hour < 12 else "PM"
    _staff_suffix = f" with {chosen_staff['name']}" if chosen_staff else ""
    friendly = f"{start_dt.strftime('%A, %B')} {start_dt.day} at {h}:{start_dt.minute:02d} {ampm}{_staff_suffix}"

    # Send SMS confirmation — but only when no mandatory deposit is still owed.
    # When a deposit is mandatory AND not already paid, the confirmation SMS is
    # sent from the payment webhook after the caller pays, so we don't falsely
    # confirm an unpaid booking. A reschedule of an already-paid appointment is
    # confirmed here directly.
    if not (deposits_mandatory and not already_paid):
        try:
            subaccount_sid   = tenant.get("twilio_subaccount_sid", "")
            subaccount_token = tenant.get("twilio_auth_token", "")
            business_phone   = tenant.get("twilio_phone_number", "")
            if subaccount_sid and subaccount_token and business_phone and caller_phone:
                greeting = f"Hi {caller_name}! " if caller_name else ""
                if already_paid:
                    sms_body = (
                        f"{greeting}Your {service} at {business_name} has been rescheduled "
                        f"to {friendly}. Your deposit is already on file — no further payment needed. "
                        f"See you then! — {business_name}"
                    )
                else:
                    sms_body = (
                        f"{greeting}Your {service} at {business_name} is confirmed "
                        f"for {friendly}. See you then! — {business_name}"
                    )
                await telephony.send_sms(
                    subaccount_sid=subaccount_sid,
                    subaccount_token=subaccount_token,
                    from_number=business_phone,
                    to_number=caller_phone,
                    body=sms_body,
                )
                logger.info("Appointment SMS sent to %s for tenant %s", caller_phone, tenant_id)
                analytics.capture(
                    analytics.distinct_id_for(tenant, tenant_id),
                    "sms_confirmation_sent",
                    {"tenant_id": tenant_id},
                )
        except Exception as e:
            logger.error("tools/book: SMS failed for tenant %s: %s", tenant_id, e)

    confirmation = (
        f"Done! Your {service} at {business_name} is confirmed for {friendly}. "
        "You'll receive a text confirmation shortly."
    )
    if already_paid:
        # Reschedule of an already-paid appointment — never ask for another deposit.
        confirmation = (
            f"Done! Your {service} at {business_name} has been rescheduled to {friendly}. "
            f"Tell the caller their deposit is already on file, so no further payment is needed, "
            f"and they'll get a confirmation text shortly. Do NOT call request_deposit."
        )
    # When a deposit is owed (provider active, not already paid), SEND THE LINK
    # NOW from the server — never rely on the AI to call request_deposit. This
    # guarantees the caller gets the payment link the instant they book.
    elif needs_deposit:
        dep = await _create_and_send_deposit(
            tenant, caller_phone=caller_phone, caller_name=caller_name,
            service=service, appointment_id=appt_id,
            amount_cents=_deposit_amount_cents(tenant, party_size),
        )
        amt = f"{dep['amount_display']} {dep['currency_voice']}".strip()
        if dep["already_paid"]:
            confirmation = (
                f"Done! Your {service} at {business_name} is set for {friendly}. "
                f"Tell the caller their deposit is already on file, so no further payment is needed. "
                f"Do NOT call request_deposit."
            )
        elif dep["sms_sent"]:
            confirmation = (
                f"BOOKING_CONFIRMED: {service} for {caller_name} on {friendly}. "
                f"A {amt} deposit link has ALREADY been texted to the caller. "
                f"Tell them: 'I've just sent a secure payment link to your phone — once you pay the "
                f"{amt} deposit your booking is fully confirmed and you'll get a confirmation text. "
                f"The link expires in {dep['expiry_hours']} hours.' "
                f"Do NOT call request_deposit — it has already been sent."
            )
        else:
            confirmation = (
                f"The {service} on {friendly} is held, but I couldn't text the payment link just now. "
                f"Tell the caller: 'I'm having trouble sending the link right now — our team will follow "
                f"up shortly to arrange the {amt} deposit.' Then close warmly. Do NOT call request_deposit."
            )
    return _result(tc_id, confirmation)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/request-deposit
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/request-deposit")
@limiter.limit("10/minute", key_func=tenant_key)
async def request_deposit(request: Request, tenant_id: str, body: dict):
    try:
        tc_id, call_id, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/request-deposit: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    msg = body.get("message", body)
    # Prefer Vapi call metadata phone (most reliable)
    caller_phone = (
        (msg.get("call") or {}).get("customer", {}).get("number", "")
        or args.get("caller_phone", "")
    )
    caller_name = args.get("caller_name", "")
    service     = args.get("service", "Appointment")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/request-deposit: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, "I wasn't able to send the payment link right now. Our team will follow up to arrange the deposit.")

    appointment    = await db.get_latest_appointment_by_phone(tenant_id, caller_phone)
    appointment_id = appointment["id"] if appointment else None
    business_name  = tenant.get("business_name", "the business")
    _party_size    = int((appointment or {}).get("party_size") or 1)

    dep = await _create_and_send_deposit(
        tenant, caller_phone=caller_phone, caller_name=caller_name,
        service=service, appointment_id=appointment_id,
        amount_cents=_deposit_amount_cents(tenant, _party_size),
    )
    if dep["error"] == "no_provider":
        return _result(tc_id, "Payment collection is not set up for this business.")
    if dep["already_paid"]:
        return _result(
            tc_id,
            "The deposit for this appointment has already been paid, so no further payment is "
            "needed. Reassure the caller their booking is confirmed and close the call warmly. "
            "Do not send a payment link.",
        )
    if not dep["sms_sent"]:
        return _result(
            tc_id,
            "I'm sorry, there was an issue sending the payment link by text. Please tell the caller: "
            "'I'm having a little trouble sending the link right now. Our team will follow up with you "
            "shortly to arrange the payment.' Then close the call warmly.",
        )
    _amt = f"{dep['amount_display']} {dep['currency_voice']}".strip()
    return _result(
        tc_id,
        f"SMS_SENT. Now close the call professionally. Say: 'I've just sent a secure payment link to "
        f"your phone. Once you complete the {_amt} deposit, your {service} at {business_name} will be "
        f"fully confirmed — you'll receive a confirmation text straight away. The link expires in "
        f"{dep['expiry_hours']} hours, so please check your messages. Is there anything else I can help "
        f"you with?' Listen for the caller's reply, then close warmly: 'Thank you for choosing "
        f"{business_name}. Have a wonderful day!' Then end the call.",
    )


def _deposit_amount_cents(tenant: dict, party_size: int = 1) -> int:
    """Deposit amount: per-person × party size when configured, else the flat base."""
    base = int(tenant.get("stripe_deposit_cents") or 2500)
    if tenant.get("deposit_per_person"):
        return base * max(1, int(party_size or 1))
    return base


async def _create_and_send_deposit(
    tenant: dict, *, caller_phone: str, caller_name: str, service: str,
    appointment_id: str | None, amount_cents: int | None = None,
) -> dict:
    """Create a deposit payment + branded short link and SMS it to the caller.
    Shared by book_appointment (auto-send the instant a deposit is owed) and the
    request_deposit tool (resend). `amount_cents` overrides the tenant base (e.g.
    per-person group deposits). Never raises; returns a status dict so the caller
    can craft the right voice response."""
    out = {"sms_sent": False, "already_paid": False, "amount_display": "",
           "currency_voice": "", "expiry_hours": 0, "error": None}
    try:
        from routers.payments import _deposit_provider, _currency_for
        _provider = _deposit_provider(tenant)
        if not _provider:
            out["error"] = "no_provider"
            return out

        tenant_id      = tenant["id"]
        deposit_cents  = int(amount_cents if amount_cents is not None else (tenant.get("stripe_deposit_cents") or 2500))
        expiry_minutes = int(tenant.get("stripe_deposit_expiry_min") or 120)
        business_name  = tenant.get("business_name", "the business")
        out["expiry_hours"] = expiry_minutes // 60
        currency = (tenant.get("square_currency") or "usd").lower() if _provider == "square" else _currency_for(tenant)

        from services.short_links import (
            generate_short_code, build_branded_url, format_currency, format_currency_voice,
        )
        out["amount_display"] = f"{deposit_cents // 100}" if deposit_cents % 100 == 0 else f"{deposit_cents / 100:.2f}"
        out["currency_voice"] = format_currency_voice(currency)
        currency_display = format_currency(currency)

        # Never collect a second deposit for an already-paid appointment.
        if appointment_id:
            try:
                if await db.get_payment_by_appointment_id(appointment_id):
                    out["already_paid"] = True
                    return out
            except Exception as e:
                logger.warning("_create_and_send_deposit: paid-check failed for tenant %s: %s", tenant_id, e)

        import uuid
        from datetime import datetime, timezone, timedelta
        payment_id  = str(uuid.uuid4())
        description = f"Deposit — {service} at {business_name}"
        expires_at  = (datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)).isoformat()

        if _provider == "square":
            from services.square_service import create_payment_link, list_locations
            from services.security import decrypt
            access_token = decrypt(tenant["square_access_token"])
            location_id  = tenant.get("square_location_id") or ""
            if not location_id:
                try:
                    locs = await list_locations(access_token)
                    if locs:
                        location_id = locs[0].get("id", "")
                        await db.update_tenant(tenant_id, {"square_location_id": location_id})
                except Exception as _le:
                    logger.warning("Could not fetch Square location for tenant %s: %s", tenant_id, _le)
            if not location_id:
                raise RuntimeError("No Square location found — re-connect your Square account")
            link_id, order_id, checkout_url = await create_payment_link(
                access_token=access_token, location_id=location_id, amount_cents=deposit_cents,
                currency=currency, name=f"Deposit — {service}",
                note=f"Refundable deposit for {service} at {business_name}",
                tenant_id=tenant_id, payment_id=payment_id, expiry_minutes=expiry_minutes,
            )
            await db.insert_payment({
                "id": payment_id, "tenant_id": tenant_id, "appointment_id": appointment_id,
                "checkout_session_id": order_id, "payment_intent_id": link_id,
                "amount_cents": deposit_cents, "currency": currency, "status": "pending",
                "provider": "square", "caller_phone": caller_phone, "caller_name": caller_name,
                "service": service, "description": description, "expires_at": expires_at,
            })
            session_id = link_id
        else:
            from services.stripe_service import create_checkout_session
            session_id, checkout_url = await create_checkout_session(
                stripe_account_id=tenant["stripe_account_id"], amount_cents=deposit_cents,
                description=description, tenant_id=tenant_id, payment_id=payment_id,
                caller_name=caller_name or "Customer", expiry_minutes=expiry_minutes, currency=currency,
            )
            await db.insert_payment({
                "id": payment_id, "tenant_id": tenant_id, "appointment_id": appointment_id,
                "stripe_account_id": tenant["stripe_account_id"], "checkout_session_id": session_id,
                "amount_cents": deposit_cents, "currency": currency, "status": "pending",
                "provider": "stripe", "caller_phone": caller_phone, "caller_name": caller_name,
                "service": service, "description": description, "expires_at": expires_at,
            })

        logger.info("Created deposit payment %s via %s for tenant %s caller %s",
                    payment_id, _provider, tenant_id, caller_phone)

        # Branded short link
        branded_url = checkout_url
        try:
            short_code = generate_short_code()
            for _ in range(4):
                if not await db.get_payment_short_link_by_code(short_code):
                    break
                short_code = generate_short_code()
            await db.create_payment_short_link({
                "tenant_id": tenant_id, "appointment_id": appointment_id, "short_code": short_code,
                "stripe_checkout_url": checkout_url, "stripe_session_id": session_id,
                "amount_cents": deposit_cents, "currency": currency,
                "purpose": "appointment_deposit", "expires_at": expires_at,
            })
            branded_url = build_branded_url(short_code)
        except Exception as e:
            logger.error("_create_and_send_deposit: short link failed for tenant %s: %s", tenant_id, e)

        # SMS the link to the caller
        provider_label = "Square" if _provider == "square" else "Stripe"
        sid    = tenant.get("twilio_subaccount_sid", "")
        tok    = tenant.get("twilio_auth_token", "")
        from_n = tenant.get("twilio_phone_number", "")
        if not caller_phone:
            logger.warning("Deposit SMS skipped for tenant %s — caller_phone empty", tenant_id)
        elif not (sid and tok and from_n):
            logger.warning("Deposit SMS skipped for tenant %s — Twilio creds missing", tenant_id)
        else:
            caller_display  = caller_name or "there"
            service_display = service or "appointment"
            sms_body = (
                f"Hi {caller_display}!\n\n"
                f"To confirm your {service_display} at {business_name}, please pay the refundable "
                f"{currency_display} {out['amount_display']} deposit:\n\n{branded_url}\n\n"
                f"Secure payment powered by {provider_label}.\n"
                f"Expires in {out['expiry_hours']} hrs."
            )
            out["sms_sent"] = await telephony.send_sms(
                subaccount_sid=sid, subaccount_token=tok, from_number=from_n,
                to_number=caller_phone, body=sms_body,
            )
            if out["sms_sent"]:
                logger.info("Deposit SMS sent to %s for tenant %s", caller_phone, tenant_id)
            else:
                logger.warning("Deposit SMS send returned False for tenant %s", tenant_id)
        return out
    except Exception as e:
        logger.error("_create_and_send_deposit failed for tenant %s: %s", tenant.get("id"), e)
        out["error"] = "exception"
        return out



# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/cancel")
@limiter.limit("10/minute", key_func=tenant_key)
async def cancel_appointment(request: Request, tenant_id: str, body: dict):
    try:
        tc_id, _, _ = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/cancel: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    msg = body.get("message", body)
    caller_phone = (msg.get("call") or {}).get("customer", {}).get("number", "")

    if not caller_phone:
        return _result(tc_id, "I wasn't able to find your phone number to look up the appointment. Could you confirm the number on file?")

    try:
        appt = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/cancel: appointment lookup failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble looking up your appointment. Please call back and we'll get that sorted.")

    if not appt:
        return _result(tc_id, "I don't see any upcoming appointment for your number. Is it possible it's under a different phone number?")

    # Cancel Google Calendar event
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/cancel: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble processing the cancellation. Please call back and we'll get that sorted.")

    refresh_token, cal_provider = _calendar_provider(tenant or {})
    event_id = appt.get("google_event_id", "")

    if refresh_token and event_id:
        try:
            if cal_provider == "microsoft":
                await ms_cal_svc.cancel_event(refresh_token, event_id)
            else:
                await cal_svc.cancel_event(refresh_token, event_id)
        except (CalendarTokenExpiredError, MsCalendarTokenExpiredError):
            logger.error("tools/cancel: calendar token expired for tenant %s — auto-disconnecting", tenant_id)
            clear_field = "microsoft_refresh_token" if cal_provider == "microsoft" else "google_refresh_token"
            try:
                await db.update_tenant(tenant_id, {clear_field: None})
            except Exception:
                pass
        except Exception as e:
            logger.warning("tools/cancel: could not delete calendar event %s: %s", event_id, e)

    # Mark appointment cancelled in DB
    try:
        await db.update_appointment(appt["id"], {**appt, "status": "cancelled"})
    except Exception as e:
        logger.error("tools/cancel: failed to update appointment status for tenant %s: %s", tenant_id, e)

    service  = appt.get("service", "appointment")
    appt_dt_raw = appt.get("appointment_datetime", "")
    friendly = appt_dt_raw
    appt_dt_utc = None
    try:
        appt_dt_utc = datetime.fromisoformat(appt_dt_raw)
        if appt_dt_utc.tzinfo is None:
            appt_dt_utc = appt_dt_utc.replace(tzinfo=ZoneInfo("UTC"))
        tz_str  = (tenant or {}).get("calendar_timezone") or "America/Toronto"
        appt_dt_local = appt_dt_utc.astimezone(ZoneInfo(tz_str))
        h    = appt_dt_local.hour % 12 or 12
        ampm = "AM" if appt_dt_local.hour < 12 else "PM"
        friendly = f"{appt_dt_local.strftime('%A, %B')} {appt_dt_local.day} at {h}:{appt_dt_local.minute:02d} {ampm}"
    except Exception:
        pass

    logger.info("Cancelled appointment %s for tenant %s caller %s", appt["id"], tenant_id, caller_phone)
    analytics.capture(
        analytics.distinct_id_for(tenant, tenant_id),
        "appointment_cancelled",
        {"tenant_id": tenant_id},
    )

    # ---- Deposit refund per the business's cancellation policy ----
    from services import refunds as refund_svc
    from services.short_links import format_currency

    tenant = tenant or {}
    caller_name = appt.get("caller_name", "") or ""
    refund_clause = ""  # appended to the AI's spoken confirmation
    cancel_refunded = False
    try:
        payment = await db.get_payment_by_appointment_id(appt["id"])
    except Exception as e:
        logger.error("tools/cancel: payment lookup failed for tenant %s: %s", tenant_id, e)
        payment = None

    if payment:
        refund_hours = int(tenant.get("cancellation_refund_hours") if tenant.get("cancellation_refund_hours") is not None else 24)
        eligible = refund_svc.refund_eligible(appt_dt_utc, refund_hours)
        amount_cents = int(payment.get("amount_cents") or 0)
        cur          = format_currency(payment.get("currency", "usd"))
        amt          = f"{amount_cents // 100}" if amount_cents % 100 == 0 else f"{amount_cents / 100:.2f}"

        if eligible:
            ok = await refund_svc.issue_provider_refund(payment, tenant)
            if ok:
                try:
                    await db.update_payment(payment["id"], {
                        "status":      "refunded",
                        "refunded_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as e:
                    logger.error("tools/cancel: failed to mark payment refunded for tenant %s: %s", tenant_id, e)
                await refund_svc.sms_caller_refund(tenant, payment, appt)
                await refund_svc.notify_business(tenant, payment, refunded=True)
                cancel_refunded = True
                refund_clause = f" Your {cur} {amt} deposit will be refunded, and you'll get a confirmation text shortly."
            else:
                # Refund API failed — leave payment as-is, have the team follow up.
                await refund_svc.notify_business(tenant, payment, refunded=False, service=service)
                refund_clause = " There was an issue processing your deposit refund automatically, but our team will follow up to arrange it."
        else:
            # Cancelled inside the non-refundable window — deposit forfeited.
            await refund_svc.sms_caller_cancelled(
                tenant, caller_phone, caller_name, service,
                deposit_forfeited=True, amount_cents=amount_cents,
                currency=payment.get("currency", "usd"), refund_hours=refund_hours,
            )
            await refund_svc.notify_business(tenant, payment, refunded=False, service=service)
            refund_clause = (
                f" As this is within {refund_hours} hours of the appointment, the "
                f"{cur} {amt} deposit is non-refundable per the cancellation policy."
            )
    else:
        # No deposit on file — just confirm the cancellation.
        await refund_svc.sms_caller_cancelled(tenant, caller_phone, caller_name, service)
        await refund_svc.notify_business(
            tenant, None, refunded=False, service=service,
            caller_name=caller_name, caller_phone=caller_phone,
        )

    try:
        from services import zapier
        _pay = payment or {}
        _amt_cents = int(_pay.get("amount_cents") or 0)
        await zapier.emit(tenant_id, "appointment_cancelled", {
            "caller_name": caller_name,
            "caller_phone": caller_phone,
            "service": service,
            "datetime": appt.get("appointment_datetime", ""),
            "refunded": cancel_refunded,
            "refund_amount": round(_amt_cents / 100, 2) if cancel_refunded else 0,
            "currency": format_currency(_pay.get("currency", "usd")) if _pay else "",
        })
    except Exception as e:
        logger.warning("tools/cancel: Zapier emit failed for tenant %s (non-fatal): %s", tenant_id, e)

    return _result(
        tc_id,
        f"Done — your {service} on {friendly} has been cancelled.{refund_clause} "
        f"Is there anything else I can help you with?",
    )
