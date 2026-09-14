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


#: Where the wizard sends a tenant the moment provisioning returns.
_AFTER_PROVISION = ONB[ONB.index("setItem('ol_onboarding_tenant'"):][:700]


def test_a_fresh_tenant_is_routed_by_the_server_not_by_its_country():
    """This branch used to read onboarding_state itself and pick a stage, which
    is a second derivation of an answer the server already owns — and it drifted:
    the unregulated side jumped to notifications, skipping the calendar step
    setup-state would bounce them back to on the next refresh."""
    assert "advance(" in _AFTER_PROVISION


def test_the_wizard_reads_the_state_rather_than_deciding_it():
    """Server-authoritative: no country test decides the stage."""
    for smell in ("'IE'", '"IE"', "+353", "country ===", "country =="):
        assert smell not in _AFTER_PROVISION, smell


def test_no_premature_account_ready_for_a_regulated_tenant():
    """The old flow declared success before the customer could get a number."""
    assert "Your account is ready" not in _AFTER_PROVISION
    assert "setStage('done')" not in _AFTER_PROVISION


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
    i = ONB.index("getItem('ol_onboarding_tenant')")
    assert "getSession" in ONB[i:i + 500]


def test_a_completed_tenant_stops_being_resumed():
    """Resume ends on exactly one condition: a live permanent number.

    Anchored on the clear that follows the resume path's own READ, not on the
    first textual match. Two other sites now clear the same key -- an explicit
    ?new=1 and the "start a new setup" button -- and both sit earlier in the
    file, so a bare index() finds one of those and asserts nothing about resume.
    """
    start = ONB.index("getItem('ol_onboarding_tenant')")
    i = ONB.index("removeItem('ol_onboarding_tenant')", start)
    assert "phone?.permanent" in ONB[i - 200:i], "only a live permanent number ends resume"


def test_a_resumed_setup_offers_a_way_out():
    """A resume with no exit is a trap.

    The pointer clears only once a permanent number exists, which for a
    regulated tenant is days away — so every visit to /onboarding, including
    both "Build your own agent" CTAs, silently returned the customer to the
    stage they left, through hard refreshes and all. Resume is right; being
    silent and inescapable was not.
    """
    assert "resumedStage" in ONB, "the wizard must know it resumed, to be able to say so"
    assert "startNewSetup" in ONB, "and must offer a way out of the stage it resumed into"


def test_starting_fresh_reloads_rather_than_resetting_in_place():
    """The card step's onboarding key is captured once per mount, and that key
    binds a Stripe Customer and claims a tenant. Resetting state in place would
    carry this attempt's key into the next one and mint a duplicate; only a
    reload past a cleared sessionStorage guarantees a fresh one."""
    i = ONB.index("function startNewSetup")
    body = ONB[i:i + 800]
    assert "removeItem('ol_onboarding_key')" in body, "a new attempt needs its own key"
    assert "location.href" in body, "must reload, not reset in place"


def test_the_status_endpoint_is_tenant_authenticated():
    import inspect
    for fn in (onboarding.onboarding_status, onboarding.setup_state):
        assert "verify_tenant_owner" in inspect.getsource(fn)


def test_resume_is_best_effort_and_cannot_break_the_wizard():
    i = ONB.index("getItem('ol_onboarding_tenant')")
    assert "catch" in ONB[i:i + 1200]


# ═══ 4. the UX corrections ══════════════════════════════════════════════

def test_the_review_row_no_longer_claims_email_was_chosen():
    assert "Choose during setup" in ONB
    assert "Emailed to ${form.email}" not in ONB


def test_the_business_email_helper_is_just_a_login_hint():
    assert "Your dashboard login email." in ONB
    assert "also email your call summaries here" not in ONB


#: The toggle moved out of this page into one component every password input
#: shares — login, reset-password and settings each had a bare field, so the
#: eye existed on exactly one of the seven places a password is typed.
PWFIELD = (FE / "components" / "PasswordField.tsx").read_text()


