"""Regulatory verification inside the onboarding wizard (Gate A).

WHAT WAS WRONG
A regulated customer was told "Your account is ready" and handed a link that
looked like body text, which took them out of onboarding and into the dashboard
to do the one thing standing between them and a phone number.

WHAT MATTERS MOST HERE
Not the copy — the RESUME. Onboarding now spans account creation, payment and a
regulatory review that takes days, so the wizard's position must come from the
server, never from React state that a refresh discards.

These are contract tests over the frontend and the endpoints it relies on. The
verification logic itself is untouched and is still covered by the W9I-C suites.
"""
import json
import pathlib
import re

import pytest

from routers import onboarding, regulatory_verification

ROOT = pathlib.Path(__file__).resolve().parents[2]
FE = ROOT / "frontend" / "src"
ONB = (FE / "app" / "onboarding" / "page.tsx").read_text()
COMPONENT = (FE / "components" / "BusinessVerification.tsx").read_text()
DASH = (FE / "app" / "dashboard" / "[tenantId]" / "verification" / "page.tsx").read_text()
PREFS = (FE / "components" / "NotificationPreferences.tsx").read_text()


# ═══ 1. one implementation, two surfaces ════════════════════════════════

def test_the_dashboard_route_renders_the_shared_component():
    assert "BusinessVerification" in DASH
    assert "@/components/BusinessVerification" in DASH


def test_onboarding_renders_the_same_shared_component():
    assert "@/components/BusinessVerification" in ONB


def test_the_dashboard_route_holds_no_form_of_its_own():
    """A fork would be two regulatory contracts drifting apart."""
    for own in ("<input", "<form", "authedFetch", "saveDetails", "/verification/details"):
        assert own not in DASH, own
    assert len(DASH.splitlines()) < 40, "the wrapper grew a second implementation"


def test_the_component_still_talks_to_the_existing_endpoints():
    assert "/regulatory/${tenantId}/verification" in COMPONENT
    for step in ("/details", "/address", "/review", "/authorize"):
        assert step in COMPONENT or step.strip("/") in COMPONENT, step


# ═══ 2. the new stage ═══════════════════════════════════════════════════

def test_verification_is_a_first_class_onboarding_stage():
    assert "'verification'" in ONB
    m = re.search(r"type Stage =([^\n]+)", ONB)
    assert m and "'verification'" in m.group(1)


def test_a_regulated_tenant_enters_verification_instead_of_done():
    assert "onboarding_state === 'regulatory_required'" in ONB
    i = ONB.index("onboarding_state === 'regulatory_required'")
    assert "setStage('verification')" in ONB[i:i + 300]


def test_the_wizard_reads_the_state_rather_than_deciding_it():
    """Server-authoritative: no country test decides the stage."""
    i = ONB.index("onboarding_state === 'regulatory_required'")
    window = ONB[i - 400:i + 400]
    for smell in ("'IE'", '"IE"', "+353", "country ===", "country =="):
        assert smell not in window, smell


def test_no_premature_account_ready_for_a_regulated_tenant():
    """The old flow declared success before the customer could get a number."""
    i = ONB.index("onboarding_state === 'regulatory_required'")
    assert "Your account is ready" not in ONB[i:i + 400]


# ═══ 3. durable resume — the part that actually matters ═════════════════

def test_the_component_derives_its_step_from_the_server():
    """next_step + the authorisation rows, not React state."""
    assert "next_step" in COMPONENT
    assert "a.authorized" in COMPONENT or "authorizations" in COMPONENT


def test_the_server_still_publishes_the_resume_signal():
    import inspect
    src = inspect.getsource(regulatory_verification)
    assert '"next_step"' in src


def test_onboarding_resumes_from_server_state_not_local_state():
    assert "/onboarding/status/" in ONB
    i = ONB.index("/onboarding/status/")
    window = ONB[i:i + 700]
    assert "onboarding_state === 'regulatory_required'" in window
    assert "setStage('verification')" in window


def test_local_storage_carries_only_a_pointer_never_a_decision():
    """The tenant id is remembered; the STAGE is always asked of the server."""
    assert "ol_onboarding_tenant" in ONB
    i = ONB.index("ol_onboarding_tenant")
    for smell in ("setItem('ol_onboarding_stage'", "getItem('ol_onboarding_stage'"):
        assert smell not in ONB, smell


def test_resume_requires_a_session():
    i = ONB.index("/onboarding/status/")
    assert "getSession" in ONB[i - 500:i]


def test_a_completed_tenant_stops_being_resumed():
    i = ONB.index("/onboarding/status/")
    assert "removeItem('ol_onboarding_tenant')" in ONB[i:i + 800]


def test_the_status_endpoint_is_tenant_authenticated():
    import inspect
    assert "verify_tenant_owner" in inspect.getsource(onboarding.onboarding_status)


def test_resume_is_best_effort_and_cannot_break_the_wizard():
    i = ONB.index("/onboarding/status/")
    assert "catch" in ONB[i:i + 900]


# ═══ 4. the UX corrections ══════════════════════════════════════════════

def test_the_review_row_no_longer_claims_email_was_chosen():
    assert "Choose during setup" in ONB
    assert "Emailed to ${form.email}" not in ONB


def test_the_business_email_helper_is_just_a_login_hint():
    assert "Your dashboard login email." in ONB
    assert "also email your call summaries here" not in ONB


def test_the_password_field_is_hidden_by_default_and_toggleable():
    assert "showPassword ? 'text' : 'password'" in ONB
    assert "useState(false)" in ONB.split("showPassword")[0][-400:] or \
           "const [showPassword, setShowPassword] = useState(false)" in ONB


def test_the_password_toggle_is_accessible_and_never_submits():
    i = ONB.index("pw-toggle")
    window = ONB[i - 300:i + 700]
    assert 'type="button"' in window
    assert "'Hide password' : 'Show password'" in window or \
           "showPassword ? 'Hide password' : 'Show password'" in window
    assert "aria-pressed" in window


def test_the_toggle_changes_only_the_input_type_not_the_value():
    i = ONB.index("pw-toggle")
    window = ONB[i - 400:i + 700]
    assert "setShowPassword(v => !v)" in window
    assert "setForm" not in window, "the toggle must not touch the password value"


def test_the_preferences_primary_action_renders_as_a_button():
    """It was styled with the wizard's class, which does not exist in Settings —
    so it appeared as plain text on one of the two surfaces."""
    assert "np-primary" in PREFS
    assert 'className="btn-primary"' not in PREFS
    css = (FE / "app" / "globals.css").read_text()
    assert ".np-primary" in css


def test_the_primary_action_says_save_and_continue():
    assert "Save and continue" in PREFS or "Save and continue" in ONB


def test_deferring_saves_nothing_at_all():
    """'I'll decide later' must not enable Email or stamp an explicit
    preference — a deferred customer stays legacy until they answer."""
    import re as _re
    i = ONB.index("I&apos;ll decide later")
    window = ONB[i - 700:i + 200]
    # Strip the JSX comment first: it EXPLAINS that nothing is stamped, and
    # scanning the prose would flag the explanation as the act.
    code = _re.sub(r"\{/\*.*?\*/\}", "", window, flags=_re.S)
    assert "setStage('done')" in code
    for write in ("authedFetch", "PATCH", "email_enabled", "notification_prefs_set_at"):
        assert write not in code, write
