"""
Microsoft Graph Calendar service for Open Lines.
Mirrors the interface of services/calendar.py (Google) so tools.py can dispatch
to either provider based on which token the tenant has.
"""

import os
import logging
from datetime import datetime, timedelta, date as date_type
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_MS_AUTH_BASE  = "https://login.microsoftonline.com"
_MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_SCOPES = "openid profile email offline_access User.Read Calendars.ReadWrite"

_PERIOD_HOURS = {
    "morning":   (9, 12),
    "afternoon": (12, 17),
    "evening":   (17, 21),
    "any":       (9, 17),
}

_SLOT_STEP = 15  # minutes between candidate slot start times


class MsCalendarTokenExpiredError(Exception):
    """Microsoft refresh token has been revoked, expired, or is otherwise invalid."""


def _env() -> tuple[str, str, str, str]:
    client_id     = os.getenv("MICROSOFT_CLIENT_ID", "")
    ms_tenant_id  = os.getenv("MICROSOFT_TENANT_ID", "common")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    redirect_uri  = os.getenv("MICROSOFT_REDIRECT_URI", "")
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, and MICROSOFT_REDIRECT_URI must be set"
        )
    return client_id, ms_tenant_id, client_secret, redirect_uri


def build_oauth_url(state: str) -> str:
    client_id, ms_tenant_id, _, redirect_uri = _env()
    params = {
        "client_id":     client_id,
        "response_type": "code",
        "redirect_uri":  redirect_uri,
        "response_mode": "query",
        "scope":         _SCOPES,
        "state":         state,
        "prompt":        "consent",
    }
    return f"{_MS_AUTH_BASE}/{ms_tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    client_id, ms_tenant_id, client_secret, redirect_uri = _env()
    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_MS_AUTH_BASE}/{ms_tenant_id}/oauth2/v2.0/token",
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "code":          code,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
                "scope":         _SCOPES,
            },
            timeout=15.0,
        )
        res.raise_for_status()
        return res.json()


async def _refresh_tokens(refresh_token: str) -> dict:
    client_id, ms_tenant_id, client_secret, redirect_uri = _env()
    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_MS_AUTH_BASE}/{ms_tenant_id}/oauth2/v2.0/token",
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type":    "refresh_token",
                "scope":         _SCOPES,
            },
            timeout=15.0,
        )
        if res.status_code in (400, 401):
            try:
                err = res.json().get("error", "")
            except Exception:
                err = ""
            if err in ("invalid_grant", "interaction_required"):
                raise MsCalendarTokenExpiredError(f"Microsoft token invalid: {err}")
        res.raise_for_status()
        return res.json()


async def _access_token(refresh_token: str) -> str:
    tokens = await _refresh_tokens(refresh_token)
    return tokens["access_token"]


async def verify_token(refresh_token: str) -> bool:
    try:
        access = await _access_token(refresh_token)
        async with httpx.AsyncClient() as http:
            res = await http.get(
                f"{_MS_GRAPH_BASE}/me",
                headers={"Authorization": f"Bearer {access}"},
                timeout=8.0,
            )
            return res.status_code == 200
    except MsCalendarTokenExpiredError:
        return False
    except Exception as e:
        logger.warning("ms_calendar.verify_token failed: %s", e)
        return False


async def get_user_email(refresh_token: str) -> str | None:
    try:
        access = await _access_token(refresh_token)
        async with httpx.AsyncClient() as http:
            res = await http.get(
                f"{_MS_GRAPH_BASE}/me",
                headers={"Authorization": f"Bearer {access}"},
                params={"$select": "mail,userPrincipalName,identities"},
                timeout=8.0,
            )
            if res.status_code != 200:
                return None
            d = res.json()

            # Best: mail field (set for most personal/work accounts)
            if d.get("mail"):
                return d["mail"]

            # Second: identities array — emailAddress sign-in type holds the real address
            for identity in d.get("identities") or []:
                if identity.get("signInType") == "emailAddress":
                    email = identity.get("issuerAssignedId")
                    if email:
                        return email

            # Fallback: reconstruct from external-user UPN format
            # e.g. "User_outlook.com#EXT#@tenant.onmicrosoft.com" → "User@outlook.com"
            upn = d.get("userPrincipalName", "")
            if "#EXT#" in upn:
                local = upn.split("#EXT#")[0]
                idx = local.rfind("_")
                if idx > 0:
                    return local[:idx] + "@" + local[idx + 1:]

            return upn or None
    except Exception:
        pass
    return None


def _parse_graph_dt(dt_str: str, tz: ZoneInfo) -> datetime:
    """Parse a Microsoft Graph dateTime string to a timezone-aware datetime.

    When the Prefer: outlook.timezone header is sent, Graph returns local time
    without an offset suffix — we attach the requested timezone directly.
    """
    clean = dt_str.rstrip("Z")
    if "+" in clean or clean.count("-") > 2:
        return datetime.fromisoformat(clean).astimezone(tz)
    return datetime.fromisoformat(clean).replace(tzinfo=tz)


