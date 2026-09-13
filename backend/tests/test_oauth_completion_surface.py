"""OAuth returns to a page that renders nothing (Gate C.1).

THE DEFECT THIS CLOSES
Every callback redirected to a full dashboard page. Run in a popup opened by
onboarding -- which is how a customer connects a calendar during signup -- that
meant the popup loaded the whole dashboard, painted it, and was only then closed
by the opener's next poll. Observed live: a few seconds of dashboard in the
middle of an Irish signup.

The numbering follows Gate C.1 Part M.
"""
import ast
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from services import oauth_return as R

BACKEND = Path(__file__).resolve().parents[1]
FE = BACKEND.parent / "frontend" / "src"

CAL = (BACKEND / "routers" / "calendar.py").read_text()
SQ = (BACKEND / "routers" / "square_connect.py").read_text()
COMPLETE = (FE / "app" / "oauth" / "complete" / "page.tsx").read_text()
CC = (FE / "components" / "CalendarConnect.tsx").read_text()
ONB = (FE / "app" / "onboarding" / "page.tsx").read_text()

FRONT = "https://www.openlines.ai"
TENANT = "fb3e73c9-a482-4ffc-b3e3-d504c569940f"


def _strip_comments(src: str) -> str:
    """Both forms. Prose about what the code deliberately does NOT do must not
    be able to satisfy — or break — an assertion about what it does."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


def _redirect_targets(src: str, func: str) -> list[str]:
    """Every RedirectResponse target expression inside one function, by AST.

    Parsed rather than grepped: a docstring describing the old dashboard URL
    would otherwise fail a test about where the code actually redirects.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == func:
            out = []
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and getattr(call.func, "id", "") == "RedirectResponse"):
                    arg = (call.args[0] if call.args
                           else next((k.value for k in call.keywords if k.arg == "url"), None))
                    out.append(ast.unparse(arg) if arg is not None else "")
            return out
    raise AssertionError(f"{func} not found")


# ── 1-3. no onboarding success may land on the dashboard ────────────────

#: (module source, callback function, label). Ids given explicitly — passing the
#: source as a parameter otherwise prints an entire router into the test name.
_CALLBACKS = [
    pytest.param(SQ, "callback", "square", id="square"),
    pytest.param(CAL, "calendar_callback", "google", id="google"),
    pytest.param(CAL, "microsoft_callback", "microsoft", id="microsoft"),
]


@pytest.mark.parametrize("src,func,label", _CALLBACKS)
def test_no_callback_redirects_to_a_dashboard_page(src, func, label):
    """1-3. Every exit — success, denial, malformed state — goes through the
    completion page. A popup that lands on a real page renders it, which is the
    flash itself; and the paths taken BEFORE the state is validated are the easy
    ones to forget."""
    for target in _redirect_targets(src, func):
        assert "/dashboard" not in target, f"{label} still targets the dashboard: {target}"
        assert "completion_url" in target or "_dest(" in target, \
            f"{label} has an exit that bypasses the completion page: {target}"


def test_the_callbacks_agree_on_one_vocabulary():
    """Not three return systems. Square already carried an origin; Google and
    Microsoft now use the same module rather than a second and third scheme."""
    for src, label in ((CAL, "calendar"), (SQ, "square_connect")):
        assert "oauth_return" in src, f"{label} does not use the shared module"


# ── 4-6. the popup, and what the parent may conclude from it ────────────

def test_the_completion_page_closes_when_it_has_an_opener():
    """4. Only the browser knows whether this window was opened by us."""
    body = _strip_comments(COMPLETE)
    assert "window.opener" in body
    assert "window.close()" in body


def test_the_completion_page_loads_no_dashboard():
    """4. It is deliberately not under /dashboard, and pulls in none of it."""
    body = _strip_comments(COMPLETE)
    for smell in ("authedFetch", "supabase", "Sidebar", "db-root", "useParams"):
        assert smell not in body, f"the completion page pulls in {smell}"


def test_the_parent_refetches_setup_state():
    """5. Durable server state is authoritative for what happens next."""
    body = _strip_comments(CC)
    assert "setup-state" in body


def test_the_parent_never_infers_success_from_a_closed_popup():
    """6. A closed window means the interaction ended, not that it worked.

    The ORDER is the property: the server is asked first, and only a server that
    says no AND a window that is gone ends the wait.
    """
    body = _strip_comments(CC)
    start = body.index("const tick = useCallback")
    tick = body[start:body.index("}, [poll, clearTimers])", start)]
    assert tick.index("await poll()") < tick.index("closed"), \
        "the closed check must not short-circuit the server check"
    assert "finish()" not in tick, "only a confirmed connection may finish"


# ── 7-9. denial keeps the customer on the step ──────────────────────────

@pytest.mark.parametrize("provider", ["square", "google", "microsoft"])
def test_a_denied_authorisation_is_reported_as_retryable(provider):
    """7-9. Denial returns status=error, the popup closes, the server still says
    not connected — so the step stays and offers another go."""
    url = R.completion_url(FRONT, origin=R.ONBOARDING, tenant_id=TENANT,
                           provider=provider, status="error")
    assert "status=error" in url
    body = _strip_comments(CC)
    assert "Please try again" in body, "no retryable message on the step"
    assert "advance(" not in body, "the step must not advance itself"


