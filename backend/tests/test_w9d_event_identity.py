"""W9D — what makes two Twilio regulatory callbacks the same event.

Twilio's callback carries AccountSid, BundleSid, Status and FailureReason (plus
ValidUntil and Email). There is no event id, no timestamp and no previous status,
so the whole dedup scheme has to be built from those fields.

The design under test:
    fingerprint = sha256 over (bundle_sid, status, failure_reason, valid_until)
    occurrence  = which time that content has been seen for this bundle
    rule        = fingerprint equals the LATEST row's fingerprint -> redelivery,
                  otherwise a new occurrence

These tests exist because the obvious key -- (bundle_sid, status) -- is wrong, and
wrong in a way that silently destroys data: a bundle can reach the same status
twice, and collapsing the second occurrence loses a real transition.
"""
import pytest

from services import regulatory_events as ev

BUNDLE = "BU00000000000000000000000000000001"
ACCOUNT = "AC00000000000000000000000000000001"


def callback(status, failure="", valid_until="", bundle=BUNDLE):
    return {"AccountSid": ACCOUNT, "BundleSid": bundle, "Status": status,
            "FailureReason": failure, "ValidUntil": valid_until}


def fp(**kw):
    return ev.fingerprint(ev.parse_callback(callback(**kw)))


# ── parsing ────────────────────────────────────────────────────────────────

def test_twilio_form_keys_map_onto_our_columns():
    out = ev.parse_callback(callback("twilio-approved"))
    assert out["bundle_sid"] == BUNDLE
    assert out["provider_account_sid"] == ACCOUNT
    assert out["bundle_status"] == "twilio-approved"


def test_both_documented_spellings_of_the_sid_keys_are_accepted():
    """Twilio's own docs write BundleSID in the callback table and BundleSid in the
    resource reference. Trusting one spelling would drop the field."""
    a = ev.parse_callback({"BundleSID": BUNDLE, "AccountSID": ACCOUNT, "Status": "draft"})
    b = ev.parse_callback({"bundlesid": BUNDLE, "accountsid": ACCOUNT, "status": "draft"})
    assert a == b
    assert a["bundle_sid"] == BUNDLE


def test_unknown_fields_are_dropped():
    """What stops a field Twilio adds later -- or anything an unsigned caller
    invents -- from reaching a column or a log."""
    out = ev.parse_callback({**callback("draft"), "Ssn": "x", "extra": "y"})
    assert set(out) <= {"bundle_sid", "provider_account_sid", "bundle_status",
                        "failure_reason", "valid_until", "email"}
    assert "x" not in str(out)


def test_status_case_is_normalised_but_failure_prose_is_not():
    out = ev.parse_callback(callback("Twilio-Approved", failure="Business Name mismatch"))
    assert out["bundle_status"] == "twilio-approved"
    assert out["failure_reason"] == "Business Name mismatch"


def test_whitespace_differences_do_not_create_a_new_event():
    """An HTTP retry may differ only in how a wrapped line was encoded."""
    assert fp(status="pending-review", failure="a  b\n c") == \
           fp(status="pending-review", failure="a b c")


# ── fingerprint ────────────────────────────────────────────────────────────

def test_fingerprint_is_a_sha256_hex_digest():
    digest = fp(status="draft")
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_fingerprint_is_stable_across_calls():
    assert fp(status="draft") == fp(status="draft")


def test_status_change_changes_the_fingerprint():
    assert fp(status="pending-review") != fp(status="twilio-approved")


def test_failure_reason_change_changes_the_fingerprint():
    """So a corrected or expanded rejection reason is never silently swallowed by
    the first one."""
    assert fp(status="twilio-rejected", failure="address invalid") != \
           fp(status="twilio-rejected", failure="address invalid; CRN not found")


def test_valid_until_change_changes_the_fingerprint():
    """Twilio moving the validity deadline is a real change the customer may need
    to act on, even at an unchanged status."""
    assert fp(status="twilio-approved", valid_until="2027-01-01T00:00:00Z") != \
           fp(status="twilio-approved", valid_until="2027-06-01T00:00:00Z")


def test_different_bundles_never_share_a_fingerprint():
    assert fp(status="draft") != fp(status="draft", bundle="BU" + "9" * 32)


def test_the_account_sid_is_not_part_of_the_fingerprint():
    """It never varies for a bundle, so including it would add a constant to every
    hash while changing nothing -- and it is already a column."""
    a = ev.fingerprint(ev.parse_callback(callback("draft")))
    b = ev.fingerprint(ev.parse_callback({**callback("draft"), "AccountSid": "ACother"}))
    assert a == b
    assert "provider_account_sid" not in ev.CANONICAL_FIELDS


def test_field_boundaries_cannot_be_forged():
    """('ab','c') and ('a','bc') must not collide, which a plain concatenation
    would allow."""
    assert fp(status="ab", failure="c") != fp(status="a", failure="bc")


