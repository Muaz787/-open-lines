"""Twilio regulatory status-callback handling (W9G Stages N-Q).

── SIGNATURE VERIFICATION AND THE PROXY PROBLEM ───────────────────────────────
Twilio signs the EXACT URL it posted to, plus the sorted form parameters. Behind
Railway's proxy, `request.url` is not that URL: the proxy terminates TLS and can
present http, an internal host, or a rewritten path. Verifying against `request.url`
therefore fails intermittently and, worse, could be "fixed" by disabling verification.

So the URL is reconstructed from the CONFIGURED public backend URL plus the known
route path -- exactly the pattern routers/payments.py already uses for Square's
webhook, which has the same property. The value that Twilio was given as the
status_callback is the same constant (regulatory_engine.callback_url()), so the two
cannot drift.

── WHAT AN INVALID CALLBACK GETS ──────────────────────────────────────────────
403, no ledger row, no profile mutation, and a log line that says a signature failed
without saying which part of it did. An attacker learning "the host was wrong but the
body was fine" would be learning how to forge the next one.
"""
from __future__ import annotations

import logging

from db import regulatory as db_reg
from services import regulatory_events as events
from services import regulatory_state as st

logger = logging.getLogger(__name__)

ACCEPTED = "accepted"
BAD_SIGNATURE = "bad_signature"
NOT_CONFIGURED = "not_configured"
UNKNOWN_BUNDLE = "unknown_bundle"
ACCOUNT_MISMATCH = "account_mismatch"
NO_BUNDLE_SID = "no_bundle_sid"


#: Which credential validated a callback. Recorded so the open question below
#: answers itself on first contact instead of needing another investigation.
CRED_SUBACCOUNT = "subaccount"
CRED_PARENT = "parent"
CRED_NONE = ""


def verify_signature(*, url: str, params: dict, signature: str,
                     auth_token: str) -> bool:
    """Twilio's own RequestValidator against ONE named credential. Never raises."""
    if not signature or not auth_token:
        return False
    try:
        from twilio.request_validator import RequestValidator
        return bool(RequestValidator(auth_token).validate(url, params, signature))
    except Exception as e:
        logger.error("Signature validation raised: %s", type(e).__name__)
        return False


def select_credential(*, url: str, params: dict, signature: str,
                      subaccount_token: str, parent_token: str = "") -> str:
    """Which of OUR OWN tokens signed this callback -- or CRED_NONE.

    ── AN OPEN QUESTION, HANDLED EXPLICITLY RATHER THAN ASSUMED ──────────────
    W9G asserted Twilio signs a sub-account-owned Bundle's callback with the
    SUB-ACCOUNT auth token. W9G.1 went back to Twilio's security documentation to
    confirm it and found the page documents the HMAC-SHA1 scheme and the
    URL-plus-sorted-params construction but says NOTHING about which token signs a
    request concerning a sub-account-owned resource. So the assertion was
    unverified.

    Both candidates are OpenLines-controlled credentials for the same organisation,
    and which one Twilio picks changes nothing about who is allowed to move the
    profile -- cross-account abuse is blocked separately by comparing the callback's
    AccountSid with the profile's provider_account_sid. So the safe handling is to
    accept either of our own tokens and RECORD WHICH ONE MATCHED, rather than guess
    one and take a production outage on the first real callback, or accept anything.

    This does not widen what is accepted beyond credentials we already hold: a
    third party's signature matches neither and is refused. The sub-account is tried
    first because it is the more specific, tenant-bound credential.
    """
    if not signature:
        return CRED_NONE
    if subaccount_token and verify_signature(url=url, params=params,
                                             signature=signature,
                                             auth_token=subaccount_token):
        return CRED_SUBACCOUNT
    if parent_token and verify_signature(url=url, params=params,
                                         signature=signature,
                                         auth_token=parent_token):
        logger.warning("Regulatory callback validated with the PARENT auth token, "
                       "not the sub-account token -- record this: it settles which "
                       "credential Twilio signs sub-account bundle callbacks with")
        return CRED_PARENT
    return CRED_NONE


