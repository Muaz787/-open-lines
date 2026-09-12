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
from services import appointment_cancellation
from services import appointment_refs
from services import mutation_ownership
from services import reschedule_intent
from db import mutation_claims as db_mc
from services import caller_identity
from services import customer_identity
from services import calendar as cal_svc
from services.calendar import CalendarTokenExpiredError
from services import ms_calendar as ms_cal_svc
from services.ms_calendar import MsCalendarTokenExpiredError
from services import square_booking
from services import call_location, location_resolver, location_scope, slot_offers
from services import telephony
from services.ratelimit import limiter, tenant_key
from services.security import verify_vapi_server_secret
from services import entitlements, routing_engine
from db import supabase as db
from db import locations as db_loc
from services import location_sync
from services.square_service import list_locations as _sq_list_locations
from db import routing as rdb

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

# Obvious model inventions. Vapi delivers a real E.164 for an inbound PSTN call,
# so these only ever appear when the LLM filled the field in itself — as it did
# during the W4 rehearsal, offering "+00000000000" for a Square customer record.
_IMPLAUSIBLE_CALLER_PHONES = {"", "+00000000000", "+10000000000", "+0000000000",
                              "0000000000", "+1234567890", "1234567890"}


def _plausible_caller_phone(value: str) -> bool:
    v = (value or "").strip()
    if v in _IMPLAUSIBLE_CALLER_PHONES:
        return False
    digits = "".join(c for c in v if c.isdigit())
    if len(digits) < 8 or len(set(digits)) <= 1:      # all-same-digit is never real
        return False
    return not digits.startswith("555555")


def trusted_caller_phone(body: dict, args: dict) -> str:
    """The caller's number, preferring what the telephony provider told us.

    The model is NEVER authoritative for caller identity. Vapi's call metadata is
    signed-adjacent — it comes from the authenticated webhook, not from generated
    text — so when it is present it wins outright. A model-supplied value is used
    only when metadata is genuinely absent, and even then it must look like a real
    number: the rehearsal showed the model inventing "+00000000000", which would
    have become a Square customer's phone number.
    """
    msg = body.get("message", body)
    cust = (msg.get("call") or {}).get("customer") or {}
    for candidate in (cust.get("number"), cust.get("phoneNumber"),
                      (msg.get("customer") or {}).get("number"),
                      (msg.get("customer") or {}).get("phoneNumber")):
        if (candidate or "").strip():
            return candidate.strip()
    supplied = (args.get("caller_phone") or "").strip()
    if supplied and _plausible_caller_phone(supplied):
        return supplied
    if supplied:
        logger.warning("tools: discarded implausible model-supplied caller_phone")
    return ""


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


async def _list_cancellable(tc_id, call_id, tenant, tenant_id, caller_phone,
                            *, action: str = "cancel"):
    """Stage 1 of cancellation OR of a move: enumerate, label, and mutate NOTHING.

    Returns human-readable choices — location, service, date, time — with an
    opaque ref beside each. One candidate is listed too, not acted on: a single
    match is still an assumption about which appointment the caller meant.

    W6A2-D3 shares this with the reschedule tool rather than duplicating it. The
    enumeration and the refs it mints are identical; only the closing instruction
    differs, because telling the model to "call cancel_appointment again" when the
    caller asked to MOVE something is how a move becomes a cancellation.
    """
    verb, tool_name = (("cancelled", "cancel_appointment") if action == "cancel"
                       else ("moved", "reschedule_appointment"))
    try:
        candidates = await db.get_active_appointments_by_phone(tenant_id, caller_phone)
    except Exception as e:
        logger.error("tools/cancel: candidate lookup failed for tenant %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble looking up your appointment. Please call back and we'll get that sorted.")

    if not candidates:
        return _result(tc_id,
            "I don't see any upcoming appointment for this caller's number. Ask "
            "whether it might be under a different number.")

    # Location names for speech. Never an id — anything the model can see it can
    # say out loud or hand back to a tool.
    names: dict[str, str] = {}
    try:
        _multi, adopted = await call_location.is_multi_location(tenant_id)
        names = {str(l.get("id")): (l.get("name") or "") for l in adopted}
    except Exception as e:
        logger.warning("tools/cancel: location names unavailable for %s: %s", tenant_id, e)

    rows = await appointment_refs.create_refs(
        vapi_call_id=call_id, tenant_id=tenant_id,
        caller_phone=caller_phone, appointments=candidates)
    if not rows:
        return _result(tc_id, "I had trouble looking up your appointment. Please call back and we'll get that sorted.")

    tz = tenant.get("calendar_timezone") or "UTC"
    described = [
        (r["appointment_ref"],
         appointment_refs.describe(r, names.get(str(r.get("tenant_location_id")), ""), tz))
        for r in rows
    ]

    tail = ("" if action == "cancel" else
            " Then check_availability for that same service at that same location, "
            "and only call reschedule_appointment once the caller has chosen a new time.")

    if len(described) == 1:
        return _result(tc_id,
            f"This caller has one upcoming appointment: {described[0][1]} "
            f"[{described[0][0]}]. Read the appointment back WITHOUT the reference "
            f"and ask them to confirm they want it {verb}. If they confirm, call "
            f"{tool_name} again with that reference.{tail}")

    return _result(tc_id,
        f"This caller has {len(described)} upcoming appointments: "
        f"{appointment_refs.spoken_list(described)}. Read them out WITHOUT the "
        f"references — those are internal — and ask which one they want {verb}. "
        f"Then call {tool_name} again with the matching reference. If you are not "
        f"certain which they meant, ask rather than guess.{tail}")


async def _cancel_square_booking(tenant, appt, event_id, tenant_id) -> str:
    """Thin delegate. C4 moved the provider half into services/appointment_cancellation
    so the refund path and the deferred-intent worker share one implementation of
    the location-verification and outcome rules rather than three copies."""
    return await appointment_cancellation.cancel_square_booking(
        tenant, appt, event_id, tenant_id)


def _customer_problem_message(status: str) -> str:
    """What to say when we cannot settle who the caller is, without booking anyway.

    Every branch here ends in no booking. Creating a second customer record to get
    past an ambiguity is the failure W6B exists to remove, so ambiguity has to cost
    us a booking rather than cost the merchant a clean customer list.
    """
    if status == customer_identity.AMBIGUOUS:
        return ("There are several customer records with this phone number, so I can't "
                "safely tell which one is the caller. Take their details and let them "
                "know the team will confirm the booking shortly.")
    if status == customer_identity.UNAVAILABLE:
        return ("I'm still confirming this caller's details — give me a moment and try "
                "booking that same time again.")
    return _CALENDAR_ERROR_MSG


async def _trusted_caller_name(tenant_id: str, supplied: str, phone: str) -> str:
    """Resolve a caller name we are willing to persist, or ''.

    The lead lookup is best-effort: failing to read history must never block a
    booking, and its absence simply means we hold no name — which is the correct
    outcome, not a degraded one.
    """
    persisted = ""
    if phone and caller_identity.is_placeholder_name(supplied):
        try:
            lead = await db.get_lead_by_phone(tenant_id, phone)
            persisted = (lead or {}).get("name") or ""
        except Exception as e:
            logger.warning("caller name: lead lookup failed for %s: %s", tenant_id, e)
    return caller_identity.resolve_caller_name(supplied, persisted)


