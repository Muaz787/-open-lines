"""W9I-G — the provider-idempotency contract for the activation email.

TWO MECHANISMS, DOING DIFFERENT JOBS
  the DB claim      stops two CONCURRENT workers becoming two email events
  the provider key  stops one event becoming two DELIVERED emails

Neither is sufficient alone, and the tests below are grouped that way. The claim
cannot help once the process holding it has died mid-send; the key cannot stop
two workers building two different messages.

WHAT IS MEASURED, NOT ASSUMED
resend 2.44.0 accepts `Emails.send(params, options={"idempotency_key": ...})`
and turns it into the `Idempotency-Key` header on POST -- read from the SDK's
own request builder during the W9I-G checkpoint audit. An earlier draft of this
gate inferred the SDK had no such support because it failed to import in a local
shell; it is a real production dependency that conftest stubs.

No live email is sent by anything here.
"""
from unittest.mock import MagicMock, patch

import pytest

from services import activation_notification as notify

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
ROW = "33333333-3333-3333-3333-333333333333"
REPLACEMENT_ROW = "44444444-4444-4444-4444-444444444444"
E164 = "+35315550123"
TO = "owner@example.ie"


class _ResendError(Exception):
    """Shaped like resend.exceptions.ResendError: a code plus the API's `type`."""

    def __init__(self, error_type, code=400, message="x"):
        super().__init__(message)
        self.error_type = error_type
        self.code = code
        self.message = message


# ═══ 1. one activation, one key ════════════════════════════════════════════

def test_the_same_activation_always_derives_the_same_key():
    """A fresh key per attempt is exactly how a retry becomes a second email."""
    first = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    for _ in range(5):
        assert notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW) == first


def test_the_key_format_is_pinned():
    key = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    assert key == f"openlines-ie-activation/{TENANT}/{ROW}"
    assert key.startswith(notify.KEY_PREFIX)


def test_a_replacement_number_gets_a_different_key():
    """THE reason the notification is scoped to the phone row and not the tenant:
    a tenant can replace a +353, and the replacement must be announced."""
    original = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    replacement = notify.idempotency_key(tenant_id=TENANT, phone_row_id=REPLACEMENT_ROW)
    assert original != replacement


def test_two_tenants_never_share_a_key():
    assert (notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
            != notify.idempotency_key(tenant_id=OTHER_TENANT, phone_row_id=ROW))


def test_the_key_fits_the_provider_limit():
    """W9H shipped a 65-character marker against a 64-character provider limit
    and the failure was silent. This one is asserted."""
    key = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    assert len(key) <= notify.KEY_MAX
    assert notify.KEY_MAX == 256          # Resend's documented ceiling


def test_the_key_carries_no_secret_or_customer_data():
    key = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    for leak in (TO, E164, "@", "+353"):
        assert leak not in key, leak


def test_a_key_cannot_be_derived_from_a_missing_id():
    for kwargs in ({"tenant_id": "", "phone_row_id": ROW},
                   {"tenant_id": TENANT, "phone_row_id": ""}):
        with pytest.raises(ValueError):
            notify.idempotency_key(**kwargs)


def test_an_oversized_key_is_refused_rather_than_truncated():
    """A truncated key silently stops deduplicating."""
    with pytest.raises(ValueError):
        notify.idempotency_key(tenant_id="t" * 200, phone_row_id="r" * 200)


# ═══ 2. the payload must be as stable as the key ══════════════════════════

def test_the_payload_is_deterministic_for_one_activation():
    """Resend compares the key AND the body. A body that drifts between retries
    wedges recovery instead of deduplicating."""
    first = notify.payload(recipient=TO, e164=E164)
    for _ in range(5):
        assert notify.payload(recipient=TO, e164=E164) == first


def test_the_payload_contains_the_real_number():
    body = notify.payload(recipient=TO, e164=E164)
    assert body["e164"] == E164
    assert body["to"] == TO
    assert body["subject"] == notify.SUBJECT


def test_an_empty_number_can_never_be_emailed():
    """The exact shape of the defect W9I-G.0 fixed, made structurally impossible
    on this path."""
    for bad in ("", "   ", "353151234", None):
        with pytest.raises(ValueError):
            notify.payload(recipient=TO, e164=bad)


def test_an_empty_recipient_is_refused():
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            notify.payload(recipient=bad, e164=E164)


def test_the_payload_excludes_mutable_decoration():
    """Every mutable field in the body is another way for a retry to fail. The
    business name adds nothing the customer does not know."""
    body = notify.payload(recipient=TO, e164=E164)
    assert set(body) == {"to", "subject", "e164"}


