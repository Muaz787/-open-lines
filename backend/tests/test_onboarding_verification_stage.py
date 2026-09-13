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
    assert "/onboarding/setup-state/" in ONB
    assert "STAGE_FOR(st.next_stage)" in ONB


def test_local_storage_carries_only_a_pointer_never_a_decision():
    """The tenant id is remembered; the STAGE is always asked of the server."""
    assert "ol_onboarding_tenant" in ONB
    i = ONB.index("ol_onboarding_tenant")
    for smell in ("setItem('ol_onboarding_stage'", "getItem('ol_onboarding_stage'"):
        assert smell not in ONB, smell


def test_resume_requires_a_session():
    i = ONB.index("STAGE_FOR(st.next_stage)")
    assert "getSession" in ONB[i - 900:i]


def test_a_completed_tenant_stops_being_resumed():
    i = ONB.index("STAGE_FOR(st.next_stage)")
    window = ONB[i:i + 400]
    assert "removeItem('ol_onboarding_tenant')" in window
    assert "phone?.permanent" in window, "only a live permanent number ends resume"


def test_the_status_endpoint_is_tenant_authenticated():
    import inspect
    for fn in (onboarding.onboarding_status, onboarding.setup_state):
        assert "verify_tenant_owner" in inspect.getsource(fn)


def test_resume_is_best_effort_and_cannot_break_the_wizard():
    i = ONB.index("STAGE_FOR(st.next_stage)")
    assert "catch" in ONB[i:i + 500]


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
    assert "setStage('finalsetup')" in code
    for write in ("authedFetch", "PATCH", "email_enabled", "notification_prefs_set_at"):
        assert write not in code, write


# ═══ 5. Gate B: the reordered tail, driven by the server ════════════════

FINAL = (FE / "components" / "FinalSetup.tsx").read_text()
BANNER = (FE / "app" / "dashboard" / "[tenantId]" / "TrialBanner.tsx").read_text()


def test_the_stage_machine_has_the_reordered_tail():
    m = re.search(r"type Stage =([^\n]+)", ONB)
    for stage in ("'verification'", "'calendar'", "'notifications'", "'finalsetup'", "'done'"):
        assert stage in m.group(1), stage
    order = [m.group(1).index(x) for x in
             ("'verification'", "'calendar'", "'notifications'", "'finalsetup'", "'done'")]
    assert order == sorted(order), "stages are declared out of order"


def test_verification_continues_into_calendar():
    assert "setStage('calendar')" in ONB


def test_calendar_continues_into_notifications():
    i = ONB.index("Skip for now")
    assert "setStage('notifications')" in ONB[i - 500:i + 200]


def test_notifications_continue_into_final_setup():
    assert "onSaved={() => setStage('finalsetup')}" in ONB


def test_deferring_notifications_still_reaches_final_setup():
    i = ONB.index("I&apos;ll decide later")
    assert "setStage('finalsetup')" in ONB[i - 400:i + 200]


def test_the_wizard_obeys_the_server_stage_rather_than_deriving_it():
    assert "/onboarding/setup-state/" in ONB
    assert "STAGE_FOR(st.next_stage)" in ONB


def test_the_stage_map_covers_every_server_stage():
    import inspect
    src = inspect.getsource(onboarding._next_setup_stage)
    returned = set(re.findall(r"return '([a-z_]+)'", src)) | set(
        re.findall(r'return "([a-z_]+)"', src))
    for stage in returned:
        assert f"{stage}:" in ONB, f"the wizard cannot render server stage {stage!r}"


# ── the server decides the order, and nothing else does ─────────────────

@pytest.mark.parametrize("kw,expected", [
    (dict(needs_reg=True, reg_done=False, reg_blocked=False, integration_connected=False,
          notifications_set=False, permanent=False, temporary=False), "verification"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=True, integration_connected=True,
          notifications_set=True, permanent=False, temporary=True), "verification"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=False, integration_connected=False,
          notifications_set=False, permanent=False, temporary=False), "calendar"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=False, integration_connected=True,
          notifications_set=False, permanent=False, temporary=False), "notifications"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=False, integration_connected=True,
          notifications_set=True, permanent=False, temporary=False), "final_setup"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=False, integration_connected=True,
          notifications_set=True, permanent=False, temporary=True), "ready"),
    (dict(needs_reg=True, reg_done=True, reg_blocked=False, integration_connected=True,
          notifications_set=True, permanent=True, temporary=True), "ready"),
    # a non-regulated tenant never sees verification
    (dict(needs_reg=False, reg_done=True, reg_blocked=False, integration_connected=False,
          notifications_set=False, permanent=False, temporary=False), "calendar"),
])
def test_the_resume_mapping(kw, expected):
    assert onboarding._next_setup_stage(**kw) == expected


def test_a_live_permanent_number_ends_setup_whatever_else_is_unfinished():
    assert onboarding._next_setup_stage(
        needs_reg=True, reg_done=False, reg_blocked=True, integration_connected=False,
        notifications_set=False, permanent=True, temporary=False) == "ready"


def test_a_blocked_filing_outranks_everything_downstream():
    assert onboarding._next_setup_stage(
        needs_reg=True, reg_done=True, reg_blocked=True, integration_connected=True,
        notifications_set=True, permanent=False, temporary=True) == "verification"


# ── final setup orchestrates, it does not decide ────────────────────────

