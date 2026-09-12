"""W9G — the Twilio regulatory callback: signature, ownership, ledger, replay.

THE PROXY PROBLEM IS THE POINT. Twilio signs the exact URL it posted to. Behind
Railway's proxy `request.url` is not that URL -- the proxy terminates TLS and can
present http or an internal host -- so verifying against it fails intermittently and
invites someone to "fix" it by turning verification off. The URL is therefore
reconstructed from the CONFIGURED public backend URL plus the known path, which is
exactly what routers/payments.py already does for Square's webhook, and it is the
same constant handed to Twilio as the status_callback so the two cannot drift.
"""
import pytest

# The real validator, loaded by conftest from the installed package. If it is not
# available these tests SKIP rather than pass against a mock -- a mock validator
# would accept every signature and the suite would be lying.
RequestValidator = None
try:
    from twilio.request_validator import RequestValidator  # type: ignore
except Exception:  # pragma: no cover
    pass
pytestmark = pytest.mark.skipif(RequestValidator is None,
                                reason="real twilio.request_validator unavailable")

from services import regulatory_callback as cb
from services import regulatory_engine as engine
from services import regulatory_events as events
from services import regulatory_state as st

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
SUB = "ACsub00000000000000000000000000001"
OTHER_SUB = "ACoth00000000000000000000000000002"
BUNDLE = "BU00000000000000000000000000000001"
TOKEN = "the-subaccount-auth-token"
URL = "https://backend-production-71174.up.railway.app/webhooks/twilio/regulatory"


def form(status="twilio-approved", failure="", bundle=BUNDLE, account=SUB):
    body = {"AccountSid": account, "BundleSid": bundle, "Status": status}
    if failure:
        body["FailureReason"] = failure
    return body


def sign(params, url=URL, token=TOKEN):
    return RequestValidator(token).compute_signature(url, params)


# ── signature verification ─────────────────────────────────────────────────

def test_a_correct_signature_is_accepted():
    params = form()
    assert cb.verify_signature(url=URL, params=params,
                               signature=sign(params), auth_token=TOKEN) is True


def test_a_tampered_form_field_is_rejected():
    params = form()
    sig = sign(params)
    tampered = {**params, "Status": "twilio-rejected"}
    assert cb.verify_signature(url=URL, params=tampered, signature=sig,
                               auth_token=TOKEN) is False


def test_an_added_form_field_is_rejected():
    params = form()
    sig = sign(params)
    assert cb.verify_signature(url=URL, params={**params, "Extra": "x"},
                               signature=sig, auth_token=TOKEN) is False


def test_a_tampered_url_is_rejected():
    params = form()
    sig = sign(params)
    for bad in (URL + "x", URL.replace("/regulatory", "/other"),
                "https://evil.example.com/webhooks/twilio/regulatory"):
        assert cb.verify_signature(url=bad, params=params, signature=sig,
                                   auth_token=TOKEN) is False


def test_an_http_vs_https_mismatch_is_rejected():
    """THE PROXY CASE. Railway terminates TLS, so a naive request.url can say http
    while Twilio signed https. It must fail, not be papered over."""
    params = form()
    sig = sign(params)
    assert cb.verify_signature(url=URL.replace("https://", "http://"), params=params,
                               signature=sig, auth_token=TOKEN) is False


def test_a_wrong_host_is_rejected():
    params = form()
    sig = sign(params)
    internal = "https://backend.railway.internal/webhooks/twilio/regulatory"
    assert cb.verify_signature(url=internal, params=params, signature=sig,
                               auth_token=TOKEN) is False


def test_a_missing_signature_is_rejected():
    params = form()
    assert cb.verify_signature(url=URL, params=params, signature="",
                               auth_token=TOKEN) is False
    assert cb.verify_signature(url=URL, params=params, signature=None,
                               auth_token=TOKEN) is False


def test_a_missing_token_is_rejected_rather_than_skipped():
    params = form()
    assert cb.verify_signature(url=URL, params=params, signature=sign(params),
                               auth_token="") is False


def test_a_signature_from_the_wrong_token_is_rejected():
    params = form()
    assert cb.verify_signature(url=URL, params=params,
                               signature=sign(params, token="different-token"),
                               auth_token=TOKEN) is False


def test_verification_never_raises_on_garbage():
    assert cb.verify_signature(url=URL, params=form(), signature="!!!not-base64!!!",
                               auth_token=TOKEN) is False


def test_the_signed_url_is_the_configured_one_not_a_request_url():
    """engine.callback_url() is both what Twilio is given and what is verified, so
    the two cannot drift."""
    assert engine.callback_url().endswith("/webhooks/twilio/regulatory")
    assert engine.callback_url().startswith("https://")


