"""
The business's time zone at signup.

Until now every new tenant got the column default, America/Toronto, whatever
country they chose. A US business with a Texas number (tenant c8e18590,
14 Nov 2026) was therefore an hour out for its hours, availability and
bookings until someone noticed.

The owner's browser reports its IANA zone at signup (Intl.DateTimeFormat), and
the owner is almost always where the business is. We use it when it is a real
zone AND belongs to the country they chose. Otherwise, for example an owner
signing up while travelling, or a browser that reports nothing, we use the
country's most populous zone. The owner can change it later in settings, and a
Square location's own zone still takes precedence for Square bookings.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

DEFAULT_BY_COUNTRY = {
    "CA": "America/Toronto",
    "US": "America/New_York",
    "IE": "Europe/Dublin",
}
FALLBACK = "America/Toronto"

_CA = {
    "America/St_Johns", "America/Halifax", "America/Glace_Bay", "America/Moncton",
    "America/Goose_Bay", "America/Toronto", "America/Montreal", "America/Nipigon",
    "America/Thunder_Bay", "America/Iqaluit", "America/Pangnirtung", "America/Atikokan",
    "America/Winnipeg", "America/Rainy_River", "America/Resolute", "America/Rankin_Inlet",
    "America/Regina", "America/Swift_Current", "America/Edmonton", "America/Cambridge_Bay",
    "America/Yellowknife", "America/Inuvik", "America/Creston", "America/Dawson_Creek",
    "America/Fort_Nelson", "America/Whitehorse", "America/Dawson", "America/Vancouver",
    "America/Blanc-Sablon",
    "Canada/Newfoundland", "Canada/Atlantic", "Canada/Eastern", "Canada/Central",
    "Canada/Saskatchewan", "Canada/Mountain", "Canada/Pacific", "Canada/Yukon",
}
_US = {
    "America/New_York", "America/Detroit", "America/Chicago", "America/Menominee",
    "America/Denver", "America/Boise", "America/Phoenix", "America/Los_Angeles",
    "America/Anchorage", "America/Juneau", "America/Sitka", "America/Metlakatla",
    "America/Yakutat", "America/Nome", "America/Adak", "America/Puerto_Rico",
    "Pacific/Honolulu",
    "US/Eastern", "US/Central", "US/Mountain", "US/Pacific", "US/Alaska", "US/Hawaii",
    "US/Arizona", "US/Michigan", "US/East-Indiana", "US/Indiana-Starke", "US/Aleutian",
}
_US_PREFIXES = ("America/Indiana/", "America/Kentucky/", "America/North_Dakota/")
_IE = {"Europe/Dublin", "Eire"}


def _valid(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def belongs_to(tz: str, country: str) -> bool:
    cc = (country or "").strip().upper()
    if cc == "CA":
        return tz in _CA
    if cc == "US":
        return tz in _US or tz.startswith(_US_PREFIXES)
    if cc == "IE":
        return tz in _IE
    return False


def resolve(browser_tz: str | None, country: str | None) -> str:
    """The zone to store for a new business. Always a valid IANA name."""
    cc = (country or "").strip().upper()
    tz = (browser_tz or "").strip()
    if tz and len(tz) <= 64 and _valid(tz) and belongs_to(tz, cc):
        return tz
    return DEFAULT_BY_COUNTRY.get(cc, FALLBACK)
