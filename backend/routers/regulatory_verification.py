"""The customer-facing Ireland verification experience (W9I-C).

WHY THIS IS A SEPARATE ROUTER
`routers/regulatory.py` already collects details -- but its `/details` route calls
`engine.prepare_profile`, which creates the EndUser, the SupportingDocument and
the Bundle. Those are the first provider IDENTITY resources, and creating one is
the boundary W9I calls Gate 1: after it, a real regulatory identity exists at
Twilio carrying a real person's name. Everything before it is reversible by
deleting rows.

The customer collection flow must not be able to cross that line, and "must not"
is worth making structural rather than remembering. This module imports no
function that creates a provider identity: `prepare_profile`, `resolve_end_user`,
`ensure_supporting_document`, `ensure_bundle` and `ensure_item_assignments` appear
nowhere in it, and a test asserts that. The only provider write reachable from
here is Address validation, which creates no identity -- an Address is a postal
fact, not a person -- and which the authorisation fingerprint deliberately
excludes from its digest.

W9I-D owns filing. This router stops at "ready to file" and says so.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from db import regulatory as db_reg
from db.supabase import get_client
from services import onboarding_lifecycle as lifecycle_ob
from services import regulatory_authorization as auth
from services import regulatory_customer_errors as cx
from services import regulatory_engine as engine
from services import regulatory_ireland as ie_ux
from services import regulatory_review as review
from services.security import authenticated_tenant_user, require_tenant_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regulatory/{tenant_id}/verification",
                   tags=["regulatory-verification"],
                   dependencies=[Depends(require_tenant_owner)])

# The customer answers these. The declaration fields are NOT here: W9G.3 settled
# them from our provider relationship, they are statements about OpenLines rather
# than about the customer, and a customer cannot authorise a claim they never
# made. A payload naming one is refused rather than filtered, so an attempt is
# visible instead of silently ignored.
CUSTOMER_DETAIL_FIELDS = (
    "business_name", "business_website", "business_registration_number",
    "authorized_rep_first_name", "authorized_rep_last_name", "authorized_rep_email",
)

#: Fields the SYSTEM owns. Naming any of them in a request body is refused.
SYSTEM_OWNED_FIELDS = (
    "business_identity", "is_subassigned", "requirements_fingerprint",
    "authorized_at", "authorized_details_fingerprint", "authorization_fingerprint",
    "collected_at", "provider_account_sid", "address_sid", "end_user_sid",
    "bundle_sid", "supporting_document_sid",
)

CUSTOMER_ADDRESS_FIELDS = ("street", "street_secondary", "city", "region", "postal_code")


def _fail(status: str, result: dict | None = None) -> None:
    """Every refusal the customer sees comes through here, or it does not ship."""
    http, payload = cx.for_status(status, result=result)
    raise HTTPException(status_code=http, detail=payload)


async def _tenant(tenant_id: str) -> dict:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return rows[0]


def _country(tenant: dict) -> str:
    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not country:
        _fail(engine.MISSING_COUNTRY)
    return country


def _reject_system_fields(body: dict) -> None:
    named = [f for f in SYSTEM_OWNED_FIELDS if f in (body or {})]
    if named:
        logger.warning("Regulatory verification payload named system-owned fields: %s", named)
        raise HTTPException(status_code=422, detail={
            "status": "system_owned_field",
            "message": "Some values in this request are set by OpenLines and "
                       "cannot be supplied here.",
            "action_required": False,
            "fields": named,
        })


async def _requirements_fingerprint(tenant: dict, country: str) -> str:
    """The provider's current requirement shape, or "" when it cannot be reached.

    An outage must not block a customer from reviewing and authorising facts they
    can plainly see. Empty binds to empty in the review token, so a review taken
    during an outage cannot later be redeemed against a known requirement shape.
    """
    result = await engine.requirements_for(tenant, iso_country=country)
    return str(result.get("fingerprint") or "") if result.get("ok") else ""


# ── 1. what we need, and why ───────────────────────────────────────────────

@router.get("/requirements")
async def customer_requirements(tenant_id: str):
    """The form to render, decided by the provider's live Regulation.

    The field list is NOT defined here and must never be: Twilio can change what
    Ireland requires, and a hardcoded frontend list would keep collecting the old
    shape and fail at filing. The frontend owns presentation; this owns truth.
    """
    tenant = await _tenant(tenant_id)
    country = _country(tenant)
    result = await engine.requirements_for(tenant, iso_country=country)
    if not result["ok"]:
        _fail(result["status"], result)

    reqs = result["requirements"]
    # Only fields the CUSTOMER answers. The declaration fields are filtered out
    # of the form rather than shown as disabled: a customer asked to look at a
    # field they cannot fill learns nothing from it.
    fields = [f for f in result["fields"] if f.get("source") == ie_ux.CUSTOMER_SUPPLIED]
    return {
        "iso_country": reqs.iso_country,
        "number_type": reqs.number_type,
        "end_user_type": reqs.end_user_type,
        # Why any of this is being asked, in the regulator's own framing.
        "explanation": (
            "Phone numbers in this country are regulated. Before a number can be "
            "issued, the telecoms regulator requires the registered details of the "
            "business it belongs to, a named representative, and a verified "
            "business address in that country."),
        "fields": fields,
        "documents": [{"name": d.name, "description": d.description}
                      for d in reqs.documents],
        # NOT returned: regulation_sid, provider account identifiers, claim
        # markers, requirement fingerprints, provider error text. Those are
        # operational facts about our provider integration; see Stage C.
    }


# ── 2. what we already hold ────────────────────────────────────────────────

@router.get("/state")
async def verification_state(tenant_id: str):
    """Everything needed to resume, from canonical storage only.

    A refresh, a new device or a back button all land here, so the forms
    repopulate from what the server actually holds rather than from anything the
    browser kept. Never invents a value it does not have.
    """
    tenant = await _tenant(tenant_id)
    country = _country(tenant)
    details = await db_reg.get_business_details(tenant_id, country) or {}
    addresses = await _tenant_addresses(tenant_id, country)

    authorized = []
    for addr in addresses:
        check = await engine.check_authorization(
            tenant_id, iso_country=country,
            end_user_type=engine.DEFAULT_END_USER_TYPE,
            address_row=addr, details=details)
        authorized.append({
            "regulatory_address_id": addr["id"],
            "authorized": check["status"] == engine.OK,
            "status": cx.for_status(check["status"])[1]["status"]
                      if check["status"] != engine.OK else "authorized",
        })

    return {
        "iso_country": country,
        "onboarding_state": tenant.get("onboarding_state"),
        "details": {f: details.get(f) for f in CUSTOMER_DETAIL_FIELDS},
        "details_complete": all(str(details.get(f) or "").strip()
                                for f in CUSTOMER_DETAIL_FIELDS),
        "addresses": [_public_address(a) for a in addresses],
        "authorizations": authorized,
        "next_step": _next_step(details, addresses, authorized),
        # W9I-C stops before filing. Nothing here implies anything was submitted.
        "filing_submitted": False,
    }


async def _tenant_addresses(tenant_id: str, country: str) -> list[dict]:
    rows = (get_client().table("tenant_regulatory_addresses").select("*")
            .eq("tenant_id", tenant_id).eq("iso_country", country)
            .order("created_at").execute().data or [])
    return rows


def _public_address(a: dict) -> dict:
    """An address as the customer may see it. The provider's AddressSid stays here."""
    return {
        "regulatory_address_id": a.get("id"),
        "street": a.get("street"),
        "street_secondary": a.get("street_secondary"),
        "city": a.get("city"),
        "region": a.get("region"),
        "postal_code": a.get("postal_code"),
        "iso_country": a.get("iso_country"),
        "validated": bool(a.get("validated")),
        "tenant_location_id": a.get("tenant_location_id"),
    }