def test_the_password_field_is_hidden_by_default_and_toggleable():
    assert "useState(false)" in PWFIELD, "revealed must default to hidden"
    assert "shown ? 'text' : 'password'" in PWFIELD


def test_the_wizard_uses_the_shared_password_field():
    """Rather than keeping a second copy that can drift from the other six."""
    assert "PasswordField" in ONB
    assert "pw-toggle" not in ONB, "the wizard grew its own toggle again"


def test_the_password_toggle_is_accessible_and_never_submits():
    i = PWFIELD.index("pw-toggle")
    window = PWFIELD[i - 300:i + 800]
    assert 'type="button"' in window, "it would submit the form it sits in"
    assert "'Hide password' : 'Show password'" in window
    assert "aria-pressed" in window


def test_the_toggle_changes_only_the_input_type_not_the_value():
    """Scoped to the button element alone: the input sits directly above it and
    legitimately carries the onChange this asserts the BUTTON never has."""
    i = PWFIELD.index('<button type="button" className="pw-toggle"')
    button = PWFIELD[i:PWFIELD.index("</button>", i)]
    assert "setShown(v => !v)" in button
    assert "onChange" not in button, "the toggle must not touch the password value"
    assert "value" not in button, "the toggle must not read or write the value"


def test_the_preferences_primary_action_renders_as_a_button():
    """It was styled with the wizard's class, which does not exist in Settings —
    so it appeared as plain text on one of the two surfaces."""
    assert "np-primary" in PREFS
    assert 'className="btn-primary"' not in PREFS
    css = (FE / "app" / "globals.css").read_text()
    assert ".np-primary" in css


def test_the_primary_action_says_save_and_continue():
    assert "Save and continue" in PREFS or "Save and continue" in ONB


def test_deferring_saves_only_its_own_onboarding_stamp():
    """'I'll decide later' must not enable Email or stamp an explicit
    preference — a deferred customer stays legacy until they answer."""
    import re as _re
    i = ONB.index("declineStep(String(result.tenant_id), 'notifications')")
    window = ONB[i - 700:i + 300]
    # Strip the JSX comment first: it EXPLAINS that nothing is stamped, and
    # scanning the prose would flag the explanation as the act.
    code = _re.sub(r"\{/\*.*?\*/\}", "", window, flags=_re.S)
    assert "declineStep" in code
    # It may record the deferral. It may not touch a preference.
    for write in ("PATCH", "email_enabled", "sms_enabled", "whatsapp_enabled",
                  "notification_prefs_set_at", "notification_email"):
        assert write not in code, write


# ═══ 5. Gate B: the reordered tail, driven by the server ════════════════

FINAL = (FE / "components" / "FinalSetup.tsx").read_text()
BANNER = (FE / "app" / "dashboard" / "[tenantId]" / "TrialBanner.tsx").read_text()


def test_the_stage_machine_has_the_reordered_tail():
    m = re.search(r"type Stage =([^\n]+)", ONB)
    for stage in ("'calendar'", "'notifications'", "'verification'", "'finalsetup'", "'done'"):
        assert stage in m.group(1), stage
    order = [m.group(1).index(x) for x in
             ("'calendar'", "'notifications'", "'verification'", "'finalsetup'", "'done'")]
    assert order == sorted(order), "stages are declared out of order"


def test_verification_completion_asks_the_server_where_to_go():
    """It used to name 'calendar'. With the filing moved to the end of setup
    that answer is simply wrong, which is the point: no step names its own
    successor, so moving one is a change in the resolver and nowhere else."""
    i = ONB.index("onReady={")
    window = ONB[i:i + 200]
    assert "advance(" in window
    for smell in ("setStage('calendar')", "setStage('notifications')", "setStage('done')"):
        assert smell not in window, smell


