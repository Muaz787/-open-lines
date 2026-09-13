"""Connecting a booking system must not end onboarding.

THE DEFECT THIS CLOSES
The calendar step was a link to /dashboard/<id>/calendar. A customer who took
it authorised Google and was returned by the provider's redirect to the
DASHBOARD -- so onboarding ended there, notifications never set and, for a
regulated tenant, no filing made. The step whose whole job is to show what the
receptionist can do was the one that threw the customer out of the flow.

Authorisation now happens in a popup and the wizard survives it. These tests
pin the three properties that make that work, each of which fails silently
rather than loudly if it regresses.
"""
import ast
import re
from pathlib import Path

FE = Path(__file__).resolve().parents[2] / "frontend" / "src"
ONB = (FE / "app" / "onboarding" / "page.tsx").read_text()
CC = (FE / "components" / "CalendarConnect.tsx").read_text()
PROVIDERS = (FE / "lib" / "calendarProviders.ts").read_text()
DASH_CAL = (FE / "app" / "dashboard" / "[tenantId]" / "calendar" / "page.tsx").read_text()


def _strip_block_comments(src: str) -> str:
    """Strip BOTH comment forms.

    Prose explaining what the code deliberately does NOT do must not be able to
    satisfy — or break — an assertion about what it does. Block comments alone
    were not enough: the line comment above the poll tick explains why a closed
    popup is not a verdict, and the word "closed" in that sentence broke an
    assertion about where `closed` first appears in the code.

    The (?<!:) guard keeps `https://` out of it.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


# ── the step stays in the wizard ────────────────────────────────────────

def test_the_calendar_step_no_longer_links_out_of_onboarding():
    """A <Link> to the dashboard calendar page is the defect itself: following
    it hands the flow to the provider's redirect, which lands on the dashboard."""
    body = _strip_block_comments(ONB)
    i = body.index("stage === 'calendar' && result")
    step = body[i:i + 2000]
    assert "CalendarConnect" in step
    assert "/calendar`}" not in step, "the step links out again"
    assert "<Link" not in step, "the step links out again"


def test_the_step_does_not_name_its_own_successor():
    """Same rule as every other step: the server decides what comes next."""
    body = _strip_block_comments(ONB)
    # The JSX use, not the import at the top of the file.
    i = body.index("<CalendarConnect")
    window = body[i:i + 600]
    assert "advance(" in window
    for smell in ("setStage('notifications')", "setStage('finalsetup')", "setStage('done')"):
        assert smell not in window, smell


# ── completion comes from our server, never from the popup ──────────────

def test_completion_is_established_from_our_own_server():
    """The popup is cross-origin the moment it reaches Google, so its location
    cannot be read. Anything that appeared to read it would be reading nothing."""
    body = _strip_block_comments(CC)
    assert "setup-state" in body, "completion must be asked of our API"
    for smell in ("popup.current.location", "win.location.href.includes",
                  "popup.current?.location.href", ".location.search"):
        assert smell not in body, smell


def test_a_closed_popup_is_not_treated_as_a_failure():
    """A customer can complete the connection in the instant before the window
    closes. Only the server's answer ends the wait.

    The property is an ORDER — the poll must run BEFORE the closed check, not
    merely somewhere near it. An earlier draft of this test asserted proximity
    and passed against a mutant that returned on `closed` without polling at
    all, which is the exact regression it exists to catch.
    """
    body = _strip_block_comments(CC)
    start = body.index("window.setInterval(")
    tick = body[start:body.index("}, POLL_MS)", start)]
    assert "poll()" in tick and "closed" in tick
    assert tick.index("poll()") < tick.index("closed"), (
        "the close check must not short-circuit the poll")
    assert "return" not in tick, "nothing may leave the tick before the poll runs"


# ── the popup must survive the browser ──────────────────────────────────

def test_the_popup_opens_before_any_await():
    """A popup opened AFTER a network round trip is unsolicited as far as the
    browser is concerned, and is blocked. It must be opened synchronously from
    the click and pointed at its destination afterwards.

    Parsed, not grepped: the ORDER of the two statements is the property, and no
    substring search can establish an order.
    """
    src = _strip_block_comments(CC)
    fn = re.search(r"async function start\([^)]*\)\s*\{.*?\n  \}", src, re.S)
    assert fn, "start() not found"
    opened = fn.group(0).index("window.open(")
    first_await = fn.group(0).index("await ")
    assert opened < first_await, "window.open must precede the first await"


def test_a_blocked_popup_falls_back_instead_of_stranding():
    """window.open returns null when blocked. Doing nothing there would leave a
    customer clicking a button that silently does nothing."""
    body = _strip_block_comments(CC)
    assert "window.location.assign(" in body


# ── one provider list ───────────────────────────────────────────────────

def test_both_surfaces_read_one_provider_list():
    """A second hardcoded route is a connect button that stops working the day a
    route moves -- silently, because nothing renders differently until clicked."""
    assert "calendarProviders" in CC
    assert "calendarProviders" in DASH_CAL
    for surface, name in ((CC, "CalendarConnect"), (DASH_CAL, "dashboard calendar")):
        body = _strip_block_comments(surface)
        assert "/calendar/connect/" not in body, f"{name} hardcodes a route"
        assert "/calendar/microsoft/connect" not in body, f"{name} hardcodes a route"


def test_square_is_not_presented_as_a_one_click_connect():
    """Authorising Square leaves services and staff unsynced and booking not yet
    enabled. A wizard button implying otherwise would report success for a
    calendar that cannot take a booking -- and Square also refuses outright on a
    subscription that has not started, which every regulated tenant has."""
    tree_src = _strip_block_comments(PROVIDERS)
    i = tree_src.index("id: 'square'")
    entry = tree_src[i:i + 400]
    assert "kind: 'page'" in entry, "Square must hand off, not claim to connect"
    assert "kind: 'url'" not in entry


def test_every_provider_declares_how_it_starts():
    """The list is the contract; an entry without a start is a dead button."""
    src = _strip_block_comments(PROVIDERS)
    # The array literal only. The type union above it declares both kinds by
    # definition, and counting those would make this assertion meaningless.
    array = src[src.index("CALENDAR_PROVIDERS"):]
    ids = re.findall(r"id: '([a-z]+)'", array)
    kinds = re.findall(r"kind: '(url|page)'", array)
    assert len(ids) >= 3
    assert len(kinds) == len(ids), f"{len(ids)} providers but {len(kinds)} starts"
