"""W9G — the regulatory state machine is the only thing that may move a profile.

Three callers mutate profile state: the onboarding routes, the status callback, and
the reconciliation sweep. If each decided legality for itself, a late callback could
drag an approved profile back into review. These tests pin the graph.
"""
import pytest

from services import regulatory_state as st


# ── the graph ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("current,target", [
    (st.NOT_STARTED, st.DETAILS_REQUIRED),
    (st.DETAILS_REQUIRED, st.READY_TO_SUBMIT),
    (st.READY_TO_SUBMIT, st.SUBMITTING),
    (st.SUBMITTING, st.PENDING_REVIEW),
    (st.PENDING_REVIEW, st.APPROVED),
    (st.PENDING_REVIEW, st.REJECTED),
    (st.PENDING_REVIEW, st.MORE_INFORMATION_REQUIRED),
    (st.MORE_INFORMATION_REQUIRED, st.READY_TO_SUBMIT),
    (st.APPROVED, st.NUMBER_PROVISIONING),
    (st.NUMBER_PROVISIONING, st.ACTIVE),
    (st.REJECTED, st.DETAILS_REQUIRED),
    (st.FAILED, st.DETAILS_REQUIRED),
])
def test_legal_transitions_are_applied(current, target):
    assert st.transition(current, target) == (st.APPLIED, "")


@pytest.mark.parametrize("current,target", [
    (st.APPROVED, st.PENDING_REVIEW),      # the one that matters most
    (st.ACTIVE, st.PENDING_REVIEW),
    (st.NOT_STARTED, st.APPROVED),
    (st.NOT_STARTED, st.PENDING_REVIEW),
    (st.DETAILS_REQUIRED, st.APPROVED),
    (st.READY_TO_SUBMIT, st.APPROVED),
    (st.REJECTED, st.APPROVED),
    (st.ACTIVE, st.APPROVED),
])
def test_illegal_transitions_are_refused(current, target):
    outcome, reason = st.transition(current, target)
    assert outcome == st.ILLEGAL
    assert reason == f"{current}->{target}"


def test_an_approved_profile_can_never_walk_back_into_review():
    """A late or replayed callback must not undo an approval."""
    for target in (st.PENDING_REVIEW, st.SUBMITTING, st.READY_TO_SUBMIT,
                   st.DETAILS_REQUIRED, st.MORE_INFORMATION_REQUIRED):
        assert st.transition(st.APPROVED, target)[0] == st.ILLEGAL


def test_reentering_the_same_state_is_idempotent_not_an_error():
    """A redelivered callback asks for the state we are already in. Refusing would
    make Twilio retry forever."""
    for state in st.ALL_STATES:
        assert st.transition(state, state) == (st.NO_CHANGE, "already_in_state")


def test_unknown_states_are_refused_not_guessed():
    assert st.transition("nonsense", st.APPROVED)[0] == st.ILLEGAL
    assert st.transition(st.PENDING_REVIEW, "nonsense")[0] == st.ILLEGAL
    assert st.transition("", "")[0] == st.ILLEGAL


def test_failed_requires_an_explicit_retry_path():
    """FAILED does not silently resume mid-workflow; it re-enters collection."""
    assert st.ALLOWED[st.FAILED] == (st.DETAILS_REQUIRED,)
    for target in (st.READY_TO_SUBMIT, st.SUBMITTING, st.PENDING_REVIEW, st.APPROVED):
        assert st.transition(st.FAILED, target)[0] == st.ILLEGAL


def test_every_state_can_reach_failed_except_terminal_ones():
    for state in st.ALL_STATES:
        if state == st.FAILED:
            continue
        assert st.FAILED in st.ALLOWED[state], state


def test_the_graph_references_only_known_states():
    for source, targets in st.ALLOWED.items():
        assert source in st.ALL_STATES
        for t in targets:
            assert t in st.ALL_STATES, f"{source}->{t}"


def test_every_state_appears_in_the_graph():
    assert set(st.ALLOWED) == set(st.ALL_STATES)


# ── provider status mapping ────────────────────────────────────────────────

@pytest.mark.parametrize("provider,expected", [
    ("draft", st.DETAILS_REQUIRED),
    ("pending-review", st.PENDING_REVIEW),
    ("in-review", st.PENDING_REVIEW),
    ("twilio-approved", st.APPROVED),
    ("twilio-rejected", st.REJECTED),
])
def test_provider_statuses_map_as_documented(provider, expected):
    assert st.state_for_provider_status(provider)[0] == expected


def test_provisionally_approved_does_NOT_become_approved():
    """The SDK has the enum; Twilio's documented status table does not list it; and a
    W9C purchase rejection read "status is not twilio-approved". Treating it as
    approved on the strength of its name would invent provider semantics."""
    state, note = st.state_for_provider_status("provisionally-approved")
    assert state == st.PENDING_REVIEW
    assert state != st.APPROVED
    assert "not treated as approved" in note


def test_an_unknown_future_provider_status_maps_to_nothing():
    """A status Twilio adds later must not cause a destructive transition."""
    for value in ("brand-new-status", "twilio-pending-something", "APPROVED?"):
        state, note = st.state_for_provider_status(value)
        assert state is None
        assert note.startswith("unknown_provider_status:")


def test_an_empty_provider_status_maps_to_nothing():
    assert st.state_for_provider_status("")[0] is None
    assert st.state_for_provider_status(None)[0] is None


def test_provider_status_matching_is_case_and_space_insensitive():
    assert st.state_for_provider_status("  TWILIO-APPROVED  ")[0] == st.APPROVED


def test_only_twilio_approved_maps_to_approved():
    """Guards the mutation where another status is quietly promoted."""
    approving = [k for k, v in st.PROVIDER_STATUS_MAP.items() if v == st.APPROVED]
    assert approving == ["twilio-approved"]


# ── terminal / nonterminal sets ────────────────────────────────────────────

def test_terminal_states_are_not_polled():
    assert set(st.TERMINAL_STATES) == {st.APPROVED, st.REJECTED, st.ACTIVE}
    for state in st.TERMINAL_STATES:
        assert st.is_terminal(state)
        assert state not in st.NONTERMINAL_STATES


def test_nonterminal_states_are_the_ones_worth_reconciling():
    assert set(st.NONTERMINAL_STATES) == {st.SUBMITTING, st.PENDING_REVIEW,
                                         st.MORE_INFORMATION_REQUIRED,
                                         st.NUMBER_PROVISIONING}
    for state in st.NONTERMINAL_STATES:
        assert not st.is_terminal(state)
