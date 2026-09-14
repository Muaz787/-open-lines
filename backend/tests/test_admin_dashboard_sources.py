"""Everything the admin displays must come from one derivation.

TWO DEFECTS THIS CLOSES, both found by comparing the rendered pages:

  * CAL said "—" for a tenant whose receptionist was booking. has_calendar
    read google_refresh_token alone, so Outlook and Square connections were
    invisible — and the Calendar: yes/no filter and the tenant health-issues
    list inherited the same blind spot. Live: DANI and DANI Test — Internal
    both had Square connected and both showed as having no calendar.

  * Overview and Revenue disagreed about the same tenants. Overview compared
    subscription_status directly; Revenue used billingStatus(). A comped
    account carries status 'active', so Overview counted it as a paying
    customer AND booked its plan price as revenue — the admin reported $957
    MRR against a real $758, money from a free account. Card-free trials carry
    status 'none', so four of five trials were invisible there.

Parsed rather than grepped: a comment explaining the old behaviour must not be
able to satisfy or break an assertion about the new one.
"""
import re
from pathlib import Path

import pytest

FE = Path(__file__).resolve().parents[2] / "frontend" / "src"
API = FE / "app" / "api" / "admin"

TENANTS = (API / "tenants" / "route.ts").read_text()
DETAIL = (API / "tenants" / "[id]" / "route.ts").read_text()
OVERVIEW = (API / "overview" / "route.ts").read_text()
REVENUE = (API / "revenue" / "route.ts").read_text()
BILLING = (FE / "lib" / "billing.ts").read_text()

#: The three columns the backend's setup-state treats as a connected calendar.
PROVIDER_COLUMNS = ("google_refresh_token", "microsoft_refresh_token", "square_access_token")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


# ── the calendar column ─────────────────────────────────────────────────

#: Ids given explicitly — passing a route's source as a parameter otherwise
#: prints the entire file into the test name.
_ROUTES = [pytest.param(TENANTS, "tenant list", id="tenant_list"),
           pytest.param(DETAIL, "tenant detail", id="tenant_detail")]


@pytest.mark.parametrize("src,label", _ROUTES)
def test_a_connected_calendar_means_any_provider(src, label):
    body = _strip_comments(src)
    # The DERIVING EXPRESSION, not the file. "or col in body" was satisfied by
    # the select listing the columns while the derivation still read Google
    # alone — the exact bug, passing its own test.
    i = body.index("has_calendar:")
    expr = body[i:body.index("\n", body.index(",", body.index(")", i)))] \
        if "(" in body[i:i + 200] else body[i:i + 200]
    expr = body[i:i + 260]
    resolved = expr if "hasCalendar(" not in expr else body[body.index("function hasCalendar"):][:300]
    for col in PROVIDER_COLUMNS:
        assert col in resolved, f"{label} derives has_calendar without {col}"


@pytest.mark.parametrize("src,label", _ROUTES)
def test_every_provider_column_is_actually_selected(src, label):
    """Deriving from a column the query never fetched reads as always-false —
    silently, which is how the Square connections went unseen."""
    body = _strip_comments(src)
    select = body[body.index(".select("):]
    for col in PROVIDER_COLUMNS:
        assert col in select[:900], f"{label} derives from {col} but never selects it"


def test_the_health_issue_does_not_name_one_vendor():
    """"Google Calendar not connected" sent an operator hunting a fault that
    was not there, for a tenant booking happily through Square."""
    body = _strip_comments(DETAIL)
    assert "Google Calendar not connected" not in body
    assert "hasCalendar(t)" in body


# ── one billing derivation ──────────────────────────────────────────────

def test_overview_and_revenue_share_one_derivation():
    for src, label in ((OVERVIEW, "overview"), (REVENUE, "revenue")):
        assert "@/lib/billing" in src, f"{label} does not use the shared helper"


def test_no_admin_route_compares_subscription_status_by_hand():
    """The comparison that made the two pages disagree."""
    for route in sorted(API.rglob("route.ts")):
        body = _strip_comments(route.read_text())
        assert "subscription_status ===" not in body, (
            f"{route.name} re-derives billing status; use billingStatus()")


def test_a_comped_tenant_is_not_revenue():
    """billingStatus maps billing_exempt FIRST, before the Stripe status, which
    is the whole reason a comp stops counting as a paying customer."""
    body = _strip_comments(BILLING)
    i = body.index("export function billingStatus")
    fn = body[i:body.index("}", body.index("return", i))]
    assert fn.index("billing_exempt") < fn.index("subscription_status"), (
        "a comped tenant must be classified before its Stripe status is read")


def test_mrr_is_summed_over_paying_tenants_only():
    """The set MRR reduces over must be defined by isPaying(), wherever that
    filter happens to sit — Revenue builds `active` first and reduces over it,
    Overview filters inline. What neither may do is reach for the raw status,
    which is what booked a comped account as revenue.
    """
    for src, label in ((OVERVIEW, "overview"), (REVENUE, "revenue")):
        body = _strip_comments(src)
        assert "isPaying(" in body, f"{label} never consults isPaying()"
        line = next(l for l in body.splitlines() if "mrr" in l and "reduce" in l) \
            if any("mrr" in l and "reduce" in l for l in body.splitlines()) \
            else next(l for l in body.splitlines() if "mrr" in l)
        assert "subscription_status" not in line, (
            f"{label} sums MRR against the raw status: {line.strip()}")


def test_overview_selects_what_its_derivation_reads():
    """billingStatus reads billing_exempt and created_at; a select missing
    either makes every tenant look un-comped or permanently expired."""
    body = _strip_comments(OVERVIEW)
    select = body[body.index("from('tenants')"):][:400]
    for col in ("billing_exempt", "created_at", "subscription_status", "subscription_plan"):
        assert col in select, f"overview derives from {col} but never selects it"