def test_calendar_skip_records_the_answer_instead_of_forcing_a_stage():
    """Gate B.1: forcing 'notifications' here lost the answer on refresh."""
    i = ONB.index("declineStep(String(result.tenant_id), 'booking')")
    window = ONB[i - 300:i + 400]
    assert "declineStep" in window
    assert "setStage('notifications')" not in window


def test_notifications_completion_cannot_skip_an_unfinished_filing():
    """Hardcoding 'finalsetup' here would send a regulated tenant straight to
    provisioning and try to buy a +353 no regulator has authorised."""
    i = ONB.index("onSaved={")
    window = ONB[i:i + 400]
    assert "advance(" in window
    assert "setStage('finalsetup')" not in window


def test_deferring_notifications_records_the_answer_instead_of_forcing_a_stage():
    i = ONB.index("declineStep(String(result.tenant_id), 'notifications')")
    window = ONB[i - 300:i + 400]
    assert "declineStep" in window
    assert "setStage('finalsetup')" not in window


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
    # The FIRST filing is now the last step before provisioning, so an untouched
    # regulated tenant starts at the calendar like everyone else.
    (dict(needs_reg=True, reg_done=False, reg_blocked=False, integration_connected=False,
          notifications_set=False, permanent=False, temporary=False), "calendar"),
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


def test_the_first_filing_is_the_last_step_before_provisioning():
    """Verification sits after the calendar and notification steps and before
    final setup, so a customer completes everything they CAN before being asked
    for a CRO number, a named representative and a registered address."""
    base = dict(needs_reg=True, reg_done=False, reg_blocked=False,
                permanent=False, temporary=False)
    assert onboarding._next_setup_stage(
        **base, integration_connected=False, notifications_set=False) == "calendar"
    assert onboarding._next_setup_stage(
        **base, integration_connected=True, notifications_set=False) == "notifications"
    assert onboarding._next_setup_stage(
        **base, integration_connected=True, notifications_set=True) == "verification"


def test_a_declined_calendar_and_notifications_still_reach_verification():
    """Skip and defer are answers, so they advance — to the filing, not past it.
    Reaching final_setup here would try to provision a regulated number that no
    regulator has authorised."""
    assert onboarding._next_setup_stage(
        needs_reg=True, reg_done=False, reg_blocked=False,
        integration_connected=False, notifications_set=False,
        booking_skipped=True, notifications_deferred=True,
        permanent=False, temporary=False) == "verification"


def test_provisioning_is_never_reached_with_an_unfinished_filing():
    """The one ordering constraint that is actually regulatory."""
    for connected in (True, False):
        for notified in (True, False):
            for skipped in (True, False):
                for deferred in (True, False):
                    stage = onboarding._next_setup_stage(
                        needs_reg=True, reg_done=False, reg_blocked=False,
                        integration_connected=connected, notifications_set=notified,
                        booking_skipped=skipped, notifications_deferred=deferred,
                        permanent=False, temporary=False)
                    assert stage != "final_setup", (connected, notified, skipped, deferred)


def test_an_unregulated_tenant_is_unaffected_by_the_move():
    assert onboarding._next_setup_stage(
        needs_reg=False, reg_done=False, reg_blocked=False,
        integration_connected=True, notifications_set=True,
        permanent=False, temporary=False) == "final_setup"


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


# ═══ 6. Gate B.1: "asked and declined" is not "never asked" ═════════════
# The resolver read only positive signals -- a connected integration, a set
# preference. Both are absences otherwise, and an absence cannot say whether the
# customer was never offered the step or offered it and said no. So someone who
# skipped the calendar was sent back to it on every refresh.

BASE = dict(needs_reg=True, reg_done=True, reg_blocked=False,
            permanent=False, temporary=False)


def _stage(**over):
    return onboarding._next_setup_stage(**{
        **BASE, "integration_connected": False, "notifications_set": False,
        "booking_skipped": False, "notifications_deferred": False, **over})


# ── calendar ────────────────────────────────────────────────────────────

