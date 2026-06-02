import os
import logging
from datetime import datetime, timedelta, date as date_type
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL   = "https://oauth2.googleapis.com/token"
_CAL_BASE    = "https://www.googleapis.com/calendar/v3"
_SCOPES      = "https://www.googleapis.com/auth/calendar.events"
_SLOT_STEP   = 30  # minutes between candidate slots


class CalendarTokenExpiredError(Exception):
    """Google refresh token has been revoked, expired, or is otherwise invalid."""

# Business hour window per period (local time, inclusive start, exclusive end)
_PERIOD_HOURS: dict[str, tuple[int, int]] = {
    "morning":   (9, 12),
    "afternoon": (12, 17),
    "evening":   (17, 21),
    "any":       (9, 17),   # overridden per-tenant via business_hours_start/end
}


_PROD_REDIRECT_URI = "https://backend-production-71174.up.railway.app/calendar/callback"


def build_oauth_url(state: str) -> str:
    GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", _PROD_REDIRECT_URI)
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI must be set")
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         _SCOPES,
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         state,
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange an authorisation code for access + refresh tokens."""
    GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", _PROD_REDIRECT_URI)
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise RuntimeError("Google OAuth env vars must be set")
    async with httpx.AsyncClient() as http:
        res = await http.post(_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        }, timeout=15.0)
        res.raise_for_status()
        return res.json()


async def _access_token(refresh_token: str) -> str:
    GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise RuntimeError("Google OAuth env vars must be set")
    async with httpx.AsyncClient() as http:
        res = await http.post(_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type":    "refresh_token",
        }, timeout=15.0)
        if res.status_code == 400:
            try:
                err = res.json().get("error", "")
            except Exception:
                err = ""
            if err in ("invalid_grant", "token_revoked"):
                logger.warning("Google refresh token is expired/revoked — raising CalendarTokenExpiredError")
                raise CalendarTokenExpiredError(f"Google token invalid: {err}")
        res.raise_for_status()
        return res.json()["access_token"]


async def verify_token(refresh_token: str) -> bool:
    """Test that a refresh token can successfully obtain an access token and
    reach the Calendar API. Called right after OAuth exchange to catch bad tokens
    before they get stored."""
    try:
        access = await _access_token(refresh_token)
        async with httpx.AsyncClient() as http:
            res = await http.get(
                f"{_CAL_BASE}/calendars/primary/events?maxResults=1",
                headers={"Authorization": f"Bearer {access}"},
                timeout=8.0,
            )
            ok = res.status_code == 200
            if not ok:
                logger.warning("verify_token: events.list returned %s", res.status_code)
            return ok
    except CalendarTokenExpiredError:
        return False
    except Exception as e:
        logger.warning("verify_token failed: %s", e)
        return False


def _fmt_slot(dt: datetime) -> str:
    """Format a datetime as '2:00 PM' or '2:30 PM'."""
    h = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{h}:{dt.minute:02d} {ampm}"


async def list_free_slots(
    refresh_token: str,
    date_str: str,
    duration_minutes: int,
    timezone: str,
    period: str = "any",
    exclude_event_id: str | None = None,
    exclude_range: tuple[datetime, datetime] | None = None,
    business_hours_start: int = 9,
    business_hours_end: int = 17,
) -> list[str]:
    """Return available slot strings (e.g. '2:00 PM') for the given date.

    business_hours_start / business_hours_end override the 'any' window so
    each tenant's full working day is shown (e.g. 8-20 for a 24h business).

    exclude_event_id: Google Calendar event ID to ignore — used during reschedules.
    exclude_range: fallback time-range exclusion (±5 min tolerance).
    """
    tz = ZoneInfo(timezone)
    appt_date = date_type.fromisoformat(date_str)

    if period == "any":
        hour_start, hour_end = business_hours_start, business_hours_end
    else:
        hour_start, hour_end = _PERIOD_HOURS.get(period, (business_hours_start, business_hours_end))
    window_start = datetime(appt_date.year, appt_date.month, appt_date.day, hour_start, 0, tzinfo=tz)
    window_end   = datetime(appt_date.year, appt_date.month, appt_date.day, hour_end,   0, tzinfo=tz)

    access = await _access_token(refresh_token)
    headers = {"Authorization": f"Bearer {access}"}

    # Use events.list (authorized under calendar.events scope) instead of
    # freeBusy (which requires calendar.readonly and would need an extra scope).
    async with httpx.AsyncClient() as http:
        res = await http.get(
            f"{_CAL_BASE}/calendars/primary/events",
            headers=headers,
            params={
                "timeMin":      window_start.isoformat(),
                "timeMax":      window_end.isoformat(),
                "singleEvents": "true",
                "orderBy":      "startTime",
            },
            timeout=15.0,
        )
        res.raise_for_status()
        items = res.json().get("items", [])

    # Normalise exclude_range to local tz once (avoids repeated conversions below)
    ex_start_tz = ex_end_tz = None
    if exclude_range:
        ex_start_tz = exclude_range[0].astimezone(tz)
        ex_end_tz   = exclude_range[1].astimezone(tz)

    busy: list[tuple[datetime, datetime]] = []
    for event in items:
        start_info = event.get("start", {})
        end_info   = event.get("end", {})
        start_str  = start_info.get("dateTime") or start_info.get("date")
        end_str    = end_info.get("dateTime")   or end_info.get("date")
        if not start_str or not end_str:
            continue
        try:
            # All-day events have date-only strings — treat them as full-day blocks
            if "T" not in start_str:
                b_start = datetime.fromisoformat(start_str).replace(hour=0,  minute=0,  tzinfo=tz)
                b_end   = datetime.fromisoformat(end_str).replace(  hour=23, minute=59, tzinfo=tz)
            else:
                b_start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(tz)
                b_end   = datetime.fromisoformat(end_str.replace(  "Z", "+00:00")).astimezone(tz)
        except Exception:
            continue
        # Primary exclusion: match by Google event ID (exact, never fails on tz rounding)
        event_id = event.get("id", "")
        if exclude_event_id and event_id and event_id == exclude_event_id:
            logger.debug("Excluding reschedule event by ID %s: %s–%s", event_id, b_start, b_end)
            continue
        # Fallback exclusion: time-range match (±5 min tolerance for DST edge cases)
        if ex_start_tz is not None:
            if (abs((b_start - ex_start_tz).total_seconds()) < 300
                    and abs((b_end - ex_end_tz).total_seconds()) < 300):
                logger.debug("Excluding reschedule conflict by time range: %s–%s", b_start, b_end)
                continue
        busy.append((b_start, b_end))

    now = datetime.now(tz)
    slots: list[str] = []
    cursor = window_start

    while cursor + timedelta(minutes=duration_minutes) <= window_end:
        slot_end = cursor + timedelta(minutes=duration_minutes)

        # Skip past slots (require at least 30-min notice)
        if cursor < now + timedelta(minutes=30):
            cursor += timedelta(minutes=_SLOT_STEP)
            continue

        # Skip if overlaps any busy period
        if any(cursor < b_end and slot_end > b_start for b_start, b_end in busy):
            cursor += timedelta(minutes=_SLOT_STEP)
            continue

        slots.append(_fmt_slot(cursor))
        cursor += timedelta(minutes=_SLOT_STEP)

    # Return the full day's availability (cap at 32 to cover even long business
    # days). Previously capped at 6, which made a free 9-5 day stop at 11:30 AM.
    # The availability tool tells the AI to confirm the caller's specific
    # requested time, so a longer list is fine — the AI won't read all aloud.
    return slots[:32]


async def cancel_event(refresh_token: str, event_id: str) -> None:
    """Delete a Google Calendar event by ID."""
    access = await _access_token(refresh_token)
    headers = {"Authorization": f"Bearer {access}"}
    async with httpx.AsyncClient() as http:
        res = await http.delete(
            f"{_CAL_BASE}/calendars/primary/events/{event_id}",
            headers=headers,
            timeout=15.0,
        )
        if res.status_code not in (200, 204, 410):
            res.raise_for_status()
        logger.info("Deleted Google Calendar event %s", event_id)


async def create_event(
    refresh_token: str,
    title: str,
    start_dt: datetime,
    duration_minutes: int,
    timezone: str,
    description: str = "",
) -> dict:
    """Create a Google Calendar event. Returns {id, htmlLink}."""
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    access = await _access_token(refresh_token)
    headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}

    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_CAL_BASE}/calendars/primary/events",
            headers=headers,
            json={
                "summary":     title,
                "description": description,
                "start":       {"dateTime": start_dt.isoformat(), "timeZone": timezone},
                "end":         {"dateTime": end_dt.isoformat(),   "timeZone": timezone},
            },
            timeout=15.0,
        )
        res.raise_for_status()
        data = res.json()
        logger.info("Created Google Calendar event %s", data.get("id"))
        return {"id": data.get("id", ""), "htmlLink": data.get("htmlLink", "")}