# ── resolving the profile ──────────────────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    state = {"profiles": [{"id": "p1", "tenant_id": TENANT, "bundle_sid": BUNDLE,
                           "provider_account_sid": SUB, "state": st.PENDING_REVIEW,
                           "bundle_status": "pending-review"}],
             "events": [], "writes": []}

    async def find_by_bundle(sid):
        return next((p for p in state["profiles"] if p.get("bundle_sid") == sid), None)
    async def latest_event(sid):
        rows = [e for e in state["events"] if e["bundle_sid"] == sid]
        return rows[-1] if rows else None
    async def count_fp(sid, fp):
        return len([e for e in state["events"]
                    if e["bundle_sid"] == sid and e["fingerprint"] == fp])
    async def insert_event(row):
        row = {**row, "id": f"ev-{len(state['events']) + 1}", "delivery_count": 1}
        state["events"].append(row)
        return row
    async def bump(eid, count):
        for e in state["events"]:
            if e["id"] == eid:
                e["delivery_count"] = count
                return e
        return None
    async def update_profile(pid, patch):
        state["writes"].append(("update", pid, dict(patch)))
        for p in state["profiles"]:
            if p["id"] == pid:
                p.update(patch); return p
        return None
    async def transition_profile(pid, *, expected_state, new_state, patch=None):
        for p in state["profiles"]:
            if p["id"] == pid and p.get("state") == expected_state:
                p.update(patch or {}); p["state"] = new_state
                state["writes"].append(("transition", pid, new_state))
                return True
        return False

    for name, fn in (("find_profile_by_bundle", find_by_bundle),
                     ("latest_event", latest_event),
                     ("count_events_with_fingerprint", count_fp),
                     ("insert_event", insert_event),
                     ("bump_event_delivery", bump),
                     ("update_profile", update_profile),
                     ("transition_profile", transition_profile)):
        monkeypatch.setattr(cb.db_reg, name, fn)
    return state