def test_calendar_unanswered_still_returns_calendar():
    assert _stage() == "calendar"


@pytest.mark.parametrize("field", ["google_refresh_token", "microsoft_refresh_token",
                                   "square_access_token"])
def test_any_connected_provider_completes_the_calendar_step(field):
    """The three tokens setup_state reads, each on its own."""
    import inspect
    src = inspect.getsource(onboarding.setup_state)
    assert field in src
    assert _stage(integration_connected=True) != "calendar"


def test_an_explicit_skip_completes_the_calendar_step():
    assert _stage(booking_skipped=True) == "notifications"


def test_a_skip_survives_a_refresh():
    """The defect: identical inputs but for the stamp, and the stamp is what
    stops the customer being asked again."""
    assert _stage(booking_skipped=False) == "calendar"
    assert _stage(booking_skipped=True) != "calendar"


def test_a_skipped_then_connected_tenant_stays_complete():
    """Positive state wins on its own -- nothing has to be unwound."""
    assert _stage(booking_skipped=True, integration_connected=True) != "calendar"


# ── notifications ───────────────────────────────────────────────────────

def test_notifications_unanswered_still_returns_notifications():
    assert _stage(integration_connected=True) == "notifications"


def test_explicit_preferences_complete_the_step():
    assert _stage(integration_connected=True, notifications_set=True) != "notifications"


def test_an_explicit_defer_completes_the_step():
    assert _stage(integration_connected=True, notifications_deferred=True) == "final_setup"


def test_a_defer_survives_a_refresh():
    assert _stage(integration_connected=True, notifications_deferred=False) == "notifications"
    assert _stage(integration_connected=True, notifications_deferred=True) != "notifications"


def test_a_deferred_then_configured_tenant_stays_complete():
    assert _stage(integration_connected=True, notifications_set=True,
                  notifications_deferred=True) != "notifications"


# ── combined, and priority preserved ────────────────────────────────────

def test_skip_plus_defer_reaches_final_setup():
    assert _stage(booking_skipped=True, notifications_deferred=True) == "final_setup"


def test_skip_plus_defer_does_not_bounce_back_to_calendar():
    """Before the fix this returned 'calendar' -- two steps backwards."""
    assert _stage(booking_skipped=True, notifications_deferred=True) != "calendar"


def test_a_blocked_filing_still_outranks_both_declines():
    assert onboarding._next_setup_stage(
        **{**BASE, "reg_blocked": True, "integration_connected": True,
           "notifications_set": True, "booking_skipped": True,
           "notifications_deferred": True}) == "verification"


def test_a_permanent_number_still_wins_over_everything():
    assert onboarding._next_setup_stage(
        **{**BASE, "permanent": True, "reg_blocked": True,
           "integration_connected": False, "notifications_set": False,
           "booking_skipped": False, "notifications_deferred": False}) == "ready"


def test_a_temporary_number_still_ranks_after_the_setup_steps():
    assert _stage(temporary=True) == "calendar"
    assert _stage(temporary=True, booking_skipped=True,
                  notifications_deferred=True) == "ready"


# ── the endpoint ────────────────────────────────────────────────────────

def test_only_the_two_declinable_steps_are_addressable():
    assert set(onboarding._DECLINABLE_STEPS) == {"booking", "notifications"}
    assert onboarding._DECLINABLE_STEPS["booking"] == "booking_setup_skipped_at"
    assert onboarding._DECLINABLE_STEPS["notifications"] == "notification_prefs_deferred_at"


def test_the_decline_endpoint_is_tenant_authenticated():
    import inspect
    assert "verify_tenant_owner" in inspect.getsource(onboarding.decline_setup_step)


def test_the_timestamp_is_server_written_and_idempotent():
    import inspect
    src = inspect.getsource(onboarding.decline_setup_step)
    assert "_dt.now(_tz.utc)" in src           # the server decides the time
    assert '.is_(column, "null")' in src       # and only when it is absent


