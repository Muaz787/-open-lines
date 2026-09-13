"""Regulatory compliance API + Twilio status callback (W9G Stages N, U).

TWO ROUTERS, DELIBERATELY. The tenant-facing router derives the tenant from the
authenticated bearer token via the repository's existing `require_tenant_owner`
dependency, so no customer-facing route can ever name another tenant. The webhook
router is unauthenticated by nature and is protected by Twilio's signature instead.
"""
from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from db import regulatory as db_reg
from db.supabase import get_client
from services import business_country, regulatory_callback as cb
from services import regulatory_engine as engine
from services import regulatory_filing as filing
from services import regulatory_events as reg_events
from services import regulatory_ireland as ie_ux
from services import regulatory_requirements as rq
from services import regulatory_state as st
from services.security import require_tenant_owner

logger = logging.getLogger(__name__)

# Every route carries {tenant_id} and the dependency refuses unless the bearer token
# belongs to it. The path parameter is never authority on its own.
router = APIRouter(prefix="/regulatory", tags=["regulatory"],
                   dependencies=[Depends(require_tenant_owner)])

webhook_router = APIRouter(prefix="/webhooks/twilio", tags=["regulatory-webhooks"])

_STATUS_FOR = {
    engine.MISSING_COUNTRY: 409,
    engine.INVALID_CUSTOMER_DATA: 422,
    engine.ADDRESS_VALIDATION_FAILED: 422,
    engine.OWNERSHIP_CONFLICT: 409,
    engine.REGULATORY_IDENTITY_CONFLICT: 409,
    engine.UNSUPPORTED_DOCUMENT_REQUIREMENT: 501,
    engine.UNSUPPORTED_REQUIREMENT_FIELD: 501,
    engine.REQUIREMENTS_CHANGED: 409,
    engine.NOT_READY: 409,
    engine.PROVIDER_UNAVAILABLE: 503,
    engine.SUBMISSION_OUTCOME_UNKNOWN: 503,
    rq.NOT_FOUND: 404,
    rq.AMBIGUOUS: 409,
    rq.UNAVAILABLE: 503,
}


async def _tenant(tenant_id: str) -> dict:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return rows[0]


def _fail(result: dict) -> None:
    """Turn an engine outcome into an HTTP error, preserving the distinction."""
    status = _STATUS_FOR.get(result.get("status"), 400)
    payload = {k: v for k, v in result.items()
               if k in ("status", "detail", "missing", "blockers", "next_requirement",
                        "count", "regulation_sid")}
    raise HTTPException(status_code=status, detail=payload)


# ── country ────────────────────────────────────────────────────────────────

@router.post("/{tenant_id}/business-country")
async def confirm_business_country(tenant_id: str, body: dict):
    """Explicitly confirm the compliance country. Never inferred from anything."""
    result = await business_country.confirm(
        tenant_id, str((body or {}).get("business_country_code") or ""))
    if result["status"] == business_country.INVALID:
        raise HTTPException(status_code=422, detail=result)
    if result["status"] in (business_country.BLOCKED_REGULATORY,
                            business_country.BLOCKED_REGULATED_NUMBER):
        raise HTTPException(status_code=409, detail=result)
    if result["status"] == business_country.NOT_FOUND:
        raise HTTPException(status_code=404, detail=result)
    return result


# ── requirements ───────────────────────────────────────────────────────────

@router.get("/{tenant_id}/requirements")
async def get_requirements(tenant_id: str, country: str | None = None,
                           number_type: str = engine.DEFAULT_NUMBER_TYPE,
                           end_user_type: str = engine.DEFAULT_END_USER_TYPE):
    tenant = await _tenant(tenant_id)
    result = await engine.requirements_for(tenant, iso_country=country,
                                          number_type=number_type,
                                          end_user_type=end_user_type)
    if not result["ok"]:
        _fail(result)
    reqs = result["requirements"]
    return {
        "regulation_sid": reqs.regulation_sid,
        "regulation_name": reqs.friendly_name,
        "iso_country": reqs.iso_country,
        "number_type": reqs.number_type,
        "end_user_type": reqs.end_user_type,
        "requirements_fingerprint": result["fingerprint"],
        "fields": result["fields"],
        "documents": [{
            "requirement_name": d.requirement_name, "name": d.name,
            "accepted_type": d.accepted_type,
            "fields": [f.name for f in d.fields],
            "satisfied_by_address": d.satisfied_by_address_sids,
            "description": d.description,
        } for d in reqs.documents],
        "unresolved_declarations": list(ie_ux.UNRESOLVED_DECLARATION_FIELDS),
    }