# ── the redelivery / recurrence rule ───────────────────────────────────────

def test_an_exact_duplicate_delivery_collapses():
    digest = fp(status="pending-review")
    action, occurrence = ev.decide(incoming_fingerprint=digest,
                                   latest_fingerprint=digest, prior_occurrences=1)
    assert action == ev.REDELIVERY
    assert occurrence == 1


def test_a_first_ever_callback_is_occurrence_one():
    action, occurrence = ev.decide(incoming_fingerprint=fp(status="draft"),
                                   latest_fingerprint=None, prior_occurrences=0)
    assert (action, occurrence) == (ev.NEW_OCCURRENCE, 1)


def test_a_status_progression_creates_a_new_row():
    first = fp(status="pending-review")
    second = fp(status="twilio-approved")
    action, occurrence = ev.decide(incoming_fingerprint=second,
                                   latest_fingerprint=first, prior_occurrences=0)
    assert (action, occurrence) == (ev.NEW_OCCURRENCE, 1)


def test_the_same_status_returning_later_is_NOT_destroyed():
    """THE REASON (bundle_sid, status) IS NOT THE KEY.

        pending-review -> twilio-rejected -> (corrected) -> pending-review

    The second pending-review is a genuine transition. It arrives when the
    REJECTION is the latest row, so it cannot be mistaken for a redelivery, and it
    lands as occurrence 2 rather than overwriting occurrence 1.
    """
    pending = fp(status="pending-review")
    rejected = fp(status="twilio-rejected", failure="address invalid")
    action, occurrence = ev.decide(incoming_fingerprint=pending,
                                   latest_fingerprint=rejected, prior_occurrences=1)
    assert action == ev.NEW_OCCURRENCE
    assert occurrence == 2


def test_a_redelivery_of_the_recurrence_collapses_onto_the_recurrence():
    pending = fp(status="pending-review")
    action, occurrence = ev.decide(incoming_fingerprint=pending,
                                   latest_fingerprint=pending, prior_occurrences=2)
    assert (action, occurrence) == (ev.REDELIVERY, 2)


def test_a_full_lifecycle_walk_produces_exactly_the_right_rows():
    """Simulates the ledger: a rejection cycle with retries at every step, ending
    approved. Five distinct events, several redeliveries, nothing lost."""
    deliveries = [
        callback("pending-review"),
        callback("pending-review"),                                  # HTTP retry
        callback("twilio-rejected", failure="address invalid"),
        callback("twilio-rejected", failure="address invalid"),       # HTTP retry
        callback("twilio-rejected", failure="address invalid; CRN not found"),
        callback("pending-review"),                                   # genuine return
        callback("pending-review"),                                   # HTTP retry
        callback("twilio-approved", valid_until="2027-01-01T00:00:00Z"),
    ]
    rows: list[dict] = []          # the ledger, newest last
    for form in deliveries:
        parsed = ev.parse_callback(form)
        digest = ev.fingerprint(parsed)
        latest = rows[-1]["fingerprint"] if rows else None
        prior = sum(1 for r in rows if r["fingerprint"] == digest)
        action, occurrence = ev.decide(incoming_fingerprint=digest,
                                       latest_fingerprint=latest,
                                       prior_occurrences=prior)
        if action == ev.REDELIVERY:
            rows[-1]["delivery_count"] += 1
        else:
            rows.append({"fingerprint": digest, "occurrence": occurrence,
                         "bundle_status": parsed["bundle_status"],
                         "failure_reason": parsed.get("failure_reason", ""),
                         "delivery_count": 1})

    assert [r["bundle_status"] for r in rows] == [
        "pending-review", "twilio-rejected", "twilio-rejected",
        "pending-review", "twilio-approved"]
    # both pending-review transitions survive, as occurrence 1 and 2
    pendings = [r for r in rows if r["bundle_status"] == "pending-review"]
    assert [r["occurrence"] for r in pendings] == [1, 2]
    # the retries collapsed rather than creating rows
    assert [r["delivery_count"] for r in rows] == [2, 2, 1, 2, 1]
    # both rejection reasons are retained
    assert [r["failure_reason"] for r in rows if r["bundle_status"] == "twilio-rejected"] \
        == ["address invalid", "address invalid; CRN not found"]
    # every (fingerprint, occurrence) pair is unique, as the index requires
    keys = [(r["fingerprint"], r["occurrence"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_identity_never_depends_on_an_openlines_clock():
    """decide() takes no timestamp at all, so a replayed queue or a skewed clock
    cannot change how an event is classified."""
    import inspect
    params = set(inspect.signature(ev.decide).parameters)
    assert params == {"incoming_fingerprint", "latest_fingerprint", "prior_occurrences"}
    assert not any("time" in f or "at" == f[-2:] for f in ev.CANONICAL_FIELDS)