def test_a_caller_cannot_supply_a_time_or_a_column():
    """The path names a STEP; the column is looked up server-side from a fixed
    map, so there is no field in which a value or a column name could travel."""
    import inspect
    sig = inspect.signature(onboarding.decline_setup_step)
    assert set(sig.parameters) == {"tenant_id", "step", "authorization"}
    src = inspect.getsource(onboarding.decline_setup_step)
    assert "_DECLINABLE_STEPS.get(step)" in src


def test_declining_writes_nothing_but_its_own_column():
    import ast, inspect, textwrap
    fn = ast.parse(textwrap.dedent(
        inspect.getsource(onboarding.decline_setup_step))).body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)
    for forbidden in ("notification_prefs_set_at", "email_enabled", "sms_enabled",
                      "whatsapp_enabled", "notification_email", "sms_alert_number",
                      "whatsapp_alert_number", "subscription", "trial"):
        assert forbidden not in code, forbidden


# ── the dispatcher must never see the defer stamp ───────────────────────

def test_the_notification_dispatcher_never_reads_the_defer_stamp():
    """An ONBOARDING fact only. If delivery ever consulted it, deferring would
    silently change what a tenant receives."""
    import inspect
    from services import notification_channels as nch
    from services import webhook_processor as wp
    for mod in (nch, wp):
        assert "notification_prefs_deferred_at" not in inspect.getsource(mod), mod.__name__


def test_deferring_leaves_a_tenant_in_legacy_dispatch_semantics():
    from services import notification_channels as nch
    deferred = {"id": "t", "notification_prefs_deferred_at": "2026-09-13T12:00:00+00:00",
                "notification_email": "owner@acme.com", "whatsapp_enabled": True,
                "sms_alert_number": "+14165551111"}
    p = nch.preferences(deferred)
    assert p["semantics"] == "legacy"
    assert p["dashboard_only"] is False
    # ...and the legacy destinations still resolve exactly as before
    assert p["channels"][nch.WHATSAPP]["destination"] == "+14165551111"


def test_deferring_does_not_enable_email():
    from services import notification_channels as nch
    a = nch.preferences({"id": "t", "email_enabled": False, "notification_email": ""})
    b = nch.preferences({"id": "t", "email_enabled": False, "notification_email": "",
                         "notification_prefs_deferred_at": "2026-09-13T12:00:00+00:00"})
    assert a["channels"][nch.EMAIL] == b["channels"][nch.EMAIL]


# ── historical compatibility ────────────────────────────────────────────

def test_historical_tenants_are_null_on_both_and_unaffected():
    """No backfill: an existing tenant with a connected calendar and legacy
    notifications is still complete on the strength of its positive state."""
    assert _stage(integration_connected=True, notifications_set=True) == "final_setup"
    assert onboarding._next_setup_stage(
        **{**BASE, "needs_reg": False, "integration_connected": True,
           "notifications_set": True, "booking_skipped": False,
           "notifications_deferred": False, "permanent": True}) == "ready"


# ── the wiring ──────────────────────────────────────────────────────────

def test_both_declines_call_the_durable_endpoint():
    assert "decline-step" in ONB
    assert "declineStep(String(result.tenant_id), 'booking')" in ONB
    assert "declineStep(String(result.tenant_id), 'notifications')" in ONB


def test_the_wizard_obeys_the_returned_stage_rather_than_forcing_one():
    i = ONB.index("const declineStep")
    window = ONB[i:i + 700]
    assert "STAGE_FOR(st.next_stage)" in window
    for forced in ("setStage('notifications')", "setStage('finalsetup')"):
        assert forced not in window, forced


def test_a_failed_decline_does_not_advance():
    """Advancing on failure would lose the answer at the next refresh."""
    i = ONB.index("declineStep(String(result.tenant_id), 'booking')")
    window = ONB[i:i + 400]
    assert "catch" in window and "setDeclineError" in window
    assert "setStage(" not in window
