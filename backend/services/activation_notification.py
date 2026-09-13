"""The "your Irish number is live" email, sent once per activation (W9I-G).

WHAT THE CHECKPOINT REVIEW CORRECTED, AND WHY IT WAS RIGHT
The first design put the notification state on `tenants`. That is wrong, and
wrong in a way that only shows up later: a tenant can eventually REPLACE a +353
-- a reclaim, a port, a regulatory re-filing -- and a tenant-global `sent_at`
would suppress the activation email for the replacement number. The customer
would get a new number and never be told.

The notification belongs to the ACTIVATION, and the activation is a particular
row in `tenant_phone_numbers`. A replacement is a different row, so it gets its
own notification lifecycle and its own idempotency key, for free.

THE GUARANTEE, AND WHERE IT COMES FROM
Two mechanisms, doing different jobs:

  the DB claim      stops two CONCURRENT workers becoming two email events
  the provider key  stops one event becoming two DELIVERED emails

Neither is sufficient alone. A claim cannot help once the process that held it
has died mid-send; a provider key cannot stop two workers building two different
messages. Together they cover the crash window: a second worker that takes over
an unconfirmed claim sends the SAME key with the SAME payload, and Resend
returns the original send instead of delivering again.

Measured, not assumed: resend 2.44.0 accepts
`Emails.send(params, options={"idempotency_key": ...})` and turns it into the
`Idempotency-Key` header on POST -- read from the SDK's own request builder.

THE WINDOW IS THE HARD EDGE
Resend retains an idempotency key for about 24 hours. Past that the key is
meaningless and a "retry" is simply a second email. So a claim older than that
window with no confirmed send is NOT retried -- it becomes a review state.
Uncertainty must not be resolved by producing another customer-visible side
effect, which is the whole reason this module exists rather than a bare retry.

NOTHING HERE TOUCHES THE DATABASE. This is the deterministic half -- key
derivation, payload construction, provider-response classification -- so it can
be pinned by tests before migration 032R exists. The claim/confirm half lands
with that migration.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

# ── the idempotency key ────────────────────────────────────────────────────

#: Namespaced so a key can never collide with another OpenLines use of the same
#: provider, and readable so an operator can find the activation it belongs to.
KEY_PREFIX = "openlines-ie-activation"

#: Resend documents a 256-character ceiling. The derived key is 98 for two
#: UUIDs, well inside it; asserted rather than assumed, because W9H shipped a
#: 65-character marker against a 64-character provider limit and the failure was
#: silent.
KEY_MAX = 256


def idempotency_key(*, tenant_id: str, phone_row_id: str) -> str:
    """The one key for one permanent-number activation.

    Derived from two IMMUTABLE ids, so every retry of the same activation
    produces the same key and a REPLACEMENT number -- a different phone row --
    produces a different one. Never random per attempt: a fresh key on each try
    is exactly how a retry becomes a second email.

    Contains no secret and no customer data: both values are internal
    identifiers, and the key travels in a request header a provider logs.
    """
    tid = str(tenant_id or "").strip()
    rid = str(phone_row_id or "").strip()
    if not tid or not rid:
        raise ValueError("an activation idempotency key needs both ids")
    key = f"{KEY_PREFIX}/{tid}/{rid}"
    if len(key) > KEY_MAX:
        # Cannot happen with UUIDs, and must not pass silently if id shapes ever
        # change -- a truncated key would silently stop deduplicating.
        raise ValueError(f"activation idempotency key too long: {len(key)}")
    return key


# ── the payload ────────────────────────────────────────────────────────────
#
# Resend compares the key AND the body. Same key with a DIFFERENT body is an
# error, not a silent re-send -- which is the behaviour we want, but it means a
# payload that drifts between retries wedges recovery. So the payload is built
# from as little mutable data as possible.

SUBJECT = "Your Irish OpenLines number is ready"


def payload(*, recipient: str, e164: str) -> dict:
    """The canonical activation message. Deterministic for one activation.

    EVERY input is either constant or immutable-per-activation, with ONE
    exception, named here rather than discovered later: `recipient` is read from
    the tenant row and a customer can change it. If it changes inside the
    provider's idempotency window and a retry follows, Resend rejects the retry
    as an invalid idempotent request and the activation goes to review.

    That is a deliberate trade. The alternatives were a durable payload snapshot
    -- a whole outbox table to defend against an address changing in the same
    24 hours a number went live -- or folding the recipient into the key, which
    would send a SECOND email to the new address. A rare, visible review state
    is better than either.

    The business name is deliberately NOT in the message. It is mutable, it adds
    nothing the customer does not already know, and every mutable field in the
    body is another way for a retry to fail.
    """
    to = str(recipient or "").strip()
    number = str(e164 or "").strip()
    if not to:
        raise ValueError("an activation email needs a recipient")
    if not number.startswith("+"):
        # The empty-number welcome email is the exact defect W9I-G.0 fixed. It
        # cannot happen here.
        raise ValueError("an activation email needs a real E.164 number")
    return {"to": to, "subject": SUBJECT, "e164": number}


def payload_fingerprint(body: dict) -> str:
    """A digest of what was sent, so two attempts can be compared in a log.

    Not sent anywhere and not a security control -- purely so an operator
    diagnosing an invalid-idempotent-request can see that the body moved,
    without the body itself being written to a log.
    """
    parts = [f"{k}={body.get(k) or ''}" for k in ("to", "subject", "e164")]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# ── classifying what the provider says ─────────────────────────────────────

SENT = "sent"
#: Another request holding the same key is in flight. Ours did not deliver, and
#: the one that did will confirm. Retryable, with the SAME key.
CONCURRENT = "concurrent_idempotent_request"
#: Same key, different body. Retrying cannot fix it and would never deliver.
#: Fail closed -- this is a wedged activation needing a human.
INVALID = "invalid_idempotent_request"
#: Everything else: rate limits, 5xx, transport. Retryable with the same key.
RETRYABLE = "retryable"
#: A refusal that retrying will not change (bad API key, malformed sender).
FATAL = "fatal"

#: Resend's own `type` values for the two idempotency outcomes. They are not in
#: the SDK's ERRORS map, so they arrive as a generic ResendError carrying this
#: string -- which is why classification reads error_type rather than the class.
_CONCURRENT_TYPES = frozenset({"concurrent_idempotent_requests",
                               "concurrent_idempotent_request"})
_INVALID_TYPES = frozenset({"invalid_idempotent_request",
                            "invalid_idempotent_requests"})
_FATAL_TYPES = frozenset({"missing_api_key", "invalid_api_key",
                          "validation_error", "missing_required_field",
                          "missing_required_fields"})


def classify(error: Exception | None) -> str:
    """What a send outcome means for the NEXT attempt.

    Unknown is treated as RETRYABLE, not FATAL: the same key makes a retry safe,
    so the cost of retrying something unretryable is one wasted call, while the
    cost of giving up on something transient is a customer never told their
    number is live.
    """
    if error is None:
        return SENT
    etype = str(getattr(error, "error_type", "") or "").strip().lower()
    if etype in _CONCURRENT_TYPES:
        return CONCURRENT
    if etype in _INVALID_TYPES:
        return INVALID
    if etype in _FATAL_TYPES:
        return FATAL
    return RETRYABLE


# ── the provider's memory, and its edge ────────────────────────────────────

#: Resend retains an idempotency key for approximately 24 hours. This is the
#: PROVIDER's number, recorded so the safe window below can be checked against
#: it rather than against a memory of it.
PROVIDER_IDEMPOTENCY_WINDOW_HOURS = 24

#: How long WE will still treat a key as good for. Strictly below the provider's
#: retention, and configurable, because the margin is a judgement about how close
#: to an undocumented boundary it is sensible to run -- not a fact.
#:
#: 20 hours rather than 23: the retention is documented as "approximately" 24,
#: and what is being risked at the edge is a duplicate email to a customer. Four
#: hours of margin costs a review that would otherwise have auto-retried; four
#: minutes of margin costs a duplicate.
SAFE_RETRY_WINDOW_ENV = "ACTIVATION_EMAIL_SAFE_RETRY_WINDOW_HOURS"
DEFAULT_SAFE_RETRY_WINDOW_HOURS = 20

#: Outcomes for a claim that was never confirmed.
TAKEOVER_SAFE = "takeover_safe"
NEEDS_REVIEW = "activation_notification_needs_review"


def safe_retry_window_seconds() -> float:
    """How old an unconfirmed claim may be and still be retried.

    Refuses a configured value that is not strictly inside the provider's
    retention window, and refuses a malformed one, rather than quietly
    substituting the default -- a silent fallback is how a deployment ends up
    running a window nobody chose. The default applies only when the variable is
    absent, which is the one case where nobody chose anything.
    """
    import os
    raw = os.getenv(SAFE_RETRY_WINDOW_ENV, "").strip()
    if not raw:
        hours = DEFAULT_SAFE_RETRY_WINDOW_HOURS
    else:
        try:
            hours = float(raw)
        except ValueError:
            raise ValueError(
                f"{SAFE_RETRY_WINDOW_ENV}={raw!r} is not a number") from None
        if hours <= 0 or hours >= PROVIDER_IDEMPOTENCY_WINDOW_HOURS:
            raise ValueError(
                f"{SAFE_RETRY_WINDOW_ENV}={raw!r} must be >0 and strictly under "
                f"the provider's {PROVIDER_IDEMPOTENCY_WINDOW_HOURS}h retention")
    return hours * 60 * 60


def stale_claim_outcome(claim_age_seconds: float) -> str:
    """May an unconfirmed claim be retried, or must a human look at it?

    THE CASE THIS EXISTS FOR: the email was delivered, the acknowledgement was
    lost, and the service was then down for longer than the provider remembers
    the key. Taking the claim over now would send the SAME key -- to a provider
    that has forgotten it -- and the customer gets a second email.

    Inside the window a takeover is genuinely safe, because the provider still
    deduplicates. Outside it, nothing we can do locally distinguishes "never
    sent" from "sent and forgotten", so it stops being an automatic decision.
    """
    if claim_age_seconds < 0:
        # A clock moved. Not a licence to send.
        return NEEDS_REVIEW
    return TAKEOVER_SAFE if claim_age_seconds < safe_retry_window_seconds() \
        else NEEDS_REVIEW
