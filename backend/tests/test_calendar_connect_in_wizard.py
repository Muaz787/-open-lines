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
    # Gate C.1 lifted the tick body out of the setInterval callback so it could
    # await the server; the property is the same and lives in tick().
    start = body.index("const tick = useCallback")
    tick = body[start:body.index("}, [poll, clearTimers])", start)]
    assert "poll()" in tick and "closed" in tick
    assert tick.index("poll()") < tick.index("closed"), (
        "the close check must not short-circuit the poll")


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


def test_no_provider_hands_off_to_the_dashboard():
    """A customer in onboarding is there to reach a working phone number. A step
    that sends them elsewhere to finish IS the flow ending: the provider's
    redirect lands them on the dashboard and the wizard is simply over.

    Square was the last one doing this, because authorising it leaves services
    and staff unimported and booking switched off."""
    array = _strip_block_comments(PROVIDERS)
    array = array[array.index("CALENDAR_PROVIDERS"):]
    assert "/dashboard/" not in array, "a provider still hands off to the dashboard"


def test_square_declares_what_finishing_it_takes():
    """Connected is not bookable: Square imports services and staff and then has
    to be switched on. Reporting success in between is the same lie as the old
    hand-off, just quieter."""
    array = _strip_block_comments(PROVIDERS)
    array = array[array.index("CALENDAR_PROVIDERS"):]
    i = array.index("id: 'square'")
    entry = array[i:i + 500]
    assert "finalize" in entry
    assert "syncPath" in entry and "enablePath" in entry


def test_finishing_runs_before_success_is_reported():
    """An ORDER, and the reason this component exists: a connected Square with
    nothing synced looks identical to a working one from the outside."""
    body = _strip_block_comments(CC)
    i = body.index("const ok = id ? await finalize(id) : true")
    after = body[i:i + 200]
    assert "finish()" in after, "success must follow the finalize call"
    assert body.index("finish()", i) > i


def test_a_failed_finish_does_not_report_success():
    body = _strip_block_comments(CC)
    i = body.index("const ok = id ? await finalize(id) : true")
    window = body[i:i + 500]
    # The property, not the punctuation: whatever shape the branch takes, the
    # only call to finish() here must sit behind the success of finalize().
    line = next(l for l in window.splitlines() if "finish()" in l)
    assert "if (ok)" in line, f"success is not conditional on finishing: {line.strip()}"
    assert "setError(" in window, "and the customer must be told when it did not"


def test_only_one_poll_may_finish_a_connection():
    """The interval keeps firing while finalize awaits. A second pass would
    re-sync and re-enable behind the first."""
    body = _strip_block_comments(CC)
    i = body.index("claimed.current = true")
    before = body[max(0, i - 300):i]
    assert "if (claimed.current) return" in before


def test_every_provider_declares_how_it_starts():
    """The list is the contract; an entry without a start is a dead button."""
    src = _strip_block_comments(PROVIDERS)
    array = src[src.index("CALENDAR_PROVIDERS"):]
    ids = re.findall(r"id: '([a-z]+)'", array)
    starts = re.findall(r"start: \{", array)
    assert len(ids) >= 3
    assert len(starts) == len(ids), f"{len(ids)} providers but {len(starts)} starts"


# ── the success screen ──────────────────────────────────────────────────

def test_the_success_screen_connects_inline_rather_than_linking_out():
    """It offered "one more step: connect your calendar" as a link to the
    dashboard — the same hand-off the calendar step itself no longer does."""
    body = _strip_block_comments(ONB)
    i = body.index("One more step: connect your calendar")
    panel = body[i - 400:i + 1400]
    assert "CalendarConnect" in panel
    assert "/calendar`}" not in panel, "the panel links out again"


def test_the_success_screen_does_not_nag_a_customer_who_connected():
    """It used to render unconditionally, telling someone who had just connected
    a calendar that they still had one more step."""
    body = _strip_block_comments(ONB)
    i = body.index("One more step: connect your calendar")
    guard = body[max(0, i - 500):i]
    assert "!setup?.integration_connected" in guard
