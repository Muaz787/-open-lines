"""New businesses get their own time zone, not the America/Toronto default."""
import pytest

from services import business_timezone as btz
from services import provisioning


@pytest.mark.parametrize("browser,country,want", [
    ("America/Chicago", "US", "America/Chicago"),          # Texas owner (tenant c8e18590)
    ("America/Los_Angeles", "US", "America/Los_Angeles"),
    ("America/Indiana/Indianapolis", "US", "America/Indiana/Indianapolis"),
    ("Pacific/Honolulu", "US", "Pacific/Honolulu"),
    ("America/Vancouver", "CA", "America/Vancouver"),
    ("America/Halifax", "CA", "America/Halifax"),
    ("America/St_Johns", "CA", "America/St_Johns"),
    ("Europe/Dublin", "IE", "Europe/Dublin"),
    ("ie", "IE", "Europe/Dublin"),                          # not a zone
])
def test_the_owners_zone_is_used_when_it_fits_the_country(browser, country, want):
    assert btz.resolve(browser, country) == want


@pytest.mark.parametrize("browser,country,want", [
    ("Europe/London", "US", "America/New_York"),           # owner travelling
    ("America/Toronto", "US", "America/New_York"),         # Canadian zone, US business
    ("America/Chicago", "CA", "America/Toronto"),
    ("America/New_York", "IE", "Europe/Dublin"),
    ("", "US", "America/New_York"),
    (None, "CA", "America/Toronto"),
    ("Not/AZone", "US", "America/New_York"),
    ("America/Chicago" + "x" * 80, "US", "America/New_York"),
    ("America/Chicago", "", "America/Toronto"),
    ("America/Chicago", "GB", "America/Toronto"),
])
def test_otherwise_the_countrys_main_zone(browser, country, want):
    assert btz.resolve(browser, country) == want


def test_every_listed_zone_is_real():
    from zoneinfo import ZoneInfo
    for tz in btz._CA | btz._US | btz._IE | set(btz.DEFAULT_BY_COUNTRY.values()):
        ZoneInfo(tz)


def test_the_new_tenant_row_carries_the_resolved_zone():
    row = provisioning._initial_tenant_row(
        {"business_name": "Riya", "industry": "beauty", "timezone": "America/Chicago"}, "US")
    assert row["calendar_timezone"] == "America/Chicago"
    row = provisioning._initial_tenant_row({"business_name": "B", "industry": "x"}, "US")
    assert row["calendar_timezone"] == "America/New_York"


def test_signup_accepts_the_browser_zone():
    from routers.onboarding import ProvisionRequest
    assert ProvisionRequest(business_name="B", industry="beauty", country="US",
                            timezone="America/Chicago").timezone == "America/Chicago"
    assert ProvisionRequest(business_name="B", industry="beauty", country="US").timezone == ""