def test_no_provider_payload_reaches_the_customer():
    """The completion page is told a word, never a provider body."""
    url = R.completion_url(FRONT, origin=R.ONBOARDING, tenant_id=TENANT,
                           provider="google", status="invalid_grant: bad thing")
    assert "invalid_grant" not in url
    assert "status=error" in url


# ── 10-11. the same-tab fallback preserves where it started ─────────────

def test_same_tab_onboarding_returns_to_onboarding():
    """10. A blocked popup completes in this tab. "No opener, go to dashboard"
    would strand a customer mid-signup on a page they did not ask for."""
    assert R.page_for(FRONT, R.ONBOARDING, TENANT) == f"{FRONT}/onboarding"


def test_same_tab_dashboard_returns_to_the_dashboard_page_it_started_on():
    """11. And the right one of them: Square's deposit flow starts on payments."""
    assert R.page_for(FRONT, R.CALENDAR, TENANT) == f"{FRONT}/dashboard/{TENANT}/calendar"
    assert R.page_for(FRONT, R.PAYMENTS, TENANT) == f"{FRONT}/dashboard/{TENANT}/payments"


def test_the_two_vocabularies_match():
    """The page builds the same destinations the server names. Two lists that
    drift produce a redirect loop or a 404, neither of which is visible here."""
    fe = set(re.findall(r"'(onboarding|calendar|payments)'",
                        COMPLETE[COMPLETE.index("const ORIGINS"):
                                 COMPLETE.index("type Origin")]))
    assert fe == set(R.ORIGINS), f"frontend {fe} vs backend {set(R.ORIGINS)}"


# ── 12-13. the context is a word, never a URL ───────────────────────────

@pytest.mark.parametrize("bad", [
    "", None, "dashboard", "DASHBOARD", "../evil", "onboarding/../../x",
    "https://evil.example", "//evil.example", "\\\\evil.example", "%2e%2e%2f",
    "onboarding\nx", "javascript:alert(1)", "calendar?x=1", 12345,
])
def test_an_unknown_context_defaults_instead_of_being_obeyed(bad):
    """12. Rejecting would strand a customer whose round trip got mangled; the
    default is where they were already going."""
    assert R.normalize(bad) in R.ORIGINS


@pytest.mark.parametrize("bad", [
    "https://evil.example", "//evil.example", "http://evil.example/x",
    "javascript:alert(1)", "../../evil", "%2f%2fevil.example", "onboarding@evil",
])
def test_an_external_return_url_is_unreachable(bad):
    """13. There is no parameter anywhere that can express a host or a scheme."""
    for fn in (lambda v: R.page_for(FRONT, v, TENANT),
               lambda v: R.completion_url(FRONT, origin=v, tenant_id=TENANT,
                                          provider="google", status="connected")):
        got = fn(bad)
        assert urlparse(got).netloc == urlparse(FRONT).netloc, got
        assert "evil.example" not in got
        assert "javascript:" not in got


def test_a_malformed_tenant_cannot_be_injected_into_a_path():
    """The tenant comes from the validated nonce, but it is still interpolated
    into a path, so it is checked before it gets there."""
    for bad in ("../../evil", "a/b", "x?y", "", "a b"):
        got = R.page_for(FRONT, R.CALENDAR, bad)
        assert got == f"{FRONT}/", got


def test_the_identity_never_comes_from_the_context():
    """The context rides beside the nonce; the tenant comes only from the nonce
    the store validates. Parsed: consume_state must be given the decoded nonce."""
    tree = ast.parse(CAL)
    for fn in ("calendar_callback", "microsoft_callback"):
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == fn)
        src = ast.unparse(node)
        assert "oauth_return.decode_state(state)" in src
        assert "consume_state(nonce" in src, f"{fn} does not validate the decoded nonce"


def test_a_state_without_a_context_still_works():
    """A round trip that began before this shipped must not break in flight."""
    nonce, origin = R.decode_state("justanonce")
    assert nonce == "justanonce" and origin == R.DEFAULT_ORIGIN


def test_the_nonce_survives_encoding_exactly():
    """It is what proves the round trip; a mangled one fails every connection."""
    for n in ("abc123", "a-b_c", "x" * 43):
        for o in R.ORIGINS:
            assert R.decode_state(R.encode_state(n, o)) == (n, o)


# ── 14. resume after the round trip ─────────────────────────────────────

def test_a_hard_refresh_after_oauth_resumes_from_durable_state():
    """14. The same-tab return lands on /onboarding with no stage in the URL, so
    the wizard's resume asks the server where the customer belongs."""
    assert R.page_for(FRONT, R.ONBOARDING, TENANT).endswith("/onboarding")
    assert "?stage=" not in R.page_for(FRONT, R.ONBOARDING, TENANT)
    body = _strip_comments(ONB)
    assert "setup-state" in body and "STAGE_FOR(st.next_stage)" in body
