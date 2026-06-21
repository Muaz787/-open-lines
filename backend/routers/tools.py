"""
Vapi mid-call tool endpoints.

Vapi calls these URLs while a call is in progress.  Each endpoint receives a
POST with the tool-call arguments and must return a { "results": [...] } JSON
response that the AI uses to continue the conversation.
"""

import json
import logging
from datetime import date as date_type, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from services import analytics
from services import calendar as cal_svc
from services.calendar import CalendarTokenExpiredError
from services import ms_calendar as ms_cal_svc
from services.ms_calendar import MsCalendarTokenExpiredError
from services import telephony
from services.ratelimit import limiter, tenant_key
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])

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

    # Cancel existing appointment for this caller (reschedule flow).
    # Look back 24h so same-day reschedules are caught even if the slot has passed.
    existing_appt = None
    if caller_phone:
        try:
            existing_appt = await db.get_active_appointment_by_phone(tenant_id, caller_phone)
        except Exception as e:
            logger.warning("tools/book: appointment lookup failed for tenant %s: %s", tenant_id, e)

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
        description = (
            f"Booked via Open Lines AI receptionist.\n"
            f"Service: {service}\n"
            f"Caller: {caller_name}\n"
            f"Phone: {caller_phone}"
        )
        _event_kwargs = dict(
            refresh_token=refresh_token,
            title=f"{service} — {caller_name}" if caller_name else service,
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

    deposits_mandatory = (
        bool(_dep_provider)
        and bool(tenant.get("stripe_deposit_mandatory", True))
    )
    # A deposit is only requested when the provider is active AND this booking
    # isn't already covered by the original appointment's paid deposit.
    needs_deposit = bool(_dep_provider) and not already_paid
    appt_status = "pending_payment" if (deposits_mandatory and not already_paid) else "confirmed"

    try:
        appt_data = {
            "tenant_id":             tenant_id,
            "caller_name":           caller_name,
            "caller_phone":          caller_phone,
            "service":               service,
            "appointment_datetime":  start_dt.isoformat(),
            "duration_minutes":      duration_minutes,
            "status":                appt_status,
            "vapi_call_id":          call_id,
            "google_event_id":       event.get("id", ""),
        }
        if existing_appt:
            await db.update_appointment(existing_appt["id"], appt_data)
        else:
            await db.insert_appointment(appt_data)
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

    # Friendly confirmation string for the AI
    h = start_dt.hour % 12 or 12
    ampm = "AM" if start_dt.hour < 12 else "PM"
    friendly = f"{start_dt.strftime('%A, %B')} {start_dt.day} at {h}:{start_dt.minute:02d} {ampm}"

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
    # When a deposit is still owed (provider active and not already paid),
    # let the AI know to call request_deposit next.
    elif needs_deposit:
        from routers.payments import _currency_for
        from services.short_links import format_currency_voice
        _dep_cents = int(tenant.get("stripe_deposit_cents") or 2500)
        if _dep_provider == "square":
            _currency = (tenant.get("square_currency") or "usd").lower()
        else:
            _currency = _currency_for(tenant)
        _voice_word   = format_currency_voice(_currency)
        _dep_display  = f"{_dep_cents // 100} {_voice_word}" if _dep_cents % 100 == 0 else f"{_dep_cents / 100:.2f} {_voice_word}"
        _expiry_hours = int(tenant.get("stripe_deposit_expiry_min") or 120) // 60
        mandatory     = bool(tenant.get("stripe_deposit_mandatory", True))
        requirement   = "required to confirm this booking" if mandatory else "optional"
        confirmation  = (
            f"BOOKING_CONFIRMED: {service} for {caller_name} on {friendly}. "
            f"DEPOSIT: A {_dep_display} deposit is {requirement}. "
            f"Tell the caller their slot is held and you are sending them a payment link now. "
            f"IMMEDIATELY call request_deposit — do NOT end the call first."
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

    from routers.payments import _deposit_provider, _currency_for
    _provider = _deposit_provider(tenant)
    if not tenant or not _provider:
        return _result(tc_id, "Payment collection is not set up for this business.")

    deposit_cents  = int(tenant.get("stripe_deposit_cents") or 2500)
    expiry_minutes = int(tenant.get("stripe_deposit_expiry_min") or 120)
    business_name  = tenant.get("business_name", "the business")
    expiry_hours   = expiry_minutes // 60

    if _provider == "square":
        currency = (tenant.get("square_currency") or "usd").lower()
    else:
        currency = _currency_for(tenant)

    try:
        import uuid
        payment_id  = str(uuid.uuid4())
        description = f"Deposit — {service} at {business_name}"

        appointment = await db.get_latest_appointment_by_phone(tenant_id, caller_phone)
        appointment_id = appointment["id"] if appointment else None

        # Defense-in-depth: never collect a second deposit for an appointment
        # whose deposit was already paid (e.g. a reschedule). The deposit stays
        # linked to the same appointment row.
        if appointment_id:
            try:
                if await db.get_payment_by_appointment_id(appointment_id):
                    logger.info("request_deposit: appointment %s already has a paid deposit — skipping", appointment_id)
                    return _result(
                        tc_id,
                        "The deposit for this appointment has already been paid, so no further "
                        "payment is needed. Reassure the caller their booking is confirmed and "
                        "close the call warmly. Do not send a payment link.",
                    )
            except Exception as e:
                logger.warning("request_deposit: paid-deposit check failed for tenant %s: %s", tenant_id, e)

        from datetime import datetime, timezone, timedelta
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)).isoformat()

        if _provider == "square":
            from services.square_service import create_payment_link, list_locations
            from services.security import decrypt
            access_token = decrypt(tenant["square_access_token"])
            location_id  = tenant.get("square_location_id") or ""
            if not location_id:
                # location_id may not have been saved during OAuth — fetch and cache it now
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
                access_token=access_token,
                location_id=location_id,
                amount_cents=deposit_cents,
                currency=currency,
                name=f"Deposit — {service}",
                note=f"Refundable deposit for {service} at {business_name}",
                tenant_id=tenant_id,
                payment_id=payment_id,
                expiry_minutes=expiry_minutes,
            )
            await db.insert_payment({
                "id": payment_id,
                "tenant_id": tenant_id,
                "appointment_id": appointment_id,
                "checkout_session_id": order_id,
                "payment_intent_id":   link_id,
                "amount_cents": deposit_cents,
                "currency": currency,
                "status": "pending",
                "provider": "square",
                "caller_phone": caller_phone,
                "caller_name": caller_name,
                "service": service,
                "description": description,
                "expires_at": expires_at,
            })
            session_id = link_id
        else:
            from services.stripe_service import create_checkout_session
            session_id, checkout_url = await create_checkout_session(
                stripe_account_id=tenant["stripe_account_id"],
                amount_cents=deposit_cents,
                description=description,
                tenant_id=tenant_id,
                payment_id=payment_id,
                caller_name=caller_name or "Customer",
                expiry_minutes=expiry_minutes,
                currency=currency,
            )
            await db.insert_payment({
                "id": payment_id,
                "tenant_id": tenant_id,
                "appointment_id": appointment_id,
                "stripe_account_id": tenant["stripe_account_id"],
                "checkout_session_id": session_id,
                "amount_cents": deposit_cents,
                "currency": currency,
                "status": "pending",
                "provider": "stripe",
                "caller_phone": caller_phone,
                "caller_name": caller_name,
                "service": service,
                "description": description,
                "expires_at": expires_at,
            })

        logger.info("Created deposit payment %s via %s for tenant %s caller %s",
                    payment_id, _provider, tenant_id, caller_phone)

    except Exception as e:
        logger.error("tools/request-deposit: payment link creation failed for tenant %s: %s", tenant_id, e)
        return _result(
            tc_id,
            "I'm sorry, there was an issue generating the payment link. "
            "Please apologise to the caller and let them know the team will follow up shortly to arrange payment.",
        )

    # Create branded short payment link
    from services.short_links import generate_short_code, build_branded_url, format_currency, format_currency_voice
    currency_display = format_currency(currency)
    currency_voice   = format_currency_voice(currency)
    branded_url = checkout_url  # fallback if short link creation fails
    try:
        short_code = generate_short_code()
        for _ in range(4):
            if not await db.get_payment_short_link_by_code(short_code):
                break
            short_code = generate_short_code()

        await db.create_payment_short_link({
            "tenant_id":           tenant_id,
            "appointment_id":      appointment_id,
            "short_code":          short_code,
            "stripe_checkout_url": checkout_url,
            "stripe_session_id":   session_id,
            "amount_cents":        deposit_cents,
            "currency":            currency,
            "purpose":             "appointment_deposit",
            "expires_at":          expires_at,
        })
        branded_url = build_branded_url(short_code)
        logger.info("Created short payment link %s for tenant %s caller %s", short_code, tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/request-deposit: short link creation failed for tenant %s: %s", tenant_id, e)

    # Send branded SMS
    provider_label = "Square" if _provider == "square" else "Stripe"
    sms_sent = False
    try:
        sid    = tenant.get("twilio_subaccount_sid", "")
        tok    = tenant.get("twilio_auth_token", "")
        from_n = tenant.get("twilio_phone_number", "")
        if not caller_phone:
            logger.warning(
                "Deposit SMS skipped for tenant %s — caller_phone is empty "
                "(web/test call with no real number injected by Vapi)",
                tenant_id,
            )
        elif not (sid and tok and from_n):
            missing = [k for k, v in {"sid": sid, "token": tok, "from_number": from_n}.items() if not v]
            logger.warning("Deposit SMS skipped for tenant %s — Twilio creds missing: %s", tenant_id, missing)
        if sid and tok and from_n and caller_phone:
            caller_display  = caller_name or "there"
            service_display = service or "appointment"
            amount_display  = f"{deposit_cents // 100}" if deposit_cents % 100 == 0 else f"{deposit_cents / 100:.2f}"
            sms_body = (
                f"Hi {caller_display}!\n\n"
                f"To confirm your {service_display} at {business_name}, please pay the refundable "
                f"{currency_display} {amount_display} deposit:\n\n"
                f"{branded_url}\n\n"
                f"Secure payment powered by {provider_label}.\n"
                f"Expires in {expiry_hours} hrs."
            )
            sms_sent = await telephony.send_sms(
                subaccount_sid=sid,
                subaccount_token=tok,
                from_number=from_n,
                to_number=caller_phone,
                body=sms_body,
            )
            if sms_sent:
                logger.info("Deposit SMS sent to %s for tenant %s", caller_phone, tenant_id)
            else:
                logger.warning("Deposit SMS send returned False for tenant %s", tenant_id)
    except Exception as e:
        logger.error("tools/request-deposit: SMS failed for tenant %s: %s", tenant_id, e)

    if not sms_sent:
        return _result(
            tc_id,
            "I'm sorry, there was an issue sending the payment link by text. "
            "Please tell the caller: 'I'm having a little trouble sending the link right now. "
            "Our team will follow up with you shortly to arrange the payment.' "
            "Then close the call warmly.",
        )

    service_display = service or "appointment"
    amount_display  = f"{deposit_cents // 100}" if deposit_cents % 100 == 0 else f"{deposit_cents / 100:.2f}"
    return _result(
        tc_id,
        f"SMS_SENT. Now close the call professionally. Say: "
        f"'I've just sent a secure payment link to your phone. "
        f"Once you complete the {amount_display} {currency_voice} deposit, "
        f"your {service_display} at {business_name} will be fully confirmed — "
        f"you'll receive a confirmation text straight away. "
        f"The link expires in {expiry_hours} hours, so please check your messages when you get a chance. "
        f"Is there anything else I can help you with?' "
        f"Listen for the caller's reply, then close warmly: "
        f"'Thank you for choosing {business_name}. Have a wonderful day!' "
        f"Then end the call.",
    )


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
