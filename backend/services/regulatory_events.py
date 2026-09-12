"""Identity model for Twilio regulatory status callbacks (W9D).

NO ENDPOINT HERE. W9D is the data foundation; the HTTP route, signature
verification and state application land in a later gate. What this module settles
now is the one thing the schema depends on: WHAT MAKES TWO CALLBACKS THE SAME
EVENT.

── WHAT TWILIO ACTUALLY SENDS ────────────────────────────────────────────────
`application/x-www-form-urlencoded`, on every Bundle status change except
pending-review -> in-review, carrying:

    AccountSid, BundleSid, Status, FailureReason   (+ ValidUntil, Email)

There is NO event id, NO timestamp and NO previous status. Every dedup scheme has
to be built out of those fields alone.

── WHY (bundle_sid, status) IS NOT AN IDENTITY ───────────────────────────────
A bundle can legitimately reach the same status twice:

    pending-review -> twilio-rejected -> (corrected) -> pending-review -> approved

Keying the ledger on status alone would collapse the second, genuine
pending-review into the first and destroy the transition. Keying on nothing would
turn each HTTP retry of one transition into a separate row. So identity is split:

    fingerprint  hash of the canonical fields -> identifies the CONTENT
    occurrence   which time that content has been seen for this bundle

and the rule is positional rather than temporal:

    incoming fingerprint == the LATEST row's fingerprint  -> redelivery
    otherwise                                             -> occurrence + 1

A retry arrives while its own row is still the latest, so it collapses. A
recurrence only happens after some other status became the latest, so it cannot
collapse. No OpenLines-side clock takes part in identity, which is what keeps the
rule stable under clock skew and replayed queues.

ValidUntil is IN the fingerprint on purpose: Twilio moving the validity deadline
is a real change the customer may need to act on, even at an unchanged status.
FailureReason is in it too, so a corrected or expanded rejection reason is never
silently swallowed by the first one.
"""
from __future__ import annotations

import hashlib
import re

#: The fields that constitute the content of a regulatory callback. AccountSid is
#: deliberately absent: it never varies for a given bundle, so it would add a
#: constant to every hash while changing nothing, and it is already a column.
CANONICAL_FIELDS = ("bundle_sid", "bundle_status", "failure_reason", "valid_until")

REDELIVERY = "redelivery"
NEW_OCCURRENCE = "new_occurrence"

_WS = re.compile(r"\s+")

# Twilio's own docs spell these two keys both ways ("BundleSID" in the callback
# table, "BundleSid" in the resource reference), so key matching is
# case-insensitive rather than trusting either spelling.
_ALIASES = {
    "bundlesid": "bundle_sid",
    "accountsid": "provider_account_sid",
    "status": "bundle_status",
    "failurereason": "failure_reason",
    "validuntil": "valid_until",
    "email": "email",
}


def _norm(value) -> str:
    """Collapse whitespace, strip, and keep the provider's own casing.

    Whitespace is normalised because an HTTP retry may differ only in encoding of
    a wrapped line. Case is NOT normalised for anything but status: FailureReason
    is prose we show a human, and lowercasing it would alter what we display.
    """
    return _WS.sub(" ", str(value if value is not None else "")).strip()


def parse_callback(form: dict) -> dict:
    """Twilio's form fields -> our column names. Unknown keys are dropped.

    Dropping unknown keys is deliberate: it is what stops a future field Twilio
    adds (or anything an unsigned caller invents) from reaching a column or a log.
    """
    out: dict[str, str] = {}
    for key, value in (form or {}).items():
        name = _ALIASES.get(str(key).strip().lower())
        if not name:
            continue
        out[name] = _norm(value)
    status = out.get("bundle_status", "")
    if status:
        # Twilio's statuses are lower-kebab ('twilio-approved'); normalising the
        # case here keeps the fingerprint stable if that ever wobbles.
        out["bundle_status"] = status.lower()
    return out


def fingerprint(event: dict) -> str:
    """Stable sha256 hex over CANONICAL_FIELDS, in that order.

    Unit-separator joined rather than concatenated, so ('ab','c') and ('a','bc')
    cannot collide.
    """
    joined = "\x1f".join(_norm(event.get(f)) for f in CANONICAL_FIELDS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def decide(*, incoming_fingerprint: str, latest_fingerprint: str | None,
           prior_occurrences: int) -> tuple[str, int]:
    """Is this a redelivery of the latest event, or a new occurrence?

    `prior_occurrences` is how many times this exact fingerprint has already been
    recorded for this bundle (0 if never).

    Returns (REDELIVERY, occurrence_to_bump) or (NEW_OCCURRENCE, occurrence_to_write).
    """
    if latest_fingerprint and latest_fingerprint == incoming_fingerprint:
        # Its own row is still the latest -> the same transition arriving again.
        return REDELIVERY, max(prior_occurrences, 1)
    return NEW_OCCURRENCE, prior_occurrences + 1