@pytest.mark.asyncio
async def test_the_profile_is_resolved_from_the_bundle_sid_alone(world):
    profile, why = await cb.resolve_profile(events.parse_callback(form()))
    assert why == cb.ACCEPTED and profile["id"] == "p1"


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_payload_is_never_trusted(world):
    """The payload carries no tenant of ours and is never asked for one -- a forged
    tenant id has nothing to attach to."""
    parsed = events.parse_callback({**form(), "TenantId": OTHER_TENANT,
                                    "tenant_id": OTHER_TENANT})
    assert "tenant_id" not in parsed
    profile, why = await cb.resolve_profile(parsed)
    assert profile["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_an_unknown_bundle_sid_resolves_to_nothing(world):
    profile, why = await cb.resolve_profile(events.parse_callback(form(bundle="BU_nope")))
    assert profile is None and why == cb.UNKNOWN_BUNDLE


@pytest.mark.asyncio
async def test_a_payload_with_no_bundle_sid_resolves_to_nothing(world):
    profile, why = await cb.resolve_profile({"bundle_status": "twilio-approved"})
    assert profile is None and why == cb.NO_BUNDLE_SID


@pytest.mark.asyncio
async def test_a_callback_from_a_different_account_is_refused(world):
    """A validly-signed callback from ANOTHER account must not move this tenant's
    profile -- the one way a signed request can still be the wrong request."""
    profile, why = await cb.resolve_profile(
        events.parse_callback(form(account=OTHER_SUB)))
    assert why == cb.ACCOUNT_MISMATCH
    assert world["profiles"][0]["state"] == st.PENDING_REVIEW


# ── the ledger ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_first_callback_creates_one_event(world):
    parsed = events.parse_callback(form(status="twilio-approved"))
    r = await cb.record_event(profile=world["profiles"][0], params=parsed,
                              signature_valid=True)
    assert r["action"] == events.NEW_OCCURRENCE and r["occurrence"] == 1
    assert len(world["events"]) == 1
    e = world["events"][0]
    assert e["signature_valid"] is True and e["bundle_status"] == "twilio-approved"
    assert e["tenant_id"] == TENANT and e["regulatory_profile_id"] == "p1"


@pytest.mark.asyncio
async def test_an_exact_duplicate_increments_delivery_count_without_a_new_row(world):
    parsed = events.parse_callback(form())
    await cb.record_event(profile=world["profiles"][0], params=parsed,
                          signature_valid=True)
    r = await cb.record_event(profile=world["profiles"][0], params=parsed,
                              signature_valid=True)
    assert r["action"] == events.REDELIVERY
    assert len(world["events"]) == 1
    assert world["events"][0]["delivery_count"] == 2


@pytest.mark.asyncio
async def test_the_same_status_after_an_intermediate_one_is_a_new_occurrence(world):
    """pending-review -> rejected -> corrected -> pending-review. The second
    pending-review is a real transition and must not be collapsed."""
    p = world["profiles"][0]
    await cb.record_event(profile=p, params=events.parse_callback(form("pending-review")),
                          signature_valid=True)
    await cb.record_event(profile=p, params=events.parse_callback(
        form("twilio-rejected", failure="address invalid")), signature_valid=True)
    r = await cb.record_event(profile=p,
                              params=events.parse_callback(form("pending-review")),
                              signature_valid=True)
    assert r["action"] == events.NEW_OCCURRENCE and r["occurrence"] == 2
    assert [e["bundle_status"] for e in world["events"]] == [
        "pending-review", "twilio-rejected", "pending-review"]


@pytest.mark.asyncio
async def test_a_changed_failure_reason_is_preserved_as_a_new_event(world):
    p = world["profiles"][0]
    await cb.record_event(profile=p, params=events.parse_callback(
        form("twilio-rejected", failure="address invalid")), signature_valid=True)
    await cb.record_event(profile=p, params=events.parse_callback(
        form("twilio-rejected", failure="address invalid; CRN not found")),
        signature_valid=True)
    assert len(world["events"]) == 2
    assert [e["failure_reason"] for e in world["events"]] == [
        "address invalid", "address invalid; CRN not found"]


@pytest.mark.asyncio
async def test_the_raw_body_is_never_stored(world):
    parsed = events.parse_callback({**form(), "Email": "owner@dani.ie",
                                    "Junk": "should-not-persist"})
    await cb.record_event(profile=world["profiles"][0], params=parsed,
                          signature_valid=True)
    stored = world["events"][0]
    for forbidden in ("raw_envelope", "raw_body", "payload"):
        assert forbidden not in stored
    assert "should-not-persist" not in str(stored)


# ── applying the status ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_twilio_approved_moves_the_profile_to_approved(world):
    r = await cb.apply_status(profile=world["profiles"][0],
                              provider_status="twilio-approved")
    assert r["outcome"] == st.APPLIED and r["state"] == st.APPROVED
    p = world["profiles"][0]
    assert p["state"] == st.APPROVED and p["bundle_status"] == "twilio-approved"
    assert p["decided_at"]


@pytest.mark.asyncio
async def test_twilio_rejected_moves_the_profile_to_rejected(world):
    r = await cb.apply_status(profile=world["profiles"][0],
                              provider_status="twilio-rejected",
                              failure_reason="address invalid")
    assert r["state"] == st.REJECTED
    assert world["profiles"][0]["failure_reason"] == "address invalid"


@pytest.mark.asyncio
async def test_provisionally_approved_keeps_waiting(world):
    r = await cb.apply_status(profile=world["profiles"][0],
                              provider_status="provisionally-approved")
    p = world["profiles"][0]
    assert p["state"] == st.PENDING_REVIEW
    assert p["state"] != st.APPROVED
    assert p["bundle_status"] == "provisionally-approved", "stored verbatim"
    assert "not treated as approved" in r["note"]


@pytest.mark.asyncio
async def test_an_unknown_provider_status_stores_the_value_and_moves_nothing(world):
    r = await cb.apply_status(profile=world["profiles"][0],
                              provider_status="twilio-something-new")
    p = world["profiles"][0]
    assert r["outcome"] == "unmapped"
    assert p["state"] == st.PENDING_REVIEW, "no destructive transition"
    assert p["bundle_status"] == "twilio-something-new"
    assert p["failure_code"].startswith("unknown_provider_status:")


@pytest.mark.asyncio
async def test_a_replayed_callback_is_idempotent(world):
    await cb.apply_status(profile=world["profiles"][0], provider_status="twilio-approved")
    p = world["profiles"][0]
    again = await cb.apply_status(profile=p, provider_status="twilio-approved")
    assert again["outcome"] == st.NO_CHANGE
    assert p["state"] == st.APPROVED


@pytest.mark.asyncio
async def test_a_late_callback_cannot_drag_an_approved_profile_back(world):
    await cb.apply_status(profile=world["profiles"][0], provider_status="twilio-approved")
    p = world["profiles"][0]
    r = await cb.apply_status(profile=p, provider_status="pending-review")
    assert r["outcome"] == st.ILLEGAL
    assert p["state"] == st.APPROVED
    assert p["bundle_status"] == "pending-review", "the provider's value is still recorded"


@pytest.mark.asyncio
async def test_an_illegal_transition_is_logged_without_the_failure_reason(world, caplog):
    await cb.apply_status(profile=world["profiles"][0], provider_status="twilio-approved")
    with caplog.at_level("WARNING"):
        await cb.apply_status(profile=world["profiles"][0],
                              provider_status="pending-review",
                              failure_reason="Ann Byrne at ann@dani.ie is not a director")
    assert "ann@dani.ie" not in caplog.text
    assert "Refused illegal regulatory transition" in caplog.text
