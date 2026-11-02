"""Relative dates, resolved by the server from the call time in the tenant's timezone.

On 2 Nov 2026 a caller asked for "the day after tomorrow" and the model passed
2026-11-05: the prompt gave it today's date and asked it to count, and it counted
one day too far. The model is not a calendar. These helpers give it the answers
instead of the arithmetic, and let the tools check what it passes.

Only phrases with one reading are resolved. "Next Thursday" means this week's
Thursday to some people and the following one to others, so it returns None and
the model asks.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Toronto"

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "a": 1}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def tenant_tz(tenant: dict | None) -> ZoneInfo:
    try:
        return ZoneInfo((tenant or {}).get("calendar_timezone") or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def today_for(tenant: dict | None) -> date:
    """The tenant's local date right now. Never the server's: at 11 p.m. in
    Toronto it is already tomorrow in UTC."""
    return _utcnow().astimezone(tenant_tz(tenant)).date()


def resolve_phrase(phrase: str, today: date) -> date | None:
    """The date a caller's words name, or None when they don't name exactly one."""
    p = re.sub(r"[^a-z0-9 ]", " ", (phrase or "").lower())
    p = re.sub(r"\b(the|on|for|of|please|um|uh)\b", " ", p)
    p = " ".join(p.split())
    if not p:
        return None
    if p in ("today", "tonight", "this evening", "this afternoon", "this morning"):
        return today
    if p in ("tomorrow", "tomorrow morning", "tomorrow afternoon", "tomorrow evening"):
        return today + timedelta(days=1)
    if p in ("day after tomorrow", "day after tomorrow morning",
             "day after tomorrow afternoon", "overmorrow"):
        return today + timedelta(days=2)
    m = re.fullmatch(r"in (\w+) days?", p)
    if m:
        n = _NUMBERS.get(m.group(1)) or (int(m.group(1)) if m.group(1).isdigit() else None)
        return today + timedelta(days=n) if n else None
    m = re.fullmatch(r"(this )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                     r"( morning| afternoon| evening)?", p)
    if m:
        ahead = (_WEEKDAYS.index(m.group(2)) - today.weekday()) % 7
        # "Monday" said on a Monday could mean today or a week today.
        return None if ahead == 0 else today + timedelta(days=ahead)
    return None


def spoken_date(d: date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def relative_label(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == 2:
        return "the day after tomorrow"
    if delta < 0:
        return "in the past"
    return f"{delta} days from today"


def prompt_block(tenant: dict | None) -> str:
    """Today's date plus the next two weeks, already worked out."""
    today = today_for(tenant)
    tz_name = str(tenant_tz(tenant))
    rows = []
    for i in range(15):
        d = today + timedelta(days=i)
        label = {0: "Today", 1: "Tomorrow", 2: "Day after tomorrow"}.get(i, d.strftime("%A"))
        rows.append(f"- {label}: {spoken_date(d)} ({d.isoformat()})")
    return (
        f"\n\nTODAY'S DATE: {today.strftime('%A, %B %d, %Y')} ({today.isoformat()}), "
        f"in {tz_name}. The current year is {today.year}.\n"
        "These dates are already worked out. Use them; never count days yourself:\n"
        + "\n".join(rows) + "\n"
        "- Month and day with no year: use the next time that date comes round, never a past year.\n"
        "- 'Next <weekday>' can mean this week or the week after: ask which date they mean.\n"
        "- Whenever the caller names a day in words ('tomorrow', 'Thursday'), pass their exact "
        "words as date_phrase as well as the date, so the system can check it."
    )


def check(date_str: str, phrase: str, tenant: dict | None) -> tuple[str | None, str | None]:
    """Validate a model-supplied date against the call time.

    Returns (date, None) when it is usable, or (None, instruction) when it is not:
    malformed, in the past, or different from the day the caller's words name.
    """
    today = today_for(tenant)
    try:
        d = date.fromisoformat(date_str)
    except (TypeError, ValueError):
        return None, ("That date isn't in YYYY-MM-DD form. Work it out from TODAY'S DATE "
                      "and try again.")
    named = resolve_phrase(phrase, today) if phrase else None
    if named and named != d:
        return None, (
            f"Date mismatch: the caller said '{phrase}', which is {spoken_date(named)} "
            f"({named.isoformat()}), {relative_label(named, today)}, not {date_str}. "
            f"Nothing has been checked or booked. Use {named.isoformat()} and say it to the "
            f"caller as {named.strftime('%A, %B')} {named.day}.")
    if d < today:
        return None, (
            f"{spoken_date(d)} is in the past: today is {spoken_date(today)}. Nothing has "
            "been checked or booked. Ask the caller which upcoming date they mean.")
    return d.isoformat(), None