def test_finalize_is_a_wake_up_over_the_existing_lifecycle():
    import inspect
    src = inspect.getsource(onboarding.finalize_setup)
    assert "ireland_lifecycle.wake" in src
    for owns in ("ensure_temporary_number", "ensure_permanent_irish_number",
                 "create_trial_subscription", "purchase"):
        assert owns not in src, owns


def test_finalize_is_tenant_authenticated():
    import inspect
    for fn in (onboarding.finalize_setup, onboarding.setup_state):
        assert "verify_tenant_owner" in inspect.getsource(fn)


def test_finalize_returns_no_provider_internals():
    import ast, inspect, textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(onboarding.finalize_setup))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]      # the docstring may describe what is withheld
    code = ast.unparse(fn).lower()
    for leak in ("bundle", "outcome", "provider_attempt", "reason"):
        assert leak not in code, leak


def test_the_customer_cannot_choose_temporary_or_permanent():
    i = FINAL.index("/onboarding/finalize/")
    request = FINAL[i:i + 200]
    assert "method: 'POST'" in request
    # No body at all: there is no field in which a preference could travel.
    for choice in ("body:", "purpose", "permanent", "temporary"):
        assert choice not in request, choice


def test_final_setup_runs_once_not_on_every_render():
    assert "started.current" in FINAL


def test_a_blocked_filing_sends_the_customer_back_to_verification():
    assert "regulatory?.blocked" in FINAL and "onBlocked" in FINAL


def test_final_setup_never_shows_a_provider_error():
    i = FINAL.index("} catch {")
    window = FINAL[i:FINAL.index("} finally {", i)]
    assert "couldn" in window and "finish setting up" in window
    # The property is that nothing from the provider is INTERPOLATED into what
    # the customer reads -- not that the word "detail" never appears, which it
    # legitimately does in "Your details are saved".
    for leak in ("err.message", "e.message", "String(e)", "${", "d.detail",
                 "res.statusText", "JSON.stringify"):
        assert leak not in window, leak


# ── the two ready screens ───────────────────────────────────────────────

def test_the_permanent_ready_screen_shows_the_number_and_the_trial():
    assert "Your AI receptionist is ready" in ONB
    i = ONB.index("Your AI receptionist is ready")
    window = ONB[i:i + 1400]
    assert "setup.phone.permanent" in window
    assert "free trial" in window


def test_the_temporary_ready_screen_never_claims_the_trial_started():
    assert "Your test line is ready" in ONB
    i = ONB.index("Your test line is ready")
    window = ONB[i:i + 1800]
    assert "temporary_test" in window
    assert "Temporary test number" in window
    assert "hasn&apos;t started yet" in window
    assert "Not your business number" in window


def test_the_ready_variant_is_chosen_by_what_the_tenant_has():
    """Not by country, and not by how they arrived."""
    i = ONB.index("key=\"ready-permanent\"")
    window = ONB[i - 300:i]
    assert "setup?.phone?.permanent" in window
    j = ONB.index("key=\"ready-temporary\"")
    twindow = ONB[j - 300:j]
    assert "temporary_test" in twindow
    for smell in ("'IE'", '"IE"', "+353", "country ==="):
        assert smell not in window and smell not in twindow, smell


def test_account_ready_no_longer_appears_for_a_tenant_with_no_number():
    assert "Your account is ready" not in ONB


# ── the dashboard banner ────────────────────────────────────────────────

def test_the_banner_reads_the_server_flag_rather_than_a_date():
    assert "trial_pending_activation" in BANNER
    i = BANNER.index("if (trial.trial_pending_activation)")
    j = BANNER.index("} else if (trial.payment_required)")
    assert i < j, "the pending flag must be checked before the other branches"


def test_the_deferred_banner_says_what_is_actually_true():
    i = BANNER.index("if (trial.trial_pending_activation)")
    window = BANNER[i:i + 600]
    assert "will start when your business number is activated" in window
    assert "ends in" not in window


def test_an_actual_stripe_trial_still_shows_its_end_date():
    assert "trial.card_trial" in BANNER and "fmtDate(trial.trial_ends_at)" in BANNER


def test_the_pending_flag_is_server_decided_and_country_free():
    import ast, inspect, textwrap
    from services import trial as trial_svc
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(trial_svc._trial_pending_activation))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for smell in ('"IE"', "'IE'", "+353"):
        assert smell not in code, smell
    assert "needs_regulatory_clearance" in code


def test_a_tenant_with_a_real_trial_is_not_marked_pending():
    from services import trial as trial_svc
    t = {"business_country_code": "IE", "stripe_trial_ends_at": "2026-09-20T00:00:00+00:00"}
    assert trial_svc._trial_pending_activation(t) is False


def test_a_ca_tenant_is_never_marked_pending():
    from services import trial as trial_svc
    assert trial_svc._trial_pending_activation(
        {"business_country_code": "CA", "twilio_phone_number": ""}) is False


def test_a_regulated_tenant_with_a_live_number_is_not_marked_pending():
    from services import trial as trial_svc
    assert trial_svc._trial_pending_activation(
        {"business_country_code": "IE", "twilio_phone_number": "+353871234567"}) is False


def test_a_regulated_tenant_still_waiting_is_marked_pending():
    from services import trial as trial_svc
    assert trial_svc._trial_pending_activation(
        {"business_country_code": "IE", "twilio_phone_number": None}) is True
