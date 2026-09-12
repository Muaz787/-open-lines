"""The one server-owned operation that advances an authorised tenant toward filing
(W9I-D).

WHY THIS EXISTS
Before it, progressing a regulatory filing meant a browser calling three separate
provider-resource endpoints in the right order with the right payloads:
`/details` (which creates the EndUser, SupportingDocument and Bundle), then
`/evaluate`, then `/submit`. That is a state machine operated by a client, and a
client can operate it wrongly -- skip evaluation, submit a half-built bundle, or
re-drive the sequence with different attributes than the ones the customer
authorised. The provider resources are named humans filed with a regulator; the
sequencing is not the customer's to get right.

So there is one entry point. The caller names a tenant and a premises. It does not
name provider resources, attributes, declarations or fingerprints -- every one of
those is read from canonical storage or resolved by policy on this side.

WHAT IT DOES NOT DO
It does not submit unless the caller explicitly asks. Preparing resources and
FILING them are different acts with different consequences: the first is
reversible on our side, the second puts a business in front of a regulator. They
are therefore separate arguments, not one convenience flag defaulted to true.

It also does not buy numbers, promote anything, or start a trial. W9I-E and W9I-F
own those, and the approval that unlocks them must be verified against the
provider directly -- never inferred from a callback or from this module's output.
"""
from __future__ import annotations

import logging

from db import regulatory as db_reg
from db.supabase import get_client
from services import regulatory_engine as engine
from services import regulatory_state as st

logger = logging.getLogger(__name__)

OK = "ok"
NOT_FOUND = "not_found"

#: Where advance() stopped, for a caller that needs to know without re-deriving it.
PREPARED = "prepared"
EVALUATED = "evaluated"
SUBMITTED = "submitted"


async def _tenant(tenant_id: str) -> dict | None:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    return rows[0] if rows else None


async def _resolve_address(tenant_id: str, country: str,
                           regulatory_address_id: str) -> dict | None:
    """The premises this filing is for, always tenant-scoped.

    A caller may name one explicitly -- a multi-location tenant has several and
    each is filed separately. When it names none, and the tenant has exactly one,
    that one is used; with several, the caller must choose rather than have us
    pick a premises on their behalf.
    """
    if regulatory_address_id:
        # get_address is tenant-scoped at the query, so another tenant's id is
        # simply absent rather than accessible.
        return await db_reg.get_address(tenant_id, regulatory_address_id)
    rows = (get_client().table("tenant_regulatory_addresses").select("*")
            .eq("tenant_id", tenant_id).eq("iso_country", country)
            .order("created_at").execute().data or [])
    validated = [r for r in rows if r.get("validated")]
    return validated[0] if len(validated) == 1 else None


async def advance(tenant_id: str, *, regulatory_address_id: str = "",
                  submit: bool = False) -> dict:
    """Move one tenant's regulatory filing as far as it can safely go.

    Returns the engine's own result shape, plus `reached` naming the furthest
    stage completed. Every refusal is an engine status the customer error contract
    already knows how to translate -- this module invents no new vocabulary for
    the customer, because a second vocabulary is a second thing to keep in sync.
    """
    tenant = await _tenant(tenant_id)
    if not tenant:
        return {"ok": False, "status": NOT_FOUND, "detail": "tenant_not_found"}
    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not country:
        return {"ok": False, "status": engine.MISSING_COUNTRY}

    address = await _resolve_address(tenant_id, country, regulatory_address_id)
    if not address:
        return {"ok": False, "status": engine.NOT_READY,
                "detail": "address_not_submitted" if not regulatory_address_id
                          else "address_not_on_this_account"}

    # ── PREPARE ───────────────────────────────────────────────────────────
    # attributes={} on purpose, and this is the load-bearing line of the module.
    # prepare_profile merges what it is given over what is stored and then works
    # from the STORED result; passing nothing means the filing is built from the
    # facts the customer authorised, and there is no request payload that can put
    # a different value in front of the provider. The declaration is resolved by
    # policy inside prepare_profile, from our architecture, not from any caller.
    prepared = await engine.prepare_profile(
        tenant, attributes={},
        tenant_location_id=address.get("tenant_location_id") or None)
    if not prepared.get("ok"):
        # Includes every Gate 1 refusal -- no authorisation, revoked, stale facts,
        # changed requirements -- each of which leaves the provider untouched.
        return {**prepared, "reached": ""}

    profile = prepared.get("profile") or {}

    # ── EVALUATE ──────────────────────────────────────────────────────────
    # Structural compliance, checked before asking a human to review it. A
    # provider error here is not noncompliance and does not stop the filing from
    # being retried later, so it is reported without discarding the work.
    evaluated = await engine.evaluate_profile(tenant, profile=profile)
    if not evaluated.get("ok"):
        return {**evaluated, "reached": PREPARED, "profile": profile}
    if not evaluated.get("compliant"):
        # The customer has something to fix. Submitting anyway would spend a real
        # regulatory review on a filing we already know is incomplete.
        return {"ok": False, "status": engine.NOT_READY,
                "detail": "evaluation_noncompliant",
                "failed_requirements": evaluated.get("failed_requirements", []),
                "reached": EVALUATED, "profile": profile}

    if not submit:
        return {"ok": True, "status": engine.OK, "reached": EVALUATED,
                "profile": profile, "state": evaluated.get("state")}

    # ── SUBMIT ────────────────────────────────────────────────────────────
    # Re-read the profile: evaluate_profile transitioned it, and submit_profile
    # fences on the state it is actually in. Handing it the pre-evaluation copy
    # would make the CAS fail against a row that is perfectly fine.
    fresh = await db_reg.get_profile(tenant_id, str(profile["id"])) or profile
    submitted = await engine.submit_profile(tenant, profile=fresh)
    return {**submitted, "reached": SUBMITTED if submitted.get("ok") else EVALUATED,
            "profile": fresh}