# ── status ─────────────────────────────────────────────────────────────────

@router.get("/{tenant_id}/status")
async def get_status(tenant_id: str):
    tenant = await _tenant(tenant_id)
    profiles = await db_reg.list_profiles(tenant_id)
    return {
        "business_country_code": tenant.get("business_country_code"),
        "profiles": [{
            "id": p["id"], "iso_country": p.get("iso_country"),
            "number_type": p.get("number_type"),
            "state": p.get("state"), "bundle_status": p.get("bundle_status"),
            "evaluation_status": p.get("evaluation_status"),
            "regulation_sid": p.get("regulation_sid"),
            "submitted_at": p.get("submitted_at"),
            "decided_at": p.get("decided_at"),
            # SIDs and failure_reason are deliberately NOT returned to a customer
            # route: provider identifiers are operational, and failure_reason can
            # quote submitted identity.
            "has_bundle": bool(p.get("bundle_sid")),
        } for p in profiles],
    }


# ── the workflow ───────────────────────────────────────────────────────────

@router.post("/{tenant_id}/address")
async def create_address(tenant_id: str, body: dict):
    tenant = await _tenant(tenant_id)
    result = await engine.ensure_address(
        tenant, submitted=(body or {}).get("address") or {},
        tenant_location_id=(body or {}).get("tenant_location_id") or None)
    if not result["ok"]:
        _fail(result)
    addr = result["address"] or {}
    return {"status": "ok", "validated": bool(addr.get("validated")),
            "regulatory_address_id": addr.get("id"),
            "provider_locality": addr.get("provider_locality"),
            "reused": result.get("reused", False)}


@router.post("/{tenant_id}/details")
async def submit_details(tenant_id: str, body: dict):
    """Advance this tenant's filing to the point where it is ready to submit.

    W9I-D TURNED THIS INTO A WRAPPER. It used to take an `attributes` bag from the
    caller and hand it to prepare_profile, which meant a browser could put values
    in front of the provider that differed from the ones the customer authorised,
    and could drive the resource-creation sequence itself. Collection now belongs
    to /verification (W9I-C) and sequencing to services.regulatory_filing, so this
    keeps its path and its shape but no longer chooses anything: the facts come
    from canonical storage and the ordering from the orchestrator.

    `attributes` in the body is deliberately IGNORED rather than rejected -- it was
    never storage, nothing in this repository sends it, and a 4xx would be a worse
    answer than doing the right thing. Nothing a caller puts there can reach the
    provider.
    """
    result = await filing.advance(
        tenant_id,
        regulatory_address_id=str((body or {}).get("regulatory_address_id") or ""))

    # An unresolved declaration is NOT a client error: the customer's answers were
    # accepted and stored, and what remains is a compliance decision on OUR side.
    # 200 with an explicit status says that honestly; a 4xx would tell them to fix
    # something they cannot fix.
    if result["status"] == engine.UNRESOLVED_ISV_DECLARATION:
        profile = result.get("profile") or {}
        return {"status": engine.UNRESOLVED_ISV_DECLARATION,
                "details_stored": True,
                "profile_id": profile.get("id"),
                "state": profile.get("state"),
                "has_bundle": False,
                "unresolved_declarations": result.get("unresolved_declarations", []),
                "blocked_on": "openlines",
                "message": "Your details are saved. We are confirming one regulatory "
                           "declaration with our telephony provider before filing."}
    if not result["ok"]:
        _fail(result)
    profile = result["profile"]
    return {"status": "ok", "profile_id": profile["id"], "state": profile.get("state"),
            "details_stored": True,
            "has_bundle": bool(result.get("bundle_sid")),
            "has_supporting_document": bool(result.get("supporting_document_sid")),
            "unresolved_declarations": result.get("unresolved_declarations", [])}


@router.post("/{tenant_id}/evaluate")
async def evaluate_profile(tenant_id: str, body: dict):
    """Prepare and evaluate, stopping short of filing.

    Also a wrapper now. It used to take a caller-chosen profile_id and evaluate
    whatever that named, which let a client evaluate one profile and submit
    another. The orchestrator resolves the profile from the tenant and premises.
    """
    result = await filing.advance(
        tenant_id,
        regulatory_address_id=str((body or {}).get("regulatory_address_id") or ""))
    if not result.get("ok"):
        _fail(result)
    profile = result.get("profile") or {}
    return {"status": "ok", "state": profile.get("state") or result.get("state"),
            "reached": result.get("reached"),
            "evaluation_status": profile.get("evaluation_status")}