def test_a_changed_recipient_is_a_different_payload():
    """Named rather than hidden: the recipient is the one mutable input, and a
    change inside the provider window makes a retry an invalid idempotent
    request -- which fails closed to review, not to a duplicate."""
    a = notify.payload_fingerprint(notify.payload(recipient=TO, e164=E164))
    b = notify.payload_fingerprint(notify.payload(recipient="new@example.ie", e164=E164))
    assert a != b


def test_the_fingerprint_does_not_expose_the_body():
    fp = notify.payload_fingerprint(notify.payload(recipient=TO, e164=E164))
    assert len(fp) == 64 and TO not in fp and E164 not in fp


# ═══ 3. classifying what the provider says ════════════════════════════════

def test_a_concurrent_idempotent_request_is_retryable():
    """Another request holding the same key is in flight. Ours did not deliver,
    and the one that did will confirm."""
    for etype in ("concurrent_idempotent_requests", "concurrent_idempotent_request"):
        assert notify.classify(_ResendError(etype, code=409)) == notify.CONCURRENT


def test_an_invalid_idempotent_request_fails_closed():
    """Same key, different body. Retrying cannot fix it and would never
    deliver -- so it stops being automatic."""
    for etype in ("invalid_idempotent_request", "invalid_idempotent_requests"):
        assert notify.classify(_ResendError(etype, code=400)) == notify.INVALID


def test_a_successful_send_classifies_as_sent():
    assert notify.classify(None) == notify.SENT


@pytest.mark.parametrize("etype,code", [
    ("rate_limit_exceeded", 429), ("daily_quota_exceeded", 429),
    ("application_error", 500), ("internal_server_error", 500),
])
def test_transient_provider_failures_are_retryable(etype, code):
    assert notify.classify(_ResendError(etype, code=code)) == notify.RETRYABLE


@pytest.mark.parametrize("etype", ["missing_api_key", "invalid_api_key",
                                   "validation_error", "missing_required_field"])
def test_a_refusal_retrying_cannot_fix_is_fatal(etype):
    assert notify.classify(_ResendError(etype)) == notify.FATAL


def test_an_unknown_failure_is_retryable_not_fatal():
    """The same key makes a retry safe, so the cost of retrying something
    unretryable is one wasted call -- against a customer never being told their
    number is live."""
    assert notify.classify(TimeoutError("read timed out")) == notify.RETRYABLE
    assert notify.classify(_ResendError("something_new_resend_added")) == notify.RETRYABLE


def test_a_timeout_does_not_change_the_key():
    """A retry after a timeout must reuse the key, or the provider cannot
    deduplicate the send that may already have happened."""
    key_before = notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW)
    assert notify.classify(TimeoutError("timed out")) == notify.RETRYABLE
    assert notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW) == key_before


# ═══ 4. the provider's memory has an edge ═════════════════════════════════

def test_a_recent_unconfirmed_claim_may_be_taken_over(monkeypatch):
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    """Inside the window the provider still deduplicates, so a takeover sending
    the same key and body is genuinely safe."""
    assert notify.stale_claim_outcome(60) == notify.TAKEOVER_SAFE
    assert notify.stale_claim_outcome(60 * 60) == notify.TAKEOVER_SAFE


def test_a_claim_older_than_the_safe_window_never_auto_resends(monkeypatch):
    """THE case: the email was delivered, the acknowledgement was lost, and the
    service was down longer than Resend remembers the key. Taking the claim over
    now sends the same key to a provider that has forgotten it, and the customer
    gets a second email."""
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    beyond = notify.safe_retry_window_seconds() + 1
    assert notify.stale_claim_outcome(beyond) == notify.NEEDS_REVIEW
    assert notify.stale_claim_outcome(beyond * 10) == notify.NEEDS_REVIEW


def test_the_default_window_is_twenty_hours_and_strictly_inside_the_provider_window(monkeypatch):
    """The retention is documented as *approximately* 24h. Four hours of margin
    costs a review that would otherwise have auto-retried; four minutes of margin
    costs a duplicate email to a customer."""
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    assert notify.DEFAULT_SAFE_RETRY_WINDOW_HOURS == 20
    assert notify.safe_retry_window_seconds() == 20 * 60 * 60
    assert (notify.safe_retry_window_seconds()
            < notify.PROVIDER_IDEMPOTENCY_WINDOW_HOURS * 60 * 60)


def test_the_window_is_configurable(monkeypatch):
    monkeypatch.setenv(notify.SAFE_RETRY_WINDOW_ENV, "6")
    assert notify.safe_retry_window_seconds() == 6 * 60 * 60
    assert notify.stale_claim_outcome(5 * 60 * 60) == notify.TAKEOVER_SAFE
    assert notify.stale_claim_outcome(7 * 60 * 60) == notify.NEEDS_REVIEW