# ── the customer-visible view of where a filing stands ─────────────────────
#
# DERIVED, never a second stored state. tenant_regulatory_profiles.state is the
# authority; this is a translation of it for a person, and translating in one
# place is what stops a dashboard and an email from describing the same filing
# differently.

PREPARING_REGISTRATION = "PREPARING_REGISTRATION"
READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
SUBMITTED_STATE = "SUBMITTED"
UNDER_REVIEW = "UNDER_REVIEW"
ACTION_REQUIRED = "ACTION_REQUIRED"
APPROVED = "APPROVED"

#: profile state -> (customer state, message, whether the customer must act)
_CUSTOMER_VIEW: dict[str, tuple[str, str, bool]] = {
    st.NOT_STARTED: (PREPARING_REGISTRATION,
                     "We are getting your registration ready.", False),
    st.DETAILS_REQUIRED: (ACTION_REQUIRED,
                          "Some of your business information needs attention "
                          "before we can register your number.", True),
    st.ADDRESS_VALIDATION_FAILED: (ACTION_REQUIRED,
                                   "Your business address could not be verified. "
                                   "Please check it and try again.", True),
    st.READY_TO_SUBMIT: (READY_FOR_SUBMISSION,
                         "Your information is ready to be submitted for "
                         "registration.", False),
    st.SUBMITTING: (SUBMITTED_STATE,
                    "We are submitting your registration now.", False),
    st.PENDING_REVIEW: (UNDER_REVIEW,
                        "Your registration has been submitted and is being "
                        "reviewed. This usually takes a few business days.", False),
    st.MORE_INFORMATION_REQUIRED: (ACTION_REQUIRED,
                                   "The regulator needs more information before "
                                   "your number can be approved.", True),
    st.APPROVED: (APPROVED,
                  "Your business registration was approved. We are setting up "
                  "your number.", False),
    st.REJECTED: (ACTION_REQUIRED,
                  "Your registration was not accepted. Please review your "
                  "business details and submit again.", True),
    # Past this point W9I-E/F own the story, and the customer is told about the
    # number rather than about a filing.
    st.NUMBER_PROVISIONING: (APPROVED,
                             "Your business registration was approved. We are "
                             "setting up your number.", False),
    st.ACTIVE: (APPROVED, "Your number is active.", False),
    st.FAILED: (ACTION_REQUIRED,
                "Something went wrong with your registration. Our team is "
                "looking into it.", False),
}


def customer_status(profile: dict | None) -> dict:
    """How a filing looks to the person waiting on it.

    Carries no Bundle SID, no EndUser SID, no provider status string and no
    provider error text. `failure_reason` is deliberately excluded even though it
    would often be the most useful field: Twilio's rejection text can quote the
    submitted identity back, and a customer-facing surface is exactly where that
    must not appear. An operator reads it on the admin surface instead.
    """
    if not profile:
        return {"status": PREPARING_REGISTRATION,
                "message": "We have not started your registration yet.",
                "action_required": False, "submitted": False}
    state = str(profile.get("state") or "")
    status, message, action = _CUSTOMER_VIEW.get(
        state, (PREPARING_REGISTRATION, "We are getting your registration ready.",
                False))
    return {
        "status": status,
        "message": message,
        "action_required": action,
        # True once it has actually been filed -- so no screen can say "submitted"
        # about a filing that is still being built.
        "submitted": state in (st.PENDING_REVIEW, st.MORE_INFORMATION_REQUIRED,
                               st.APPROVED, st.REJECTED, st.NUMBER_PROVISIONING,
                               st.ACTIVE),
        "approved": state in (st.APPROVED, st.NUMBER_PROVISIONING, st.ACTIVE),
    }


def is_mapped(state: str) -> bool:
    return str(state or "") in _CUSTOMER_VIEW
