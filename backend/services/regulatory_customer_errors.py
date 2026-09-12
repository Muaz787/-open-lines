"""What a customer is told when regulatory verification cannot proceed (W9I-C).

W9I-A found two problems with the existing surface. Provider detail reached the
customer -- Twilio error codes, resource SIDs, exception text -- and several
authorisation outcomes had no mapping at all, so they arrived as an opaque 400.

Both matter for the same reason. A person in the middle of verifying their
business needs to know ONE thing: what, if anything, they must do. A Twilio error
code cannot tell them that, and leaking it exposes our provider topology to
anyone who can trigger an error. So every outcome is translated here, once, into:

    code            a stable application status a UI can branch on
    message         plain language, safe to display, naming no provider
    action_required whether the customer has to do something
    revisit         which step to send them back to, when there is one

WHAT IS DELIBERATELY NOT HERE
The provider's own words. They stay in the logs, where the engine already puts
them, and they are what an operator reads when reconciling. The customer gets the
consequence, not the cause.

A provider outage is NEVER described as a problem with the customer's data. That
distinction is the whole reason ensure_address separates PROVIDER_UNAVAILABLE from
ADDRESS_VALIDATION_FAILED, and collapsing them here would throw that away -- a
customer told their real address is invalid will "fix" a correct address into a
wrong one, and then the filing fails for a reason nobody can see.
"""
from __future__ import annotations

from services import regulatory_engine as engine
from services import regulatory_requirements as rq
from services import regulatory_review as review

# Steps in the customer's journey, used to say where to go back to.
STEP_COUNTRY = "country"
STEP_DETAILS = "details"
STEP_ADDRESS = "address"
STEP_REVIEW = "review"
STEP_NONE = ""

#: status -> (http, code, message, action_required, revisit)
_CONTRACT: dict[str, tuple[int, str, str, bool, str]] = {
    # ── the customer has to supply or correct something ──────────────────
    engine.MISSING_COUNTRY: (
        409, "country_not_confirmed",
        "Confirm the country your business operates in before we can tell you "
        "what verification is required.", True, STEP_COUNTRY),
    engine.INVALID_CUSTOMER_DATA: (
        422, "business_details_incomplete",
        "Some required business details are missing or not in an accepted format.",
        True, STEP_DETAILS),
    engine.ADDRESS_VALIDATION_FAILED: (
        422, "address_not_accepted",
        "We could not verify that address. Check the street, town and Eircode "
        "exactly as they appear on your official registration.", True, STEP_ADDRESS),
    engine.UNSUPPORTED_REQUIREMENT_FIELD: (
        501, "verification_not_supported_yet",
        "Your regulator is asking for information we cannot collect online yet. "
        "Our team will contact you to complete this.", False, STEP_NONE),
    engine.UNSUPPORTED_DOCUMENT_REQUIREMENT: (
        501, "verification_not_supported_yet",
        "Your regulator is asking for a document we cannot collect online yet. "
        "Our team will contact you to complete this.", False, STEP_NONE),

    # ── authorisation ────────────────────────────────────────────────────
    engine.AUTHORIZATION_NOT_RECORDED: (
        409, "authorization_required",
        "Review and confirm your business information before we can register "
        "your number.", True, STEP_REVIEW),
    engine.AUTHORIZATION_STALE: (
        409, "authorization_out_of_date",
        "Your business information changed since you last confirmed it. Please "
        "review and confirm it again.", True, STEP_REVIEW),
    engine.AUTHORIZATION_REVOKED: (
        409, "authorization_withdrawn",
        "Your authorisation was withdrawn. Review and confirm your business "
        "information again to continue.", True, STEP_REVIEW),
    engine.AUTHORIZATION_WRONG_SCOPE: (
        409, "authorization_for_another_address",
        "You have confirmed a different business address. Each premises needs "
        "its own confirmation.", True, STEP_REVIEW),

    # ── the review proof ─────────────────────────────────────────────────
    review.EXPIRED: (
        409, "review_expired",
        "This confirmation page has expired. Please review your information "
        "again.", True, STEP_REVIEW),
    review.STALE: (
        409, "review_out_of_date",
        "Your information changed while this page was open. Please review the "
        "updated details and confirm again.", True, STEP_REVIEW),
    review.SCOPE_MISMATCH: (
        409, "review_wrong_scope",
        "This confirmation does not match the business address being verified. "
        "Please review that address and confirm again.", True, STEP_REVIEW),
    review.INVALID: (
        400, "review_invalid",
        "We could not verify this confirmation. Please review your information "
        "again.", True, STEP_REVIEW),

    # ── ours, or the provider's — never the customer's fault ─────────────
    engine.REQUIREMENTS_CHANGED: (
        409, "requirements_changed",
        "The verification requirements for your country changed while you were "
        "filling this in. Please review the updated form.", True, STEP_DETAILS),
    engine.PROVIDER_UNAVAILABLE: (
        503, "verification_temporarily_unavailable",
        "We could not reach the verification service just now. Your information "
        "is saved — please try again in a few minutes.", False, STEP_NONE),
    rq.UNAVAILABLE: (
        503, "verification_temporarily_unavailable",
        "We could not reach the verification service just now. Your information "
        "is saved — please try again in a few minutes.", False, STEP_NONE),
    rq.NOT_FOUND: (
        501, "country_not_supported_yet",
        "We do not yet support number registration for this country.",
        False, STEP_NONE),
    rq.AMBIGUOUS: (
        409, "verification_needs_review",
        "Your country's requirements need a manual check. Our team will "
        "contact you.", False, STEP_NONE),
    engine.OWNERSHIP_CONFLICT: (
        409, "verification_needs_review",
        "This business address is already being verified on another account. "
        "Our team will contact you.", False, STEP_NONE),
    engine.REGULATORY_IDENTITY_CONFLICT: (
        409, "verification_needs_review",
        "Your verification records need a manual check. Our team will contact "
        "you.", False, STEP_NONE),
    engine.NOT_READY: (
        409, "verification_incomplete",
        "Some earlier steps are not finished yet.", True, STEP_DETAILS),
}

#: Anything not named above. A new engine status must not reach a customer as raw
#: text just because nobody remembered to map it -- see test_every_status_is_mapped,
#: which fails when one is added without an entry.
_FALLBACK = (400, "verification_failed",
             "We could not complete this step. Please try again, or contact us "
             "if it keeps happening.", False, STEP_NONE)

#: Keys a customer response may echo from an engine result. `missing` and
#: `invalid_enum` name FIELDS, which the customer typed and already knows;
#: everything else -- detail, blockers, regulation_sid, provider payloads -- stays
#: server-side.
_SAFE_ECHO = ("missing", "invalid_enum", "unresolved_declarations")


def for_status(status: str, *, result: dict | None = None) -> tuple[int, dict]:
    """Translate one engine/review status into (http_status, customer_payload)."""
    http, code, message, action, revisit = _CONTRACT.get(str(status or ""), _FALLBACK)
    payload = {
        "status": code,
        "message": message,
        "action_required": action,
    }
    if revisit:
        payload["revisit_step"] = revisit
    for key in _SAFE_ECHO:
        value = (result or {}).get(key)
        if value:
            payload[key] = value
    return http, payload


def is_mapped(status: str) -> bool:
    return str(status or "") in _CONTRACT