@pytest.mark.parametrize("bad", ["24", "25", "0", "-3", "abc", "1e9"])
def test_a_window_outside_the_provider_retention_is_refused_not_defaulted(monkeypatch, bad):
    """A silent fallback is how a deployment ends up running a window nobody
    chose -- and one at or past 24h is a window the provider cannot honour."""
    monkeypatch.setenv(notify.SAFE_RETRY_WINDOW_ENV, bad)
    with pytest.raises(ValueError):
        notify.safe_retry_window_seconds()


def test_the_edge_of_the_safe_window_is_exact(monkeypatch):
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    edge = notify.safe_retry_window_seconds()
    assert notify.stale_claim_outcome(edge - 1) == notify.TAKEOVER_SAFE
    assert notify.stale_claim_outcome(edge) == notify.NEEDS_REVIEW
    assert notify.stale_claim_outcome(edge + 1) == notify.NEEDS_REVIEW


def test_the_declared_provider_window_matches_the_documentation():
    assert notify.PROVIDER_IDEMPOTENCY_WINDOW_HOURS == 24


def test_a_clock_moving_backwards_is_not_a_licence_to_send(monkeypatch):
    monkeypatch.delenv(notify.SAFE_RETRY_WINDOW_ENV, raising=False)
    assert notify.stale_claim_outcome(-1) == notify.NEEDS_REVIEW


def test_review_is_a_state_not_another_side_effect():
    """Uncertainty must not be resolved by producing another customer-visible
    email, which is the whole reason this module exists rather than a retry."""
    assert notify.NEEDS_REVIEW == "activation_notification_needs_review"
    assert notify.NEEDS_REVIEW != notify.TAKEOVER_SAFE


# ═══ 5. the key actually reaches the provider ═════════════════════════════

def test_the_key_is_passed_to_resend_as_a_request_option():
    """Measured against resend 2.44.0: options={"idempotency_key": ...} becomes
    the Idempotency-Key header on POST. This asserts we pass it that way, and
    NOT as an email header -- which sets a header on the message instead."""
    from services import email as mail
    seen = {}

    def fake_send(params, options=None):
        seen["params"], seen["options"] = params, options
        return {"id": "resend_abc123"}

    with patch.object(mail, "resend", MagicMock(api_key="re_test",
                                                Emails=MagicMock(send=fake_send))):
        out = mail.send_with_outcome(
            to=TO, subject=notify.SUBJECT, html_body="<p>hi</p>",
            idempotency_key=notify.idempotency_key(tenant_id=TENANT, phone_row_id=ROW))

    assert out["ok"] is True
    assert out["provider_id"] == "resend_abc123"
    assert seen["options"] == {"idempotency_key": f"openlines-ie-activation/{TENANT}/{ROW}"}
    # NOT smuggled into the message headers.
    assert "Idempotency-Key" not in (seen["params"].get("headers") or {})


def test_a_send_without_a_key_passes_no_options():
    """Every existing caller must keep behaving exactly as before."""
    from services import email as mail
    seen = {}

    def fake_send(params, options=None):
        seen["options"] = options
        return {"id": "x"}

    with patch.object(mail, "resend", MagicMock(api_key="re_test",
                                                Emails=MagicMock(send=fake_send))):
        assert mail._send(to=TO, subject="s", html_body="<p>x</p>") is True
    assert seen["options"] is None


def test_the_outcome_reports_the_provider_error_for_classification():
    """The activation path has to tell a concurrent idempotent request from an
    invalid one, and that distinction lives in the provider's error_type."""
    from services import email as mail
    err = _ResendError("invalid_idempotent_request", code=400)

    def boom(params, options=None):
        raise err

    with patch.object(mail, "resend", MagicMock(api_key="re_test",
                                                Emails=MagicMock(send=boom))):
        out = mail.send_with_outcome(to=TO, subject="s", html_body="<p>x</p>",
                                     idempotency_key="k")
    assert out["ok"] is False
    assert out["error"] is err
    assert notify.classify(out["error"]) == notify.INVALID


def test_a_missing_api_key_is_not_reported_as_a_provider_error():
    """Nothing was attempted, so there is nothing to classify or retry against."""
    from services import email as mail
    with patch.object(mail, "resend", MagicMock(api_key="")):
        out = mail.send_with_outcome(to=TO, subject="s", html_body="<p>x</p>",
                                     idempotency_key="k")
    assert out == {"ok": False, "provider_id": "", "error": None}


def test_the_existing_bool_contract_is_unchanged():
    from services import email as mail
    import inspect
    sig = inspect.signature(mail._send)
    assert sig.return_annotation is bool
    # Every pre-existing parameter still present and still keyword-only.
    for name in ("to", "subject", "html_body", "text_body", "headers"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