def _next_step(details: dict, addresses: list[dict], authorized: list[dict]) -> str:
    if not all(str(details.get(f) or "").strip() for f in CUSTOMER_DETAIL_FIELDS):
        return cx.STEP_DETAILS
    if not any(a.get("validated") for a in addresses):
        return cx.STEP_ADDRESS
    if not any(a["authorized"] for a in authorized):
        return cx.STEP_REVIEW
    return "ready_for_filing"


# ── 3. the business details ────────────────────────────────────────────────

@router.post("/details")
async def save_details(tenant_id: str, body: dict):
    """Store the customer's answers. CREATES NO PROVIDER RESOURCE.

    Deliberately not `regulatory.submit_details`, which calls prepare_profile and
    would create an EndUser, a SupportingDocument and a Bundle -- before the
    customer has seen, let alone authorised, what those carry.
    """
    body = body or {}
    _reject_system_fields(body)
    tenant = await _tenant(tenant_id)
    country = _country(tenant)

    values = {f: str(body.get(f) or "").strip()
              for f in CUSTOMER_DETAIL_FIELDS if f in body}
    supplied = {k: v for k, v in values.items() if v}
    if not supplied:
        _fail(engine.INVALID_CUSTOMER_DATA,
              {"missing": [f for f in CUSTOMER_DETAIL_FIELDS
                           if not str(body.get(f) or "").strip()]})

    stored = await db_reg.upsert_business_details(
        tenant_id, country, end_user_type=engine.DEFAULT_END_USER_TYPE,
        values={**supplied,
                # Provenance of the answers, stamped by the server. Not the
                # authorisation timestamp -- collecting is not consenting.
                "collected_at": engine._now_iso(),
                "requirements_fingerprint": await _requirements_fingerprint(tenant, country)})
    stored = stored or {}
    missing = [f for f in CUSTOMER_DETAIL_FIELDS if not str(stored.get(f) or "").strip()]
    return {
        "status": "ok",
        "details": {f: stored.get(f) for f in CUSTOMER_DETAIL_FIELDS},
        "details_complete": not missing,
        "missing": missing,
        "next_step": cx.STEP_DETAILS if missing else cx.STEP_ADDRESS,
    }