@router.post("/{tenant_id}/submit")
async def submit_for_review(tenant_id: str, body: dict):
    """File this tenant's Bundle for regulatory review.

    Submission is a separate, explicit act -- the orchestrator does not do it
    unless asked -- and every gate still applies inside submit_profile: the
    authorisation is re-checked immediately before the provider call, not trusted
    from whenever the resources were built.
    """
    result = await filing.advance(
        tenant_id,
        regulatory_address_id=str((body or {}).get("regulatory_address_id") or ""),
        submit=True)
    if not result.get("ok"):
        _fail(result)
    return {"status": "ok", "state": result.get("state"),
            "bundle_status": result.get("bundle_status"),
            "already_submitted": result.get("already_submitted", False),
            "recovered_from_unknown": result.get("recovered_from_unknown", False)}


@webhook_router.post("/regulatory")
async def twilio_regulatory_callback(
    request: Request,
    x_twilio_signature: Annotated[str | None, Header()] = None,
):
    """Twilio Bundle status callback.

    The signed URL is reconstructed from the CONFIGURED public backend URL, not from
    request.url: behind Railway's proxy the request's apparent scheme and host are not
    what Twilio signed. routers/payments.py does the same for Square's webhook.
    """
    raw = await request.form()
    params = {k: str(v) for k, v in raw.items()}
    parsed = reg_events.parse_callback(params)

    profile, why = await cb.resolve_profile(parsed)
    if profile is None:
        # Unknown or unnamed bundle: no signing token to check against, and nothing
        # to mutate. 403 without saying which check failed.
        logger.warning("Regulatory callback rejected (%s)", why)
        raise HTTPException(status_code=403, detail="Forbidden")

    # The credential is tenant-bound: it is the sub-account token belonging to the
    # tenant that owns THIS bundle, looked up from the profile, never from the
    # payload. The parent token is offered only as the second candidate because
    # Twilio's documentation does not say which one signs a sub-account resource's
    # callback -- see regulatory_callback.select_credential.
    rows = (get_client().table("tenants").select("twilio_auth_token")
            .eq("id", profile.get("tenant_id")).limit(1).execute().data or [])
    subaccount_token = str((rows[0] if rows else {}).get("twilio_auth_token") or "")
    url = engine.callback_url()
    credential = cb.select_credential(
        url=url, params=params, signature=x_twilio_signature or "",
        subaccount_token=subaccount_token,
        parent_token=os.environ.get("TWILIO_AUTH_TOKEN", ""))
    if credential == cb.CRED_NONE:
        # No ledger row, no mutation, and no hint about which part mismatched.
        logger.warning("Regulatory callback signature verification failed")
        raise HTTPException(status_code=403, detail="Forbidden")

    if why == cb.ACCOUNT_MISMATCH:
        logger.error("Regulatory callback account mismatch — refusing")
        raise HTTPException(status_code=403, detail="Forbidden")

    ledger = await cb.record_event(profile=profile, params=parsed, signature_valid=True)
    applied = await cb.apply_status(profile=profile,
                                   provider_status=parsed.get("bundle_status", ""),
                                   failure_reason=parsed.get("failure_reason") or None)
    logger.info("Regulatory callback applied for profile %s: %s -> %s (%s, signed "
                "with the %s credential)", profile.get("id"), profile.get("state"),
                applied.get("state"), ledger.get("action"), credential)

    # ── THE FAST WAKE-UP, AND ONLY A WAKE-UP (W9I-H.AUTO.1) ───────────────
    # The lifecycle is told to look again; it is NOT told what it will find.
    # advance() re-reads the Bundle from Twilio with the tenant's own credentials
    # before it spends money or hands out free service, so this payload can never
    # by itself cause a +353 to be bought. Never raises: a callback must still be
    # acknowledged even if the next step cannot run yet, or Twilio retries it.
    from services import ireland_lifecycle
    await ireland_lifecycle.wake(str(profile.get("tenant_id") or ""),
                                 source="callback")
    return {"status": "ok", "event": ledger["action"], "state": applied["state"]}