async def resolve_profile(params: dict) -> tuple[dict | None, str]:
    """Find the profile this callback is about, from the BUNDLE SID only.

    The payload carries no tenant of ours and is never asked for one. trp_bundle_sid_key
    makes the lookup unique, so a forged tenant id has nothing to attach to.
    """
    bundle_sid = str((params or {}).get("bundle_sid") or "").strip()
    if not bundle_sid:
        return None, NO_BUNDLE_SID
    profile = await db_reg.find_profile_by_bundle(bundle_sid)
    if not profile:
        return None, UNKNOWN_BUNDLE
    incoming_account = str((params or {}).get("provider_account_sid") or "").strip()
    expected = str(profile.get("provider_account_sid") or "").strip()
    if incoming_account and expected and incoming_account != expected:
        # A validly-signed callback from a DIFFERENT account must not move this
        # tenant's profile. Cross-account bundle callbacks are the one way a signed
        # request could still be the wrong request.
        logger.error("Regulatory callback account mismatch for profile %s",
                     profile.get("id"))
        return profile, ACCOUNT_MISMATCH
    return profile, ACCEPTED


async def record_event(*, profile: dict, params: dict, signature_valid: bool) -> dict:
    """Append to the ledger using W9D's fingerprint/occurrence model.

    A redelivery of the transition that is still the latest row bumps delivery_count.
    A recurrence of a status after the bundle moved elsewhere is a NEW occurrence, so
    a legitimate second `pending-review` is never collapsed into the first. The raw
    body is never stored.
    """
    fingerprint = events.fingerprint(params)
    bundle_sid = str(params.get("bundle_sid") or "")
    latest = await db_reg.latest_event(bundle_sid)
    prior = await db_reg.count_events_with_fingerprint(bundle_sid, fingerprint)
    action, occurrence = events.decide(
        incoming_fingerprint=fingerprint,
        latest_fingerprint=str((latest or {}).get("fingerprint") or "") or None,
        prior_occurrences=prior)

    if action == events.REDELIVERY and latest:
        row = await db_reg.bump_event_delivery(
            latest["id"], int(latest.get("delivery_count") or 1) + 1)
        return {"action": action, "event": row or latest, "occurrence": occurrence,
                "fingerprint": fingerprint}

    row = await db_reg.insert_event({
        "provider": "twilio",
        "provider_account_sid": params.get("provider_account_sid") or None,
        "bundle_sid": bundle_sid,
        "bundle_status": str(params.get("bundle_status") or ""),
        "fingerprint": fingerprint, "occurrence": occurrence,
        "tenant_id": profile.get("tenant_id"),
        "regulatory_profile_id": profile.get("id"),
        "failure_reason": params.get("failure_reason") or None,
        "valid_until": params.get("valid_until") or None,
        "signature_valid": signature_valid,
        "applied": False,
    })
    return {"action": action, "event": row, "occurrence": occurrence,
            "fingerprint": fingerprint}


async def apply_status(*, profile: dict, provider_status: str,
                       failure_reason: str | None = None) -> dict:
    """Move the profile, through the one transition authority.

    Always stores the provider's value verbatim, even when it maps to nothing: an
    unmapped status is information we want, and a destructive guess is not.
    """
    target, note = st.state_for_provider_status(provider_status)
    current = str(profile.get("state") or "")
    patch: dict = {"bundle_status": str(provider_status or "")}
    if failure_reason is not None:
        patch["failure_reason"] = failure_reason

    if target is None:
        # A status Twilio added after this was written. Record it, flag it, move nothing.
        await db_reg.update_profile(profile["id"], {**patch, "failure_code": note})
        logger.error("Unmapped regulatory bundle status for profile %s: %s",
                     profile.get("id"), note)
        return {"outcome": "unmapped", "state": current, "note": note}

    outcome, reason = st.transition(current, target)
    if outcome == st.NO_CHANGE:
        await db_reg.update_profile(profile["id"], patch)
        return {"outcome": st.NO_CHANGE, "state": current, "note": note}
    if outcome == st.ILLEGAL:
        # A late or out-of-order delivery. Record the provider's status, refuse the move.
        await db_reg.update_profile(profile["id"], patch)
        logger.warning("Refused illegal regulatory transition for profile %s: %s",
                       profile.get("id"), reason)
        return {"outcome": st.ILLEGAL, "state": current, "reason": reason, "note": note}

    from datetime import datetime, timezone
    if target in (st.APPROVED, st.REJECTED):
        patch["decided_at"] = datetime.now(timezone.utc).isoformat()
    patch["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    won = await db_reg.transition_profile(profile["id"], expected_state=current,
                                         new_state=target, patch=patch)
    return {"outcome": st.APPLIED if won else "lost_race", "state": target if won else current,
            "note": note}