# ── 4. the business address ────────────────────────────────────────────────

@router.post("/address")
async def validate_address(tenant_id: str, body: dict):
    """Validate an Irish business address with the provider.

    THE ONLY PROVIDER WRITE IN THIS GATE. An Address is a postal fact, carries no
    identity, is excluded from the authorisation digest, and is deletable -- which
    is why it sits on this side of Gate 1.
    """
    body = body or {}
    _reject_system_fields(body)
    tenant = await _tenant(tenant_id)
    country = _country(tenant)

    submitted = {f: str((body.get("address") or {}).get(f) or "").strip()
                 for f in CUSTOMER_ADDRESS_FIELDS}
    # The country is OURS, from the confirmed compliance country. Accepting it
    # from the body would let a customer validate an address into a country they
    # never confirmed, and the digest would then record a country nobody chose.
    submitted["iso_country"] = country

    # The name the premises is registered to is the registered business name the
    # customer already gave, read back from storage rather than asked for twice.
    # Asking again would let the two disagree, and the address would then name a
    # business the authorisation digest does not cover -- the digest fingerprints
    # business_name, not this field.
    details = await db_reg.get_business_details(tenant_id, country) or {}
    customer_name = str(details.get("business_name") or "").strip()
    if not customer_name:
        _fail(engine.INVALID_CUSTOMER_DATA, {"missing": ["business_name"]})
    submitted["customer_name"] = customer_name

    result = await engine.ensure_address(
        tenant, submitted=submitted,
        tenant_location_id=body.get("tenant_location_id") or None)
    if not result["ok"]:
        # PROVIDER_UNAVAILABLE and ADDRESS_VALIDATION_FAILED reach the customer as
        # different things. Collapsing them would tell someone their correct
        # address is wrong during an outage, and they would "fix" it into a wrong
        # one that then fails at filing for a reason nobody can see.
        _fail(result["status"], result)

    addr = result["address"] or {}
    return {
        "status": "ok",
        "address": _public_address(addr),
        "reused": bool(result.get("reused")),
        "next_step": cx.STEP_REVIEW if addr.get("validated") else cx.STEP_ADDRESS,
    }


