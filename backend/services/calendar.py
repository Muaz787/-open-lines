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
_SCOPES      = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"
_SLOT_STEP   = 30  # minutes between candidate slots


class CalendarTokenExpiredError(Exception):
    """Google refresh token has been revoked, expired, or is otherwise invalid."""

# Business hour window per period (local time, inclusive start, exclusive end)
_PERIOD_HOURS: dict[str, tuple[int, int]] = {
    "morning":   (9, 12),
    "afternoon": (12, 17),
    "evening":   (17, 19),
    "any":       (9, 17),
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
                f"{_CAL_BASE}/users/me/calendarList?maxResults=1",
                headers={"Authorization": f"Bearer {access}"},
                timeout=8.0,
            )
            ok = res.status_code == 200
            if not ok:
                logger.warning("verify_token: calendarList returned %s", res.status_code)
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
    exclude_range: tuple[datetime, datetime] | None = None,
) -> list[str]:
    """Return available slot strings (e.g. '2:00 PM') for the given date.

    exclude_range: if provided, any Google Calendar busy period that aligns with
    this (start, end) pair is ignored — used during reschedules so the caller's
    existing appointment doesn't block the new slot search.
    """
    tz = ZoneInfo(timezone)
    appt_date = date_type.fromisoformat(date_str)

    hour_start, hour_end = _PERIOD_HOURS.get(period, (9, 17))
    window_start = datetime(appt_date.year, appt_date.month, appt_date.day, hour_start, 0, tzinfo=tz)
    window_end   = datetime(appt_date.year, appt_date.month, appt_date.day, hour_end,   0, tzinfo=tz)

    access = await _access_token(refresh_token)
    headers = {"Authorization": f"Bearer {access}"}

    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_CAL_BASE}/freeBusy",
            headers=headers,
            json={
                "timeMin": window_start.isoformat(),
                "timeMax": window_end.isoformat(),
                "items":   [{"id": "primary"}],
            },
            timeout=15.0,
        )
        res.raise_for_status()
        raw_busy = res.json().get("calendars", {}).get("primary", {}).get("busy", [])

    # Normalise exclude_range to local tz once (avoids repeated conversions below)
    ex_start_tz = ex_end_tz = None
    if exclude_range:
        ex_start_tz = exclude_range[0].astimezone(tz)
        ex_end_tz   = exclude_range[1].astimezone(tz)

    busy: list[tuple[datetime, datetime]] = []
    for bp in raw_busy:
        b_start = datetime.fromisoformat(bp["start"].replace("Z", "+00:00")).astimezone(tz)
        b_end   = datetime.fromisoformat(bp["end"].replace("Z", "+00:00")).astimezone(tz)
        # Drop this busy period if it matches the caller's existing appointment
        # (±5 min tolerance handles DST edge cases and calendar rounding)
        if ex_start_tz is not None:
            if (abs((b_start - ex_start_tz).total_seconds()) < 300
                    and abs((b_end - ex_end_tz).total_seconds()) < 300):
                logger.debug("Excluding reschedule conflict: %s–%s", b_start, b_end)
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

    return slots[:6]


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
