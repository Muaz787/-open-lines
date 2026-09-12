"""The single authority for regulatory profile state transitions (W9G).

WHY ONE PLACE. Three callers mutate profile state -- the onboarding routes, the
status callback, and the reconciliation sweep. If each decided for itself what a
legal transition was, a late callback could drag an approved profile back to
pending_review, and a reconciliation replay could undo a submission. Every mutation
goes through `transition()`, and the graph below is the only definition of legality.

IDEMPOTENCE IS A TRANSITION OUTCOME, NOT AN ERROR. A callback redelivered after it
was already applied asks for a state the profile is already in; that returns
NO_CHANGE, not a refusal, because refusing would make Twilio retry forever.
"""
from __future__ import annotations

# ── our states (migration 027's trp_state_chk) ─────────────────────────────
NOT_STARTED = "not_started"
DETAILS_REQUIRED = "details_required"
ADDRESS_VALIDATION_FAILED = "address_validation_failed"
READY_TO_SUBMIT = "ready_to_submit"
SUBMITTING = "submitting"
PENDING_REVIEW = "pending_review"
MORE_INFORMATION_REQUIRED = "more_information_required"
APPROVED = "approved"
REJECTED = "rejected"
NUMBER_PROVISIONING = "number_provisioning"
ACTIVE = "active"
FAILED = "failed"

ALL_STATES = (NOT_STARTED, DETAILS_REQUIRED, ADDRESS_VALIDATION_FAILED,
              READY_TO_SUBMIT, SUBMITTING, PENDING_REVIEW,
              MORE_INFORMATION_REQUIRED, APPROVED, REJECTED,
              NUMBER_PROVISIONING, ACTIVE, FAILED)

#: States from which no automatic sweep should keep polling.
TERMINAL_STATES = (APPROVED, REJECTED, ACTIVE)

#: States the reconciliation sweep is allowed to inspect.
NONTERMINAL_STATES = (SUBMITTING, PENDING_REVIEW, MORE_INFORMATION_REQUIRED,
                      NUMBER_PROVISIONING)

#: The whole graph. A transition not listed here does not exist.
ALLOWED: dict[str, tuple[str, ...]] = {
    NOT_STARTED: (DETAILS_REQUIRED, ADDRESS_VALIDATION_FAILED, FAILED),
    DETAILS_REQUIRED: (DETAILS_REQUIRED, READY_TO_SUBMIT, ADDRESS_VALIDATION_FAILED, FAILED),
    ADDRESS_VALIDATION_FAILED: (DETAILS_REQUIRED, ADDRESS_VALIDATION_FAILED, FAILED),
    READY_TO_SUBMIT: (SUBMITTING, DETAILS_REQUIRED, ADDRESS_VALIDATION_FAILED, FAILED),
    # A submission that never completed may be retried from the top.
    SUBMITTING: (PENDING_REVIEW, READY_TO_SUBMIT, FAILED),
    PENDING_REVIEW: (APPROVED, REJECTED, MORE_INFORMATION_REQUIRED, FAILED),
    MORE_INFORMATION_REQUIRED: (DETAILS_REQUIRED, READY_TO_SUBMIT, APPROVED, REJECTED, FAILED),
    # Approval is where a later telephony gate picks up. It must never walk
    # backwards into review on a late callback.
    APPROVED: (NUMBER_PROVISIONING, REJECTED, FAILED),
    # A rejection can be corrected and resubmitted.
    REJECTED: (DETAILS_REQUIRED, FAILED),
    NUMBER_PROVISIONING: (ACTIVE, APPROVED, FAILED),
    ACTIVE: (FAILED,),
    # FAILED requires an explicit operator retry, which re-enters collection.
    FAILED: (DETAILS_REQUIRED,),
}

APPLIED = "applied"
NO_CHANGE = "no_change"
ILLEGAL = "illegal"


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def transition(current: str, target: str) -> tuple[str, str]:
    """Decide one transition. Returns (outcome, reason).

    outcome is APPLIED, NO_CHANGE (already there -- idempotent replay) or ILLEGAL.
    Never raises: the caller decides whether an illegal transition is a bug to log
    or a stale delivery to ignore.
    """
    if current not in ALL_STATES:
        return ILLEGAL, f"unknown_current_state:{current}"
    if target not in ALL_STATES:
        return ILLEGAL, f"unknown_target_state:{target}"
    if current == target:
        return NO_CHANGE, "already_in_state"
    if target in ALLOWED.get(current, ()):
        return APPLIED, ""
    return ILLEGAL, f"{current}->{target}"


# ── provider status -> our state ───────────────────────────────────────────
# Twilio's own vocabulary, stored verbatim in bundle_status. This maps it onto
# ours; anything absent from the map is deliberately NOT mapped.
PROVIDER_STATUS_MAP: dict[str, str] = {
    "draft": DETAILS_REQUIRED,
    "pending-review": PENDING_REVIEW,
    "in-review": PENDING_REVIEW,
    "twilio-approved": APPROVED,
    "twilio-rejected": REJECTED,
    # 'provisionally-approved' is DELIBERATELY ABSENT. The SDK has the enum,
    # Twilio's documented status table does not list it, and a W9C purchase
    # rejection read "status is not twilio-approved". Treating it as approved on
    # the strength of its name would be inventing provider semantics, so it maps
    # to pending_review below and keeps waiting.
    "provisionally-approved": PENDING_REVIEW,
}


def state_for_provider_status(provider_status: str) -> tuple[str | None, str]:
    """Our state for a provider status, plus a note. (None, reason) when unmapped.

    An unmapped status -- a value Twilio adds after this was written -- must NOT
    cause a destructive transition. The caller records the raw value and flags the
    profile for review instead of guessing.
    """
    key = str(provider_status or "").strip().lower()
    if not key:
        return None, "empty_provider_status"
    if key in PROVIDER_STATUS_MAP:
        note = ("provisionally-approved is not treated as approved"
                if key == "provisionally-approved" else "")
        return PROVIDER_STATUS_MAP[key], note
    return None, f"unknown_provider_status:{key}"