# ── 5. exactly what will be authorised ─────────────────────────────────────

@router.get("/review")
async def review_snapshot(tenant_id: str, regulatory_address_id: str):
    """The twelve facts, read from canonical storage, plus the proof of this read.

    Built from the DATABASE, never from a request body. A review assembled from
    what the browser happens to be holding would let a modified page show one set
    of facts and authorise another -- which is precisely the property the
    authorisation exists to rule out.
    """
    tenant = await _tenant(tenant_id)
    country = _country(tenant)
    details = await db_reg.get_business_details(tenant_id, country) or {}
    address = await db_reg.get_address(tenant_id, regulatory_address_id)
    if not address:
        # Tenant-scoped at the query, so another tenant's address simply is not here.
        raise HTTPException(status_code=404, detail={
            "status": "address_not_found",
            "message": "That business address is not on this account.",
            "action_required": True, "revisit_step": cx.STEP_ADDRESS})
    if not address.get("validated"):
        _fail(engine.NOT_READY, {"missing": ["validated_address"]})

    missing = [f for f in CUSTOMER_DETAIL_FIELDS if not str(details.get(f) or "").strip()]
    if missing:
        _fail(engine.INVALID_CUSTOMER_DATA, {"missing": missing})

    facts = auth.facts_from(details, address)
    fingerprint = auth.fingerprint(facts)
    req_fp = await _requirements_fingerprint(tenant, country)

    return {
        "scope": {
            "tenant_id": tenant_id,
            "iso_country": country,
            "end_user_type": engine.DEFAULT_END_USER_TYPE,
            "regulatory_address_id": address["id"],
            "business_name_on_file": tenant.get("business_name"),
        },
        # The twelve fingerprinted facts, in the order the digest fixes them, each
        # with the label the customer saw when they typed it.
        "facts": [{"name": name, "label": _FACT_LABELS.get(name, name),
                   "value": facts.get(name) or ""}
                  for name in auth.FIELDS],
        "requirements_context": {
            "known": bool(req_fp),
            "note": ("These are the details your regulator currently requires."
                     if req_fp else
                     "We could not re-check the regulator's current requirements "
                     "just now. The details below are what we hold for you."),
        },
        # The proof that THIS fact set was shown. Opaque, short-lived, and worth
        # nothing on its own: authorising recomputes the digest from storage and
        # compares. The customer cannot choose what gets authorised.
        "review_token": review.issue(
            tenant_id=tenant_id, iso_country=country,
            end_user_type=engine.DEFAULT_END_USER_TYPE, address_id=address["id"],
            authorization_fingerprint=fingerprint, requirements_fingerprint=req_fp),
        "review_expires_in_seconds": review.TTL_SECONDS,
        "consent_statement": CONSENT_STATEMENT,
    }


_FACT_LABELS = {
    "business_name": "Registered business name",
    "business_registration_number": "Company registration (CRO) number",
    "business_website": "Business website",
    "authorized_rep_first_name": "Representative first name",
    "authorized_rep_last_name": "Representative last name",
    "authorized_rep_email": "Representative email",
    "address_street": "Address line 1",
    "address_street_secondary": "Address line 2",
    "address_city": "Town or city",
    "address_region": "County",
    "address_postal_code": "Eircode",
    "address_iso_country": "Country",
}

#: The words the customer affirmatively agrees to. Server-owned so the record and
#: the screen cannot diverge, and so a modified page cannot weaken the wording
#: someone is recorded as having accepted. States what we will do with the facts;
#: it does not advise them on their obligations, which is not ours to do.
CONSENT_STATEMENT = (
    "I confirm that the information shown above is accurate, that I am authorised "
    "to provide it on behalf of this business, and I authorise OpenLines to submit "
    "it to our telecommunications provider and the relevant regulator to complete "
    "the registration required for an Irish phone number.")


