"""What "Today", "7d" and "30d" mean, in one place.

A period is a run of calendar days in the tenant's own timezone, ending today:
7d is today plus the six days before it. Dashboard metrics all use this window,
so a total on the overview matches the same period in the call history.

Days are counted on the calendar, not as 24-hour blocks, so a daylight-saving day
stays one day.
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PERIOD_DAYS = {"today": 1, "7d": 7, "30d": 30}


def tenant_zone(tenant: dict | None) -> ZoneInfo:
    """The tenant's timezone, or UTC when it is unset or not a real zone."""
    name = str((tenant or {}).get("calendar_timezone") or "").strip()
    try:
        return ZoneInfo(name) if name else ZoneInfo("UTC")
    except Exception:
        return ZoneInfo("UTC")


def period_start(days: int, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """Local midnight `days - 1` calendar days ago, as a UTC datetime."""
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    first_day = today - timedelta(days=max(days, 1) - 1)
    return datetime.combine(first_day, time.min, tzinfo=tz).astimezone(timezone.utc)


def day_index(moment: datetime, start: datetime, tz: ZoneInfo) -> int:
    """How many local calendar days `moment` falls after `start`."""
    return (moment.astimezone(tz).date() - start.astimezone(tz).date()).days


def local_day(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).date().isoformat()