async def _multi_location_availability(
    tc_id: str, tenant: dict, tenant_id: str, args: dict, date_str: str, prefix: str,
    adopted: list[dict],
):
    """W4 — availability for a tenant with >= 2 adopted locations.

    Fails closed at every step: an unresolved, ambiguous, disabled, unbound or
    wrong-location request makes ZERO Square calls and returns something the
    assistant can say out loud. There is no fallback branch here on purpose —
    tenants.square_location_id, is_default and locations[0] are all unreachable
    from this function.
    """
    call_id = args.get("_call_id", "")
    if not call_id:
        # Without a proven call id there is no authoritative state, and an
        # anonymous shared row would be worse than refusing.
        logger.error("tools/availability[multi]: no vapi call id for tenant %s", tenant_id)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    eligible = call_location.eligible_for_availability(adopted)
    if not eligible:
        logger.warning("tools/availability[multi]: tenant %s has no bookable location", tenant_id)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    state = await call_location.get_or_create(call_id, tenant_id)
    if not state:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    location, resolution, state = await call_location.resolve_active_location(
        state, args.get("location", ""), eligible, tenant.get("business_name") or "")

    if not location:
        # NO LOCATION -> NO SQUARE REQUEST. Ask instead.
        lead = ("I'm not sure which location you meant. Which would you like"
                if resolution and resolution.status == location_resolver.AMBIGUOUS
                else "Which location would you like")
        return _result(tc_id, prefix + location_resolver.clarification_text(
            (resolution.candidates if resolution else eligible), lead=lead))

    loc_name = location.get("name") or location.get("slug") or "that location"
    binding = location.get("_binding") or {}
    provider_location_id = (binding.get("provider_location_id") or "").strip()
    if not provider_location_id:
        logger.error("tools/availability[multi]: %s has no usable binding", loc_name)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Timezone: the location's own, then the provider's. No tenant fallback —
    # answering an Irish caller in Toronto time would be silently wrong.
    timezone = (location.get("timezone") or binding.get("provider_timezone") or "").strip()
    if not timezone:
        logger.error("tools/availability[multi]: no timezone for %s (tenant %s)",
                     loc_name, tenant_id)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # W3 scope: only what is genuinely offered at this location.
    all_services = await db.get_square_services(tenant_id, bookable_only=True)
    services = location_scope.services_at_location(all_services, provider_location_id)
    if not services:
        return _result(tc_id, prefix +
            f"We don't have any bookable services at {loc_name} at the moment.")

    requested_service = (args.get("service") or "").strip()
    chosen = _match_square_service(requested_service, services) if requested_service else None
    if requested_service and (chosen is None or not _service_matches(requested_service, chosen)):
        offered = ", ".join(s["name"] for s in services[:6] if s.get("name"))
        return _result(tc_id, prefix +
            f"{requested_service} isn't offered at the {loc_name} location. "
            f"There we do: {offered}. Would one of those work, or would you like a "
            f"different location?")

    if chosen is not None:
        # An explicit choice replaces whatever the call was about before.
        state = await call_location.set_active_service(state, chosen)
    else:
        # W5: fall back to what this call is already about, so "what about Dublin?"
        # still means dress fitting. Only accepted if it is offered HERE.
        chosen = call_location.active_service_from(state, services)
        if chosen is None:
            remembered = call_location.remembered_service_name(state)
            offered = ", ".join(s["name"] for s in services[:6] if s.get("name"))
            if remembered:
                # Carried a service in, but this location does not do it. Say so —
                # never substitute — and keep the context so the caller can ask
                # about somewhere else naturally.
                return _result(tc_id, prefix +
                    f"{remembered} isn't offered at the {loc_name} location. "
                    f"There we do: {offered}. Would one of those work, or would you "
                    f"like to try another location?")
            if len(services) == 1:
                chosen = services[0]
                state = await call_location.set_active_service(state, chosen)
            else:
                return _result(tc_id, prefix +
                    f"Which service would you like at {loc_name}? We offer: {offered}.")

    all_staff = await db.get_square_staff(tenant_id)
    staff_rows = location_scope.staff_at_location(all_staff, provider_location_id)
    team_ids = [t for t in (chosen.get("team_member_ids") or [])
                if any(s["square_team_member_id"] == t for s in staff_rows)]

    requested_staff = (args.get("staff") or "").strip()
    if requested_staff:
        roster = [{"name": s.get("display_name"), "id": s.get("square_team_member_id")}
                  for s in staff_rows]
        matched = _match_staff(requested_staff, roster)
        if not matched or not _staff_matches(requested_staff, matched.get("name") or ""):
            names = ", ".join(r["name"] for r in roster if r["name"])
            return _result(tc_id, prefix +
                f"{requested_staff} isn't available at {loc_name}. "
                f"There we have: {names}. Would one of them work?")
        team_ids = [matched["id"]]

    if not team_ids:
        team_ids = [s["square_team_member_id"] for s in staff_rows]
    if not team_ids:
        return _result(tc_id, prefix +
            f"We don't have anyone available for that at {loc_name} right now.")

    try:
        slots = await square_booking.available_slots(
            tenant, date_str=date_str, timezone=timezone,
            service_variation_id=chosen["square_variation_id"], team_member_ids=team_ids,
            provider_location_id=provider_location_id,
        )
    except Exception as e:
        logger.error("tools/availability[multi]: Square failed for %s at %s: %s",
                     tenant_id, loc_name, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    try:
        _fmt_date = date_type.fromisoformat(date_str).strftime("%B %d, %Y")
    except ValueError:
        _fmt_date = date_str

    # Always name the location back. It is the caller's audible check that we
    # heard the right city, and it makes a mid-call switch obvious.
    service_label = chosen.get("name") or "that"
    if not slots:
        return _result(tc_id, prefix +
            f"{loc_name} has no {service_label} availability on {_fmt_date}. Would "
            f"another day work, or would you like me to try a different location?")

    # W5: write down exactly what we are offering, so booking can replay it rather
    # than re-derive it. Refs are for the model; the caller only ever hears times.
    offers = await slot_offers.create_offers(
        vapi_call_id=call_id, tenant_id=tenant_id,
        tenant_location_id=str(location.get("id") or ""),
        provider_location_id=provider_location_id,
        service_variation_id=chosen["square_variation_id"],
        service_name=chosen.get("name") or "",
        slots=slots,
    )
    if not offers:
        # Persisting failed. The times are real, so read them out, but do not let
        # booking proceed from an unrecorded offer.
        times = ", ".join(s["display"] for s in slots[:6])
        return _result(tc_id, prefix +
            f"{loc_name} has {service_label} availability on {_fmt_date}: {times}. "
            "Ask the caller which time suits, then check availability again before booking.")

    listed = slot_offers.spoken_offer_list(offers)
    return _result(tc_id, prefix +
        f"{loc_name} has {service_label} availability on {_fmt_date}: {listed}. "
        "Read only the TIMES aloud — never the slot_ references, they are internal. "
        "When the caller picks a time, call book_appointment with the slot_ref shown "
        "beside that exact time. If the caller's choice is unclear, ask which time "
        "they meant; never guess a slot.")


def _staff_matches(requested: str, matched_name: str) -> bool:
    """Did _match_staff find the requested person, or a same-surname neighbour?

    _match_staff fuzzy-matches whole names at cutoff 0.6, which is right for a
    mis-transcription ('Shayd' -> 'Shahid') but wrong across a shared surname:
    'Niamh Test' vs 'Aoife Test' scores exactly 0.600 and matches. Their FIRST
    names score 0.200, while shayd/shahid score 0.727 — so the first name is what
    separates a mis-hearing from a different person.

    Applied in the multi-location branch only. Legacy single-location matching is
    unchanged: there, offering the wrong colleague is a correction in the next
    sentence, not a caller sent to the wrong city.
    """
    import difflib as _dl
    req = (requested or "").strip().lower()
    name = (matched_name or "").strip().lower()
    if not req or not name:
        return False
    if req in name or name in req:
        return True
    return _dl.SequenceMatcher(None, req.split()[0], name.split()[0]).ratio() >= 0.6


def _service_matches(requested: str, service: dict) -> bool:
    """Did the fuzzy matcher genuinely find the requested service, or fall back?

    _match_square_service returns services[0] when nothing matches, which is safe
    enough for a single-location tenant but must never stand in for "we don't do
    that here" at a specific location.
    """
    import difflib as _dl
    name = (service.get("name") or "").lower()
    req = requested.lower().strip()
    if not req or not name:
        return False
    if req in name or name in req:
        return True
    return _dl.SequenceMatcher(None, req, name).ratio() >= 0.6


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


async def _multi_location_book(
    tc_id: str, call_id: str, tenant: dict, tenant_id: str, args: dict, *,
    caller_name: str, caller_phone: str, adopted: list[dict],
):
    """W5 — book exactly what was offered, or refuse.

    Replaces the W4 guard. Every Square identifier comes from the stored slot
    offer; none comes from the model. There is no branch here that reconstructs a
    booking from arguments, so an invalid slot_ref can only ever mean "ask the
    caller to pick again".
    """
    if not call_id:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    slot_ref = (args.get("slot_ref") or "").strip()
    if not slot_ref:
        return _result(tc_id,
            "I need to check availability first so I can hold the right time. "
            "Ask the caller which location and service they want, check availability, "
            "then book the exact time they choose.")

    state = await call_location.get_or_create(call_id, tenant_id)
    if not state:
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    active_location_id = str(state.get("active_location_id") or "")

    status, offer = await slot_offers.resolve_for_booking(
        vapi_call_id=call_id, slot_ref=slot_ref, tenant_id=tenant_id,
        active_location_id=active_location_id)

    if status == slot_offers.ALREADY_BOOKED:
        # A retried tool call. Return the existing booking rather than making a
        # second one — Vapi retries are normal and must not double-book.
        logger.info("tools/book[multi]: slot %s already booked (%s) — idempotent return",
                    slot_ref, offer.get("booking_id"))
        return _result(tc_id, _booked_message(offer, tenant, pending=False, again=True,
                                              adopted=adopted))

    if status == slot_offers.IN_PROGRESS:
        # Claimed and still in flight, or an attempt whose outcome we never learned.
        # Either way a second CreateBooking is the one thing that must not happen.
        logger.warning("tools/book[multi]: slot %s is claimed and unfinalized — refusing", slot_ref)
        return _result(tc_id,
            "I'm still confirming that time with the calendar. Give me a moment and "
            "check with the caller before trying again — don't book it twice.")

    if status == slot_offers.NOT_FOUND:
        return _result(tc_id,
            "I couldn't find that time among the ones I offered. Please check "
            "availability again and pick from the times returned.")
    if status == slot_offers.EXPIRED:
        return _result(tc_id,
            "That time has been held too long to be sure it's still free. Let me "
            "check availability again before booking.")
    if status == slot_offers.WRONG_LOCATION:
        offered_at = next((l.get("name") for l in adopted
                           if str(l.get("id")) == str(offer.get("tenant_location_id"))), "another location")
        current = next((l.get("name") for l in adopted
                        if str(l.get("id")) == active_location_id), "the current location")
        return _result(tc_id,
            f"That time was offered for {offered_at}, but we're now looking at "
            f"{current}. Ask the caller which location they want, then check "
            f"availability there before booking.")

    location = next((l for l in adopted if str(l.get("id")) == str(offer.get("tenant_location_id"))), None)
    if not location or not location.get("active") or not location.get("booking_enabled"):
        return _result(tc_id,
            "That location isn't taking bookings at the moment. Would another "
            "location work?")

    token = await square_booking.get_access_token(tenant)
    if not token:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Re-check with Square immediately before creating. The offer may be minutes
    # old and someone else may have taken it; Square is the source of truth.
    start_dt = datetime.fromisoformat(str(offer["start_at_utc"]).replace("Z", "+00:00"))
    seg = await square_booking.resolve_slot(
        token, offer["provider_location_id"], offer["service_variation_id"],
        [offer["team_member_id"]] if offer.get("team_member_id") else [], start_dt)
    if not seg or not seg.get("team_member_id"):
        return _result(tc_id,
            "I'm sorry — that time has just been taken. Would you like me to check "
            "what else is free?")

    # caller_name is deliberately NOT passed: the Square customer is created from
    # phone alone so a retry replays byte-identically. The name still reaches the
    # OpenLines appointment record below, where W5.2's rules apply.
    cust_status, customer_id = await square_booking.resolve_customer(
        tenant_id=tenant_id, token=token, phone=caller_phone)
    if cust_status != customer_identity.OK or not customer_id:
        return _result(tc_id, _customer_problem_message(cust_status))

    # THE DESTRUCTIVE BOUNDARY. Two concurrent tool calls holding this slot_ref
    # compete on this CAS and only one can pass. Before this, both read consumed_at
    # as NULL and both reached CreateBooking — and because the idempotency key is a
    # fresh uuid4 per request, Square happily made two bookings.
    if not await slot_offers.claim(call_id, slot_ref, tenant_id):
        logger.warning("tools/book[multi]: lost the claim race on slot %s", slot_ref)
        return _result(tc_id,
            "I'm still confirming that time with the calendar. Give me a moment and "
            "check with the caller before trying again — don't book it twice.")

    try:
        booking = await square_booking.create_booking(
            token, location_id=offer["provider_location_id"],
            start_at_iso=seg.get("start_at") or offer["start_at_utc"],
            customer_id=customer_id, team_member_id=seg["team_member_id"],
            service_variation_id=offer["service_variation_id"],
            service_variation_version=(seg.get("service_variation_version")
                                       or offer.get("service_variation_version")),
            duration_minutes=seg.get("duration_minutes") or offer.get("duration_minutes"),
            note=f"Booked via Open Lines AI receptionist — {offer.get('service_name') or ''}".strip(),
        )
    except square_booking.BookingOutcomeUnknown as e:
        # The booking MAY exist. The slot stays claimed on purpose: releasing it
        # would let a retry issue a second CreateBooking under a fresh idempotency
        # key, turning one uncertain booking into two certain ones. The ordinary
        # booking body is rebuilt from a live resolve_slot, so it cannot be replayed
        # byte-identically either — replay is not available to us here.
        #
        # SCOPE OF THAT PROTECTION — read before relying on it:
        #   * The claim blocks a duplicate CreateBooking for THIS slot_ref during
        #     THIS call, and nothing more.
        #   * call_slot_offers rows are deleted unconditionally at end of call
        #     (webhooks.vapi_call_ended -> slot_offers.clear) and by the TTL sweep,
        #     regardless of consumed_at or booking_id.
        #   * The claim is therefore NOT durable reconciliation state. It does not
        #     survive the call and must never be described as if it did.
        #   * An unknown outcome can leave a real Square booking with NO OpenLines
        #     appointment row: invisible to caller_lookup, to cancellation
        #     enumeration and to the busy list. The caller's details captured below
        #     are the merchant's only thread to pull on.
        #   * Durable unknown-outcome reconciliation is deliberately DEFERRED (it
        #     belongs with the reschedule operation table and its sweeper). Do not
        #     infer that it already exists from the presence of this claim.
        logger.error("tools/book[multi]: RECONCILIATION REQUIRED — CreateBooking "
                     "outcome unknown for tenant %s slot %s: %s", tenant_id, slot_ref, e)
        return _result(tc_id,
            "I couldn't confirm whether the booking went through. I won't retry it "
            "during this request. Take the caller's name and number so the team can "
            "check, and ask them to let the business verify the appointment before "
            "trying again.")
    except Exception as e:
        # Definitive rejection: Square told us no, so nothing exists. Give the slot
        # back so the caller can try the same time again rather than be told it has
        # gone.
        logger.error("tools/book[multi]: CreateBooking failed for %s: %s", tenant_id, e)
        await slot_offers.release(call_id, slot_ref)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    booking_id = booking.get("id", "")
    pending = (booking.get("status") or "").upper() == "PENDING"
    await slot_offers.mark_consumed(call_id, slot_ref, booking_id)

    try:
        await db.insert_appointment({
            "tenant_id": tenant_id, "caller_name": caller_name or None, "caller_phone": caller_phone,
            "service": offer.get("service_name") or "Appointment",
            "appointment_datetime": offer["start_at_utc"],
            "duration_minutes": offer.get("duration_minutes") or 60,
            "status": "confirmed", "vapi_call_id": call_id,
            "google_event_id": booking_id,
            "tenant_location_id": offer.get("tenant_location_id"),
            "provider_location_id": offer.get("provider_location_id"),
        })
    except Exception as e:
        logger.error("tools/book[multi]: appointment mirror failed for %s: %s", tenant_id, e)

    analytics.capture(analytics.distinct_id_for(tenant, tenant_id), "appointment_booked",
                      {"tenant_id": tenant_id, "provider": "square_appointments",
                       "multi_location": True})
    logger.info("tools/book[multi]: booked %s at %s (booking %s, status %s)",
                offer.get("service_name"), offer["provider_location_id"], booking_id,
                booking.get("status"))
    return _result(tc_id, _booked_message(offer, tenant, pending=pending, adopted=adopted))


def _offer_timezone(offer: dict, tenant: dict, adopted: list[dict] | None) -> str:
    """The timezone a booked slot must be SPOKEN in.  (W8)

    The slot's identity is its UTC instant and nothing else -- that is what was
    offered, re-resolved and sent to Square, and it never changes. This decides
    only how that instant is read back to the caller.

    It has to be the LOCATION's timezone, not the tenant's. _booked_message used
    to read `offer["_tz"]`, which nothing has ever written, so it silently fell
    through to tenant.calendar_timezone. For DANI that happens to be correct --
    Cork, Dublin and Limerick are all Europe/Dublin, and so is the tenant -- but
    it is correct by coincidence of configuration, not by construction. A tenant
    whose locations span timezones would have heard its confirmation in the
    wrong one while the booking itself was right.

    Same precedence as availability (_multi_location_availability): the
    location's own timezone, then the provider's. The tenant value survives only
    as the legacy single-location fallback, where it is genuinely authoritative.
    """
    location_id = str(offer.get("tenant_location_id") or "")
    if location_id and adopted:
        location = next((l for l in adopted if str(l.get("id")) == location_id), None)
        if location:
            tz = (location.get("timezone")
                  or (location.get("_binding") or {}).get("provider_timezone") or "").strip()
            if tz:
                return tz
    return (offer.get("_tz") or tenant.get("calendar_timezone") or "UTC")


def _booked_message(offer: dict, tenant: dict, *, pending: bool, again: bool = False,
                    adopted: list[dict] | None = None) -> str:
    """Say booked only once Square says booked, and say pending when it is pending."""
    from zoneinfo import ZoneInfo as _ZI
    loc_name = offer.get("_loc_name") or ""
    try:
        tz = _ZI(_offer_timezone(offer, tenant, adopted))
        dt = datetime.fromisoformat(str(offer["start_at_utc"]).replace("Z", "+00:00")).astimezone(tz)
        h = dt.hour % 12 or 12
        when = f"{dt.strftime('%A, %B')} {dt.day} at {h}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    except Exception:
        when = str(offer.get("start_at_utc"))
    svc = offer.get("service_name") or "appointment"
    where = f" at {loc_name}" if loc_name else ""
    if again:
        return (f"That's already booked — {svc}{where} on {when}. Tell the caller it is "
                "confirmed and do not book it again.")
    if pending:
        return (f"Your {svc}{where} is requested for {when}. Tell the caller the shop "
                "will confirm shortly — do NOT say it is already confirmed.")
    return f"Done! Your {svc}{where} is confirmed for {when}."


async def _square_book_appointment(
    tc_id: str, call_id: str, tenant: dict, tenant_id: str, args: dict, *,
    caller_name: str, caller_phone: str, service: str, date_str: str,
    time_str: str, party_size: int,
):
    """Square Appointments booking path — writes into the merchant's Square calendar
    via CreateBooking. Square owns availability/slot allocation; we resolve the spoken
    service/staff to Square IDs, confirm the slot, and persist a mirror appointment row.
    Deposits are left to Square's native prepayment policy (not our deposit-link flow)."""
    token = await square_booking.get_access_token(tenant)
    location_id = tenant.get("square_location_id") or ""
    if not token or not location_id:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    timezone = tenant.get("square_location_timezone") or tenant.get("calendar_timezone") or "America/Toronto"
    business_name = tenant["business_name"]
    try:
        tz = ZoneInfo(timezone)
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except Exception as e:
        logger.error("tools/book[square]: datetime parse failed for %s: %s", tenant_id, e)
        return _result(tc_id, "I couldn't parse that date and time. Could you say it again?")

    services = await db.get_square_services(tenant_id, bookable_only=True)
    if not services:
        return _result(tc_id, _CALENDAR_ERROR_MSG)
    chosen = _match_square_service(service, services)
    duration = chosen.get("duration_minutes") or tenant.get("appointment_duration_minutes") or 60

    staff_rows = await db.get_square_staff(tenant_id)
    staff_by_id = {s["square_team_member_id"]: s.get("display_name") for s in staff_rows}
    team_ids = list(chosen.get("team_member_ids") or [])
    requested_name = None
    if args.get("staff") and staff_rows:
        roster = [{"name": s.get("display_name"), "id": s.get("square_team_member_id")} for s in staff_rows]
        matched = _match_staff(args.get("staff", ""), roster)
        if not matched:
            names = ", ".join(r["name"] for r in roster if r["name"])
            return _result(tc_id,
                f"I'm not sure which team member you meant by '{args.get('staff')}'. "
                f"We have {names}. Who would you like to book with?")
        team_ids = [matched["id"]]
        requested_name = matched["name"]
    if not team_ids:
        team_ids = [s["square_team_member_id"] for s in staff_rows]
    if not team_ids:
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Confirm the exact slot is bookable and pick the free team member + version.
    seg = await square_booking.resolve_slot(token, location_id, chosen["square_variation_id"], team_ids, start_dt)
    if not seg or not seg.get("team_member_id"):
        if requested_name:
            return _result(tc_id,
                f"I'm sorry, {requested_name} isn't available at that time. "
                "Would another time work, or shall I check who else is free?")
        return _result(tc_id,
            "I'm sorry — that time just filled up. Could we find another time that works for you?")
    team_member_id = seg["team_member_id"]
    staff_name = requested_name or staff_by_id.get(team_member_id)

    # RESCHEDULE, ONLY WHEN THE CALLER ASKED FOR ONE.
    #
    # This used to cancel any active appointment whose phone number matched, on the
    # assumption that a second booking meant a reschedule. Phone equality is not
    # intent: a caller may legitimately hold two appointments, on different days or
    # at different locations, and the old behaviour silently destroyed one of them.
    #
    # Ordering matters too. The cancel now happens AFTER a successful create, so a
    # failed booking leaves the original appointment intact rather than losing the
    # caller both.
    # caller_name is deliberately NOT passed: the Square customer is created from
    # phone alone so a retry replays byte-identically. The name still reaches the
    # OpenLines appointment record below, where W5.2's rules apply.
    cust_status, customer_id = await square_booking.resolve_customer(
        tenant_id=tenant_id, token=token, phone=caller_phone)
    if cust_status != customer_identity.OK or not customer_id:
        return _result(tc_id, _customer_problem_message(cust_status))

    try:
        booking = await square_booking.create_booking(
            token, location_id=location_id, start_at_iso=seg["start_at"], customer_id=customer_id,
            team_member_id=team_member_id, service_variation_id=chosen["square_variation_id"],
            service_variation_version=seg.get("service_variation_version") or chosen.get("variation_version"),
            duration_minutes=seg.get("duration_minutes") or duration,
            note=f"Booked via Open Lines AI receptionist — {service}",
        )
    except Exception as e:
        logger.error("tools/book[square]: create_booking failed for %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    booking_id = booking.get("id", "")
    pending = (booking.get("status") or "").upper() == "PENDING"
    logger.info("tools/book[square]: booked %s for tenant %s (booking %s, status %s)",
                service, tenant_id, booking_id, booking.get("status"))

    appt_data = {
        "tenant_id": tenant_id, "caller_name": caller_name or None, "caller_phone": caller_phone,
        "service": service, "appointment_datetime": start_dt.isoformat(),
        "duration_minutes": seg.get("duration_minutes") or duration, "party_size": party_size,
        "status": "confirmed", "vapi_call_id": call_id, "google_event_id": booking_id,
    }
    if staff_name:
        appt_data["staff_name"] = staff_name

    # W6A2-prereq: booking CREATES. It never cancels an existing appointment.
    # This path used to gate on args.get("reschedule") — a field no tool schema
    # ever exposed, so the branch could not run — and the presence of dead
    # destructive code is itself the hazard: the next person to add the argument
    # would have shipped implicit rescheduling without meaning to. Moving an
    # appointment will arrive as an explicit reschedule_appointment tool.
    try:
        await db.insert_appointment(appt_data)
    except Exception as e:
        logger.error("tools/book[square]: failed to save appointment mirror for %s: %s", tenant_id, e)
    analytics.capture(analytics.distinct_id_for(tenant, tenant_id), "appointment_booked",
                      {"tenant_id": tenant_id, "service": service, "provider": "square_appointments"})

    h = start_dt.hour % 12 or 12
    ampm = "AM" if start_dt.hour < 12 else "PM"
    suffix = f" with {staff_name}" if staff_name else ""
    friendly = f"{start_dt.strftime('%A, %B')} {start_dt.day} at {h}:{start_dt.minute:02d} {ampm}{suffix}"

    # SMS confirmation (mirrors the Google/MS path).
    try:
        sid, tok, biz = (tenant.get("twilio_subaccount_sid", ""), tenant.get("twilio_auth_token", ""),
                         tenant.get("twilio_phone_number", ""))
        if sid and tok and biz and caller_phone:
            greeting = f"Hi {caller_name}! " if caller_name else ""
            await telephony.send_sms(subaccount_sid=sid, subaccount_token=tok, from_number=biz,
                to_number=caller_phone,
                body=f"{greeting}Your {service} at {business_name} is confirmed for {friendly}. "
                     f"See you then! — {business_name}")
    except Exception as e:
        logger.error("tools/book[square]: SMS failed for %s: %s", tenant_id, e)

    if pending:
        return _result(tc_id,
            f"Your {service} at {business_name} is requested for {friendly}. Tell the caller the shop "
            f"will confirm the appointment shortly and they'll get a text once it's accepted.")
    return _result(tc_id,
        f"Done! Your {service} at {business_name} is confirmed for {friendly}. "
        "You'll receive a text confirmation shortly.")


@router.post("/{tenant_id}/availability")
@limiter.limit("30/minute", key_func=tenant_key)
async def check_availability(request: Request, tenant_id: str, body: dict):
    logger.info("tools/availability raw payload for tenant %s: %s", tenant_id, body)
    try:
        tc_id, _call_id, args = _parse_tool_call(body)
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

    # Trusted call metadata wins over anything the model supplied. This used to be
    # the other way round; the model is not authoritative for caller identity.
    caller_phone = trusted_caller_phone(body, args)

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/availability: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, _CALENDAR_ERROR_MSG)

    # Square Appointments provider — Square owns availability (pass-through).
    # Gated on square_appointments_enabled, which stays OFF until P2 wires booking.
    if tenant.get("square_appointments_enabled"):
        # W4 cutover: a tenant with >= 2 adopted locations takes the location-scoped
        # path and can never reach tenants.square_location_id. Everyone else stays
        # on the legacy branch below, unchanged. See services/call_location.
        try:
            multi, adopted = await call_location.is_multi_location(tenant_id)
        except Exception as e:
            logger.error("tools/availability: location mode check failed for %s: %s",
                         tenant_id, e)
            multi, adopted = False, []
        if multi:
            return await _multi_location_availability(
                tc_id, tenant, tenant_id, {**args, "_call_id": _call_id},
                date_str, _year_correction_prefix, adopted)
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

    # W6A2-prereq: the caller's own appointment used to be excluded from the busy
    # list, on the assumption that booking would replace it. Booking no longer
    # replaces anything, so that slot is simply occupied — advertising it because
    # of who holds it would offer a time the booking path then refuses on
    # capacity. It counts like every other appointment now.

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
    caller_phone = trusted_caller_phone(body, args)
    # W5.2: the model may hand back a phrase it read in its own prompt
    # ("Returning Caller"). Resolve against trusted history, then fall to no name
    # at all — never write conversational filler down as a person.
    caller_name  = await _trusted_caller_name(
        tenant_id, args.get("caller_name", ""), caller_phone)
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

    # W4 BOOKING BOUNDARY — deliberately fail closed.
    #
    # _square_book_appointment re-derives location, service, staff and slot from
    # scratch and reads tenants.square_location_id. For a multi-location tenant that
    # means a caller could hear Dublin availability and be booked into whatever the
    # legacy pointer names. The tool stays exposed on the assistant, so declining to
    # modify the booking path is NOT by itself a safeguard — this guard is.
    #
    # Removed in W5, when slot binding makes the offered slot and the booked
    # location provably the same thing. Legacy single-location booking is untouched.
    try:
        _multi, _adopted = await call_location.is_multi_location(tenant_id)
    except Exception as e:
        logger.error("tools/book: location mode check failed for %s: %s", tenant_id, e)
        _multi, _adopted = False, []
    if _multi:
        # W5: the guard is replaced by the slot-bound path. CreateBooking is now
        # reachable ONLY through a validated slot offer — see _multi_location_book.
        return await _multi_location_book(
            tc_id, call_id, tenant, tenant_id, args,
            caller_name=caller_name, caller_phone=caller_phone, adopted=_adopted)

    # Square Appointments: write the booking into the merchant's Square calendar.
    if tenant.get("square_appointments_enabled"):
        return await _square_book_appointment(
            tc_id, call_id, tenant, tenant_id, args, caller_name=caller_name,
            caller_phone=caller_phone, service=service, date_str=date_str,
            time_str=time_str, party_size=party_size)

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
    # W6A2-prereq: this path used to look up the caller's earliest active
    # appointment and cancel it before creating the new one — with no flag, no
    # confirmation, and a limit(1) guess about which appointment was meant. A
    # caller with two bookings who asked for a third lost one of them silently.
    # Booking CREATES. Moving an appointment will arrive as an explicit
    # reschedule_appointment tool; until then it is simply not offered here.

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
            # No self-exclusion any more: without a reschedule there is no "own"
            # appointment to discount, and a slot the caller already holds is
            # genuinely occupied. Capacity may now refuse the booking — which is a
            # booking rule refusing, not a cancellation happening.
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

    # W6A2-prereq: this used to waive the deposit when the caller already had a
    # paid appointment, because the booking was silently a reschedule and reused
    # that appointment's row. A NEW booking is a new commitment and carries its
    # own deposit; waiving it here would have let one paid deposit cover any
    # number of bookings. Deposit waiving for a genuine reschedule belongs with
    # the explicit reschedule tool, which keeps the original appointment row.
    already_paid = False

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

    appt_id = None
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
        # Always an insert. Updating an existing row in place is what made an
        # ordinary booking overwrite an appointment the caller still wanted.
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
        elif dep["error"] == "location_required":
            # W7E.2: multi-location business with no location context on the
            # deposit. The booking stands; only the deposit link was withheld.
            confirmation = (
                f"The {service} on {friendly} is held, but I could not send the deposit link because "
                f"the location for it is unclear. Tell the caller: 'Your appointment is held — our "
                f"team will follow up shortly to arrange the {amt} deposit.' Then close warmly. "
                f"Do NOT call request_deposit."
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
    if dep["error"] == "location_required":
        # W7E.2: a multi-location business, and this deposit carries no location
        # context. Guessing which of the caller's cities to charge against would
        # be worse than asking, so nothing was created and nothing was sent.
        return _result(
            tc_id,
            "I need to know which location this deposit is for before I can send the link. "
            "Ask the caller which location their appointment is at, then book or confirm the "
            "appointment for that location and try again. Do not invent a location.",
        )
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


async def _resolve_square_deposit_location(
        tenant: dict, appointment: dict | None, access_token: str) -> tuple[str, str]:
    """Which Square location THIS ONE deposit link is created against.

    Returns (provider_location_id, reason). An empty id means refuse.

    WHY THIS EXISTS (W7E.2)
    This path used to do:

        location_id = tenant.get("square_location_id") or ""
        if not location_id:
            locs = await list_locations(access_token)
            if locs:
                location_id = locs[0].get("id", "")
                await db.update_tenant(tenant_id, {"square_location_id": location_id})

    Two separate mistakes, stacked. It picked `locs[0]` -- Square's list order,
    which is not a business rule and does not even skip a closed location -- and
    then it PERSISTED that guess as the tenant's permanent default. A
    multi-location tenant could acquire a global default location merely because
    someone asked for a deposit. W7E.1 closed exactly this defect in catalog
    sync; this is the same defect on the payments path.

    THE TWO DECISIONS ARE NOT THE SAME DECISION
    "which location does this deposit belong to" and "what is this tenant's
    permanent default location" are different questions, and answering the first
    must never be allowed to invent an answer to the second. A deposit is always
    FOR an appointment, and that appointment already names the location the
    caller chose -- resolved through W4's trusted path, not guessed.

    AUTHORITY ORDER
      1. the appointment's own provider location, VERIFIED against this tenant's
         own bindings. It came from our booking path rather than from the model,
         and the verification is what stops a stale or cross-tenant id being
         trusted.
      2. the tenant's existing legacy pointer, unchanged -- backwards
         compatibility for every single-location tenant already in production.
      3. exactly one usable provider location, via the W7E.1 policy. One answer
         means list order cannot matter.
      4. otherwise refuse. Multiple usable locations and no context is a genuine
         ambiguity, and guessing which city to charge against is worse than
         asking.
    """
    tenant_id = str(tenant.get("id") or "")

    provider_location_id = str((appointment or {}).get("provider_location_id") or "").strip()
    if provider_location_id:
        try:
            binding = await db_loc.get_binding(tenant_id, "square", provider_location_id)
        except Exception as e:
            logger.warning("deposit location: binding lookup failed for tenant %s: %s", tenant_id, e)
            binding = None
        if binding:
            return provider_location_id, "appointment"
        # Not this tenant's location. Never charge against it.
        logger.warning(
            "deposit location: appointment names Square location %s which is not bound to "
            "tenant %s — ignoring it", provider_location_id, tenant_id)

    existing = str(tenant.get("square_location_id") or "").strip()
    if existing:
        return existing, "tenant_default"

    try:
        locations = await _sq_list_locations(access_token)
    except Exception as e:
        logger.warning("deposit location: could not list Square locations for tenant %s: %s",
                       tenant_id, e)
        return "", "provider_unavailable"

    chosen = location_sync.choose_legacy_default_square_location(None, locations)
    if chosen:
        return chosen, "single_location"

    usable = location_sync.usable_square_locations(locations)
    if len(usable) > 1:
        logger.warning(
            "deposit location: tenant %s has %d usable Square locations and this deposit "
            "carries no location context — refusing rather than guessing",
            tenant_id, len(usable))
        return "", "ambiguous"
    return "", "no_location"


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
            from services.square_service import create_payment_link
            from services.security import decrypt
            access_token = decrypt(tenant["square_access_token"])

            # W7E.2: the deposit's location comes from the appointment it is for,
            # never from Square's list order, and choosing one for THIS operation
            # never writes a permanent default onto the tenant.
            appointment = None
            if appointment_id:
                try:
                    appointment = await db.get_appointment_by_id(appointment_id)
                except Exception as _ae:
                    logger.warning("deposit location: appointment lookup failed for %s: %s",
                                   appointment_id, _ae)
            location_id, _why = await _resolve_square_deposit_location(
                tenant, appointment, access_token)
            if not location_id:
                # Fail closed: no Square call, no payment row, no tenant write.
                out["error"] = ("location_required" if _why == "ambiguous" else _why)
                return out
            if _why == "single_location":
                # The ONLY case that may still settle the legacy pointer: one
                # usable location means there is nothing to guess. Best-effort --
                # the deposit must not fail because a compatibility write did.
                try:
                    await db.update_tenant(tenant_id, {"square_location_id": location_id})
                except Exception as _ue:
                    logger.warning("deposit location: could not persist the single-location "
                                   "pointer for tenant %s: %s", tenant_id, _ue)
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
# POST /tools/{tenant_id}/reschedule
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/reschedule")
@limiter.limit("10/minute", key_func=tenant_key)
async def reschedule_appointment(request: Request, tenant_id: str, body: dict):
    """W6A2-D3 — move ONE chosen appointment to ONE chosen time, or nothing.

    Deliberately thin. Every decision that matters lives behind
    services.reschedule_intent: selection prechecks, the D1 freeze, the D2
    provider lifecycle, and the mapping from an internal state to the one
    sentence the assistant is allowed to say. Duplicating any of that here would
    give the reschedule path a second opinion about safety, and two opinions is
    how they drift.

    Two stages, matching cancellation. With no appointment_ref this LISTS and
    mutates nothing. With both references it moves exactly that appointment to
    exactly that offered time.

    The model supplies only two opaque, call-scoped references. It cannot name a
    date, a time, a location, a service, a provider id or a phone number, so it
    cannot ask for a booking that was never offered to this caller in this call.
    """
    try:
        tc_id, call_id, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/reschedule: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    caller_phone = trusted_caller_phone(body, args)
    if not caller_phone:
        return _result(tc_id, "I wasn't able to find your phone number to look up the appointment. Could you confirm the number on file?")
    if not call_id:
        # Both references are call-scoped, so without a call there is nothing to
        # scope them to and nothing can be verified.
        return _result(tc_id, "I can't look that up right now. Please call back and we'll get that sorted.")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/reschedule: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble looking that up. Please call back and we'll get that sorted.")
    tenant = tenant or {}

    ref_arg = (args.get("appointment_ref") or "").strip()
    slot_arg = (args.get("slot_ref") or "").strip()

    # ---- STAGE 1: list the caller's appointments, mutate nothing -------------
    if not ref_arg:
        return await _list_cancellable(tc_id, call_id, tenant, tenant_id,
                                       caller_phone, action="reschedule")

    if not slot_arg:
        # A chosen appointment but no chosen time. Asking for availability is the
        # only safe next step; acting on half a decision is not.
        return _result(tc_id,
            "I have the appointment but not a new time. Call check_availability "
            "for the same service at the same location, read the times back, and "
            "call reschedule_appointment again once the caller has picked one.")

    analytics.capture(analytics.distinct_id_for(tenant, tenant_id),
                      "reschedule_requested", {"tenant_id": tenant_id})

    outcome, message = await reschedule_intent.move_appointment(
        vapi_call_id=call_id, tenant_id=tenant_id, caller_phone=caller_phone,
        appointment_ref=ref_arg, slot_ref=slot_arg)

    # Success analytics fire ONLY on a proven completion. An uncertain outcome is
    # not a quieter success, and counting it as one would hide exactly the cases
    # that need a human.
    if outcome == reschedule_intent.COMPLETED:
        event = "reschedule_completed"
    elif outcome == reschedule_intent.CREATE_FAILED:
        event = "reschedule_create_failed"
    elif outcome in (reschedule_intent.SOURCE_CHANGED, reschedule_intent.CANCEL_FAILED,
                     reschedule_intent.UNRESOLVED):
        event = "reschedule_partial"
    else:
        event = ""
    if event:
        analytics.capture(analytics.distinct_id_for(tenant, tenant_id), event,
                          {"tenant_id": tenant_id, "outcome": outcome,
                           "provider": "square_appointments"})

    logger.info("tools/reschedule: tenant %s outcome %s", tenant_id, outcome)
    return _result(tc_id, message)


# ---------------------------------------------------------------------------
# POST /tools/{tenant_id}/cancel
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/cancel")
@limiter.limit("10/minute", key_func=tenant_key)
async def cancel_appointment(request: Request, tenant_id: str, body: dict):
    """W6A1 — cancel exactly the appointment the caller chose, or nothing.

    Two stages on purpose. With no appointment_ref this LISTS and mutates nothing,
    even when there is only one candidate: a single match is still a guess about
    which appointment the caller meant, and the whole point is to stop guessing at
    a destructive boundary. With a ref, every identifier used comes from the stored
    row rather than from anything the model said.
    """
    try:
        tc_id, call_id, args = _parse_tool_call(body)
    except Exception as e:
        logger.error("tools/cancel: bad payload for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")

    caller_phone = trusted_caller_phone(body, args)
    if not caller_phone:
        return _result(tc_id, "I wasn't able to find your phone number to look up the appointment. Could you confirm the number on file?")
    if not call_id:
        # Without a call there is nowhere to scope a ref, so nothing can be
        # verified — and an unverifiable cancellation must not happen.
        return _result(tc_id, "I can't look that up right now. Please call back and we'll get that sorted.")

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("tools/cancel: tenant lookup failed %s: %s", tenant_id, e)
        return _result(tc_id, "I had trouble processing the cancellation. Please call back and we'll get that sorted.")
    tenant = tenant or {}

    ref_arg = (args.get("appointment_ref") or "").strip()

    # ---- STAGE 1: list the caller's appointments, mutate nothing --------------
    if not ref_arg:
        return await _list_cancellable(tc_id, call_id, tenant, tenant_id, caller_phone)

    # ---- STAGE 2: resolve the ref, verify, then cancel ------------------------
    status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=call_id, appointment_ref=ref_arg,
        tenant_id=tenant_id, caller_phone=caller_phone)

    if status == appointment_refs.NOT_FOUND:
        return _result(tc_id,
            "I couldn't find that appointment among the ones I listed. Let me look "
            "up the caller's appointments again and confirm which one they mean.")
    if status == appointment_refs.EXPIRED:
        return _result(tc_id,
            "That list is out of date now. Let me look up the caller's appointments "
            "again before cancelling anything.")
    if status == appointment_refs.ALREADY_CONSUMED:
        # Idempotent: a retried tool call must never issue a second cancellation.
        return _result(tc_id,
            "That appointment has already been cancelled. Tell the caller it is "
            "done and do not cancel it again.")

    # C3: GLOBAL OWNERSHIP, before any authoritative validation.
    #
    # Appointment refs are call-scoped, so two simultaneous calls hold two
    # different ref rows for one appointment and both claim successfully. This
    # claim is keyed on the durable appointment id, so exactly one destructive
    # workflow can hold it — a cancel in one call and a reschedule in another can
    # no longer both reach Square.
    own_status, claim = await mutation_ownership.acquire_for_cancel(
        ref["appointment_id"], tenant_id)
    if own_status == mutation_ownership.BUSY:
        return _result(tc_id,
            "That appointment is being updated right now, so I can't safely cancel "
            "it at the moment. Ask the caller to give us a minute, or take their "
            "details so the team can confirm.")
    if own_status != mutation_ownership.ACQUIRED or claim is None:
        return _result(tc_id, "I had trouble processing the cancellation. Please call back and we'll get that sorted.")

    # AUTHORITATIVE re-read, under ownership. Everything checked before the claim
    # was advisory: the row could have changed between reading it and owning it,
    # and acting on the earlier read is the TOCTOU this ordering removes.
    appt = await db.get_appointment_by_id(ref["appointment_id"])
    if not appt or str(appt.get("tenant_id")) != str(tenant_id):
        await mutation_ownership.release(claim)
        return _result(tc_id, "I couldn't find that appointment. Please call back and we'll get that sorted.")
    if (appt.get("status") or "") not in ("confirmed", "pending_payment"):
        await mutation_ownership.release(claim)
        return _result(tc_id,
            "That appointment isn't active any more — it may already have been "
            "cancelled. Tell the caller there's nothing further to do.")
    if str(appt.get("caller_phone") or "") != caller_phone:
        logger.error("tools/cancel: INTEGRITY — ref %s resolved to an appointment "
                     "belonging to another caller (tenant %s)", ref_arg, tenant_id)
        await mutation_ownership.release(claim)
        return _result(tc_id, "I couldn't verify that appointment. Please call back and we'll get that sorted.")

    event_id = appt.get("google_event_id", "")
    if not event_id:
        await mutation_ownership.release(claim)
        return _result(tc_id,
            "I can't cancel that one automatically. Take the caller's details and "
            "let them know the team will confirm the cancellation.")

    # The snapshot taken at listing time must still describe the row we are about
    # to act on. A drift between them means something moved underneath us.
    if str(ref.get("provider_location_id") or "") != str(appt.get("provider_location_id") or "") \
            or str(ref.get("tenant_location_id") or "") != str(appt.get("tenant_location_id") or ""):
        logger.error("tools/cancel: INTEGRITY — ref %s snapshot no longer matches appointment %s "
                     "(ref loc %s/%s vs appt %s/%s)", ref_arg, appt.get("id"),
                     ref.get("tenant_location_id"), ref.get("provider_location_id"),
                     appt.get("tenant_location_id"), appt.get("provider_location_id"))
        await mutation_ownership.release(claim)
        return _result(tc_id,
            "Something doesn't line up with that appointment, so I haven't changed "
            "it. Take the caller's details and let them know the team will confirm.")

    # Claim the ref BEFORE touching the provider. Two concurrent tool calls holding
    # the same ref compete here, and only one can win.
    if not await appointment_refs.claim(call_id, ref_arg):
        await mutation_ownership.release(claim)
        return _result(tc_id,
            "That appointment has already been cancelled. Tell the caller it is "
            "done and do not cancel it again.")

    refresh_token, cal_provider = _calendar_provider(tenant)

    if tenant.get("square_appointments_enabled"):
        outcome = await _cancel_square_booking(tenant, appt, event_id, tenant_id)

        if outcome == "unknown":
            # C3's most important invariant. The cancellation MAY have landed, so
            # the appointment's status stays exactly as it was AND ownership is
            # retained — releasing here would let another workflow mutate an
            # appointment whose real provider state nobody knows. The claim moves
            # to cancel_reconcile and a recovery pass settles it against Square.
            await appointment_refs.release(call_id, ref_arg)
            await mutation_ownership.to_reconcile(
                claim, db_mc.REASON_PROVIDER_UNKNOWN)
            return _result(tc_id,
                "I couldn't confirm whether the cancellation went through, so I "
                "haven't changed the appointment. Take the caller's details — the "
                "team will check and confirm it with them.")

        if outcome != "ok":
            # The booking is NOT proven cancelled, so the appointment is still a
            # real appointment. appointments.status is business state, not the
            # result of an operation, and writing a failure into it would be read
            # inconsistently across the codebase: the enumeration and reschedule
            # lookups filter IN ('confirmed','pending_payment') and would stop
            # seeing it — so the caller could never retry — while the capacity
            # guard filters != 'cancelled' and would keep counting it. Leave the
            # status exactly as it was and let the logs carry the failure.
            await appointment_refs.release(call_id, ref_arg)
            logger.error("tools/cancel: provider cancellation NOT confirmed (%s) for "
                         "appointment %s / booking %s (tenant %s) — leaving status %r",
                         outcome, appt.get("id"), event_id, tenant_id, appt.get("status"))
            # Definitive: the booking is known NOT cancelled, so there is nothing
            # to reconcile and ownership is released for a later retry.
            await mutation_ownership.release(claim)
            if outcome == "mismatch":
                return _result(tc_id,
                    "I couldn't safely confirm that booking, so the appointment "
                    "remains in place. Take the caller's details and let them know "
                    "the team will confirm the cancellation.")
            return _result(tc_id,
                "I couldn't confirm the cancellation, so the appointment remains in "
                "place. Take the caller's details and let them know the team will "
                "confirm it.")
    elif refresh_token and event_id:
        # W6A1: a failed provider cancel used to be logged and stepped over, after
        # which the row was still marked cancelled — so the caller was told it was
        # done while the event stayed in the merchant's calendar.
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
            await appointment_refs.release(call_id, ref_arg)
            await mutation_ownership.release(claim)
            return _result(tc_id,
                "I couldn't confirm the cancellation, so the appointment remains in "
                "place. Take the caller's details and let them know the team will "
                "confirm it.")
        except Exception as e:
            # Same rule as Square: unproven cancellation leaves business state alone.
            logger.error("tools/cancel: provider cancellation NOT confirmed for event %s "
                         "(tenant %s) — leaving status %r: %s",
                         event_id, tenant_id, appt.get("status"), e)
            await appointment_refs.release(call_id, ref_arg)
            await mutation_ownership.release(claim)
            return _result(tc_id,
                "I couldn't confirm the cancellation, so the appointment remains in "
                "place. Take the caller's details and let them know the team will "
                "confirm it.")
    else:
        # No provider to cancel against and no way to verify. Refuse rather than
        # mark our own row cancelled and call it done.
        logger.error("tools/cancel: no usable provider for appointment %s (tenant %s)",
                     appt.get("id"), tenant_id)
        await appointment_refs.release(call_id, ref_arg)
        await mutation_ownership.release(claim)
        return _result(tc_id,
            "I can't cancel that one automatically. Take the caller's details and "
            "let them know the team will confirm the cancellation.")

    # Provider has confirmed. Only now does our own record change — and with a
    # targeted patch, not a whole-row write-back of a value read seconds ago.
    try:
        await db.update_appointment(appt["id"], {"status": "cancelled"})
        await mutation_ownership.release(claim)
    except Exception as e:
        # Square says cancelled, we failed to write it down. Do NOT retry the
        # provider: it is already done, and a second attempt only risks acting on
        # something else. Say the true thing and leave a loud trail.
        # The ref is deliberately NOT released here. The provider mutation already
        # happened; handing the ref back would invite a second destructive attempt
        # at an appointment that is already cancelled. Square's re-fetch behaviour
        # would make that harmless, but "harmless by luck" is not the property we
        # want at a destructive boundary. Reconciliation is a human/queue job.
        # Provider truth is settled; our record is not. Ownership is RETAINED and
        # moved to cancel_reconcile so no other workflow can act on a row that
        # still reads 'confirmed' while its booking is gone.
        await mutation_ownership.to_reconcile(claim, db_mc.REASON_LOCAL_WRITE_FAILED)
        logger.error("tools/cancel: RECONCILIATION REQUIRED — provider cancelled "
                     "booking %s but appointment %s could not be updated (tenant %s): %s",
                     event_id, appt["id"], tenant_id, e)
        return _result(tc_id,
            "The appointment has been cancelled with the business, but I couldn't "
            "update our own record. Tell the caller the cancellation is confirmed, "
            "and let the team know the booking needs checking.")

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


# ===========================================================================
# AI Call Routing — mid-call tools (DECISION layer; no telephony yet).
#
#   classify-and-route : the AI passes its classification; the server runs the
#                        deterministic routing_engine against the tenant's approved
#                        profile/rules/destinations, RECORDS the decision (audit),
#                        and returns a natural-language directive. It NEVER returns a
#                        phone number to the AI. Actual transfer execution is a
#                        separate telephony layer gated by ROUTING_TRANSFER_ENABLED;
#                        until that is on, a "transfer" decision degrades to the safe
#                        callback fallback (never a false promise / dropped call).
#   create-callback    : record a structured callback request (the always-safe
#                        fallback) so the team can call the caller back.
#
# Both inherit the router-level X-Vapi-Secret gate.
# ===========================================================================

_HANDLE_MSG = ("You can handle this yourself — continue helping the caller. Do not "
               "transfer or promise a callback unless they ask.")
_CALLBACK_MSG = ("Let the caller know the right person will call them back shortly. "
                 "Capture their name and the reason if you don't have them, then call "
                 "the create_callback tool and close warmly.")
_TRANSFER_MSG = ("Tell the caller you're connecting them to the team now, then hand off.")


def _caller_phone_from(body: dict, args: dict) -> str:
    msg = body.get("message", body)
    cust = (msg.get("call") or {}).get("customer") or {}
    return (cust.get("number") or cust.get("phoneNumber")
            or (msg.get("customer") or {}).get("number", "")
            or args.get("caller_phone", ""))


def _source_from(body: dict) -> str:
    """direct | forwarded | unknown — best-effort (forwarding indicator, if present)."""
    msg = body.get("message", body)
    call = msg.get("call") or {}
    if call.get("forwardedFrom") or (msg.get("phoneNumber") or {}).get("forwardedFrom"):
        return "forwarded"
    return "unknown"


async def _do_classify_and_route(tenant_id: str, body: dict) -> dict:
    tc_id, call_id, args = _parse_tool_call(body)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    # Not entitled / feature dark -> the AI simply keeps handling the call.
    if not tenant or not entitlements.has_feature(tenant, "routing"):
        return _result(tc_id, _HANDLE_MSG)

    profile = await rdb.get_profile(tenant_id) or {}
    rules = await rdb.list_rules(tenant_id, profile["id"]) if profile.get("id") else []
    dests = {d["id"]: {"type": d.get("type"), "enabled": d.get("enabled", True)}
             for d in await rdb.list_destinations(tenant_id)}

    try:
        conf = float(args.get("confidence")) if args.get("confidence") is not None else None
    except (TypeError, ValueError):
        conf = None
    caller_phone = _caller_phone_from(body, args)
    is_returning = False
    if caller_phone:
        try:
            is_returning = bool(await db.get_lead_by_phone(tenant_id, caller_phone))
        except Exception:
            is_returning = False

    ctx = {
        "intent": args.get("intent"), "urgency": args.get("urgency"),
        "requested_person": args.get("requested_person"), "language": args.get("language"),
        "confidence": conf, "text": args.get("text"), "is_returning": is_returning,
    }
    decision = routing_engine.evaluate(profile, rules, dests, ctx)

    # Audit — best-effort, never blocks the call.
    try:
        await rdb.insert_routing_decision({
            "tenant_id": tenant_id, "vapi_call_id": call_id, "source": _source_from(body),
            "intent": ctx["intent"], "urgency": ctx["urgency"], "confidence": conf,
            "matched_rule_id": decision.matched_rule_id,
            "chosen_destination_id": decision.destination_id,
            "decision": decision.decision, "evaluated": {"reason": decision.reason},
        })
    except Exception as e:
        logger.warning("classify-and-route: could not record decision for %s: %s", tenant_id, e)

    analytics.capture(analytics.distinct_id_for(tenant, tenant_id), "routing_decision",
                      {"tenant_id": tenant_id, "decision": decision.decision, "reason": decision.reason})

    # Map decision -> AI directive. Transfer only if the telephony layer is live.
    if decision.decision == "transfer":
        if entitlements.transfer_execution_enabled():
            return _result(tc_id, _TRANSFER_MSG)
        logger.info("classify-and-route: transfer decided but execution disabled — callback fallback (%s)", tenant_id)
        return _result(tc_id, _CALLBACK_MSG)
    if decision.decision == "callback":
        return _result(tc_id, _CALLBACK_MSG)
    return _result(tc_id, _HANDLE_MSG)   # handled_ai (incl. public-emergency: never dial)


@router.post("/{tenant_id}/classify-and-route")
@limiter.limit("60/minute", key_func=tenant_key)
async def classify_and_route(request: Request, tenant_id: str, body: dict):
    try:
        return await _do_classify_and_route(tenant_id, body)
    except ValueError as e:
        logger.error("tools/classify-and-route: bad payload for %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")


async def _do_create_callback(tenant_id: str, body: dict) -> dict:
    tc_id, call_id, args = _parse_tool_call(body)
    caller_phone = _caller_phone_from(body, args)
    data = {
        "call_id": None, "caller_name": args.get("caller_name") or "",
        "caller_phone": caller_phone, "reason": args.get("reason") or "",
        "urgency": args.get("urgency") or "", "status": "open",
    }
    try:
        await rdb.create_callback(tenant_id, data)
    except Exception as e:
        logger.error("tools/create-callback: failed to store for %s: %s", tenant_id, e)
        return _result(tc_id, "I've noted your request and the team will follow up. "
                              "Is there anything else I can help with?")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        analytics.capture(analytics.distinct_id_for(tenant, tenant_id), "callback_requested",
                          {"tenant_id": tenant_id})
    except Exception:
        pass
    return _result(tc_id, "Perfect — I've taken your details and the team will call you back "
                          "shortly. Is there anything else I can help you with?")


@router.post("/{tenant_id}/create-callback")
@limiter.limit("20/minute", key_func=tenant_key)
async def create_callback(request: Request, tenant_id: str, body: dict):
    try:
        return await _do_create_callback(tenant_id, body)
    except ValueError as e:
        logger.error("tools/create-callback: bad payload for %s: %s", tenant_id, e)
        raise HTTPException(status_code=400, detail="Malformed tool-call payload")