# ── 6. consent ─────────────────────────────────────────────────────────────

@router.post("/authorize")
async def authorize(tenant_id: str, body: dict,
                    user: dict = Depends(authenticated_tenant_user)):
    """Record the customer's authorisation of the facts they just reviewed.

    STOPS HERE. Nothing downstream is triggered: no profile is prepared, no
    EndUser is created, nothing is filed. W9I-D owns that, and a route that
    quietly continued would cross Gate 1 on a click whose consent covered the
    facts, not the filing.

    The customer supplies a review token and their acknowledgement, and nothing
    else. WHO comes from the verified bearer token; WHEN comes from the server
    clock inside record_authorization; WHAT is recomputed from storage.
    """
    body = body or {}
    _reject_system_fields(body)
    if body.get("consent") is not True:
        raise HTTPException(status_code=422, detail={
            "status": "consent_required",
            "message": "Tick the confirmation box to authorise this registration.",
            "action_required": True, "revisit_step": cx.STEP_REVIEW})

    address_id = str(body.get("regulatory_address_id") or "")
    tenant = await _tenant(tenant_id)
    country = _country(tenant)
    details = await db_reg.get_business_details(tenant_id, country) or {}
    address = await db_reg.get_address(tenant_id, address_id)
    if not address:
        raise HTTPException(status_code=404, detail={
            "status": "address_not_found",
            "message": "That business address is not on this account.",
            "action_required": True, "revisit_step": cx.STEP_ADDRESS})

    # Recomputed HERE, from storage, and compared with what the token says was
    # read. The token never supplies the fingerprint that gets recorded.
    current = auth.fingerprint_for(details, address)
    proof = review.verify(
        str(body.get("review_token") or ""),
        tenant_id=tenant_id, iso_country=country,
        end_user_type=engine.DEFAULT_END_USER_TYPE, address_id=address["id"],
        current_authorization_fingerprint=current,
        current_requirements_fingerprint=await _requirements_fingerprint(tenant, country))
    if proof["status"] != review.OK:
        logger.info("Authorisation refused for tenant %s: %s (%s)",
                    tenant_id, proof["status"], proof.get("detail"))
        _fail(proof["status"])

    who = str(user.get("email") or "").strip()
    if not who:
        # An authorisation has to name someone. An account with no email on the
        # verified token cannot produce an auditable record, and inventing one
        # would defeat the point.
        raise HTTPException(status_code=409, detail={
            "status": "authorizer_unknown",
            "message": "We could not identify the signed-in account. Please sign "
                       "in again and confirm.",
            "action_required": True, "revisit_step": cx.STEP_REVIEW})

    result = await engine.record_authorization(
        tenant_id, iso_country=country, end_user_type=engine.DEFAULT_END_USER_TYPE,
        address_row=address, details=details,
        authorized_by=who,
        # The existing closed vocabulary. This flow IS the dashboard.
        authorization_method="dashboard")
    if not result["ok"]:
        _fail(result["status"], result)

    row = result.get("authorization") or {}
    return {
        "status": "authorized",
        # A repeated click re-affirms the same consent rather than creating a
        # second record; both answers are "you are authorised".
        "created": bool(result.get("created")),
        "authorized_at": row.get("authorized_at"),
        "authorized_by": row.get("authorized_by"),
        "regulatory_address_id": address["id"],
        "next_state": READY_FOR_REGULATORY_FILING,
        "message": "Your information is ready for regulatory submission.",
        "filing_submitted": False,
    }


#: Derived, not stored. tenants.onboarding_state stays `regulatory_required` --
#: 031's CHECK admits three values and this is not one of them, and widening it
#: would put a fact in the tenant row that the authorisation rows already answer
#: more precisely (per address, revocable, and historical).
READY_FOR_REGULATORY_FILING = "ready_for_regulatory_filing"