def _fmt_slot(dt: datetime) -> str:
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
    business_days: list[int] | None = None,
    break_start: int | None = None,
    break_end: int | None = None,
    slot_capacity: int = 1,
    booked_ranges: list[tuple[datetime, datetime]] | None = None,
    our_event_ids: set[str] | None = None,
) -> list[str]:
    tz = ZoneInfo(timezone)
    appt_date = date_type.fromisoformat(date_str)

    if business_days is not None and appt_date.weekday() not in business_days:
        return []

    if period == "any":
        hour_start, hour_end = business_hours_start, business_hours_end
    else:
        hour_start, hour_end = _PERIOD_HOURS.get(period, (business_hours_start, business_hours_end))

    window_start = datetime(appt_date.year, appt_date.month, appt_date.day, hour_start, 0, tzinfo=tz)
    window_end   = datetime(appt_date.year, appt_date.month, appt_date.day, hour_end,   0, tzinfo=tz)

    break_start_dt = break_end_dt = None
    if break_start is not None and break_end is not None and break_end > break_start:
        break_start_dt = datetime(appt_date.year, appt_date.month, appt_date.day, break_start, 0, tzinfo=tz)
        break_end_dt   = datetime(appt_date.year, appt_date.month, appt_date.day, break_end,   0, tzinfo=tz)

    access = await _access_token(refresh_token)

    async with httpx.AsyncClient() as http:
        res = await http.get(
            f"{_MS_GRAPH_BASE}/me/calendarView",
            headers={
                "Authorization": f"Bearer {access}",
                "Prefer": f'outlook.timezone="{timezone}"',
            },
            params={
                "startDateTime": window_start.strftime("%Y-%m-%dT%H:%M:%S"),
                "endDateTime":   window_end.strftime("%Y-%m-%dT%H:%M:%S"),
                "$select":       "id,subject,start,end,showAs",
                "$top":          "100",
            },
            timeout=15.0,
        )
        res.raise_for_status()
        items = res.json().get("value", [])

    busy: list[tuple[datetime, datetime]] = []
    for event in items:
        show_as = event.get("showAs", "")
        if show_as in ("free", "workingElsewhere", "unknown"):
            continue
        if our_event_ids and event.get("id") and event.get("id") in our_event_ids:
            continue
        if exclude_event_id and event.get("id") == exclude_event_id:
            continue
        start_str = (event.get("start") or {}).get("dateTime", "")
        end_str   = (event.get("end")   or {}).get("dateTime", "")
        if not start_str or not end_str:
            continue
        try:
            busy.append((_parse_graph_dt(start_str, tz), _parse_graph_dt(end_str, tz)))
        except Exception:
            continue

    # Fallback exclusion by time range when no event ID (e.g. cross-provider reschedule)
    if exclude_range and not exclude_event_id:
        busy.append(exclude_range)

    if break_start_dt is not None and break_end_dt is not None:
        busy.append((break_start_dt, break_end_dt))

    now = datetime.now(tz)
    slots: list[str] = []
    cursor = window_start

    while cursor + timedelta(minutes=duration_minutes) <= window_end:
        slot_end = cursor + timedelta(minutes=duration_minutes)
        if cursor < now + timedelta(minutes=30):
            cursor += timedelta(minutes=_SLOT_STEP)
            continue
        if any(cursor < b_end and slot_end > b_start for b_start, b_end in busy):
            cursor += timedelta(minutes=_SLOT_STEP)
            continue
        if booked_ranges:
            taken = sum(1 for s, e in booked_ranges if cursor < e and slot_end > s)
            if taken >= slot_capacity:
                cursor += timedelta(minutes=_SLOT_STEP)
                continue
        slots.append(_fmt_slot(cursor))
        cursor += timedelta(minutes=_SLOT_STEP)

    return slots[:32]


async def create_event(
    refresh_token: str,
    title: str,
    start_dt: datetime,
    duration_minutes: int,
    timezone: str,
    description: str = "",
) -> dict:
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    access = await _access_token(refresh_token)

    async with httpx.AsyncClient() as http:
        res = await http.post(
            f"{_MS_GRAPH_BASE}/me/events",
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type":  "application/json",
            },
            json={
                "subject": title,
                "body":    {"contentType": "text", "content": description},
                "start":   {
                    "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": timezone,
                },
                "end": {
                    "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "timeZone": timezone,
                },
            },
            timeout=15.0,
        )
        res.raise_for_status()
        data = res.json()
        logger.info("Microsoft Calendar event created: %s", str(data.get("id", ""))[:20])
        return {"id": data.get("id", ""), "webLink": data.get("webLink", "")}


async def cancel_event(refresh_token: str, event_id: str) -> None:
    access = await _access_token(refresh_token)
    async with httpx.AsyncClient() as http:
        res = await http.delete(
            f"{_MS_GRAPH_BASE}/me/events/{event_id}",
            headers={"Authorization": f"Bearer {access}"},
            timeout=15.0,
        )
        if res.status_code not in (200, 204, 404):
            res.raise_for_status()
        logger.info("Microsoft Calendar event deleted: %s", str(event_id)[:20])
