"""The Ireland regulatory compliance engine (W9G).

Takes an explicitly-confirmed Irish business from "nothing" to "submitted for
review", one resumable step at a time:

    confirm country -> discover regulation -> collect details -> validate address
    -> EndUser -> SupportingDocument -> Bundle -> ItemAssignments -> Evaluation
    -> submit -> (callback / reconciliation) -> approved | rejected | more info

── EVERY STEP IS IDEMPOTENT, BECAUSE EVERY STEP CAN BE RETRIED ────────────────
Each provider resource is created at most once per profile: the step looks for a
stored SID first, fetches it to confirm it still exists, and only creates when there
is genuinely nothing. That matters more here than usual -- a duplicate Twilio Address
or Bundle is not just untidy, it is a second filing about the same business.

── EVERY RESOURCE IS OWNERSHIP-CHECKED ────────────────────────────────────────
W9C proved Twilio regulatory objects are account-scoped and that a parent-account
Bundle is invisible to a sub-account purchase. So every resource is created in the
TENANT'S sub-account, and every stored SID is re-checked against the sub-account we
expect before it is used. A SID that belongs to the wrong account fails closed.

── NO NUMBER IS EVER PURCHASED HERE ───────────────────────────────────────────
There is no call to IncomingPhoneNumber.create in this module or anything it calls.
Acquisition is a later gate.
"""
from __future__ import annotations

import logging

from db import regulatory as db_reg
from services import regulatory_ireland as ie_ux
from services import regulatory_requirements as rq
from services import regulatory_state as st
from services import telephony, vapi  # noqa: F401  (vapi imported for parity of boundaries)
from services.telephony import _safe_provider_error

logger = logging.getLogger(__name__)

# ── step outcomes, all distinguished ──────────────────────────────────────
OK = "ok"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PROVIDER_REJECTED = "provider_rejected"
INVALID_CUSTOMER_DATA = "invalid_customer_data"
OWNERSHIP_CONFLICT = "ownership_conflict"
REGULATORY_IDENTITY_CONFLICT = "regulatory_identity_conflict"
ADDRESS_VALIDATION_FAILED = "address_validation_failed"
UNSUPPORTED_DOCUMENT_REQUIREMENT = "unsupported_document_requirement"
REQUIREMENTS_CHANGED = "requirements_changed"
UNRESOLVED_ISV_DECLARATION = "unresolved_isv_declaration"
NOT_READY = "not_ready"
MISSING_COUNTRY = "business_country_not_confirmed"

DEFAULT_NUMBER_TYPE = "local"
DEFAULT_END_USER_TYPE = "business"


def _result(status: str, **extra) -> dict:
    return {"status": status, "ok": status == OK, **extra}


def _tenant_client(tenant: dict):
    """A Twilio client authenticated AS THE TENANT'S SUB-ACCOUNT.

    Regulatory resources must live where the number will be bought (W9C), so every
    provider call in this module goes through here -- never the parent client.
    """
    sid = str((tenant or {}).get("twilio_subaccount_sid") or "").strip()
    tok = str((tenant or {}).get("twilio_auth_token") or "").strip()
    if not sid or not tok:
        return None, ""
    return telephony._sub_client(sid, tok), sid


# ═══════════════════════════════════════════════════════════════════════════
# Requirements
# ═══════════════════════════════════════════════════════════════════════════

async def requirements_for(tenant: dict, *, iso_country: str | None = None,
                           number_type: str = DEFAULT_NUMBER_TYPE,
                           end_user_type: str = DEFAULT_END_USER_TYPE) -> dict:
    """Discover what the provider currently requires. No writes."""
    country = (iso_country or str(tenant.get("business_country_code") or "")).strip().upper()
    if not country:
        return _result(MISSING_COUNTRY)
    found = await rq.discover_regulation(iso_country=country, number_type=number_type,
                                        end_user_type=end_user_type)
    if not found.ok:
        return _result(PROVIDER_UNAVAILABLE if found.status == rq.UNAVAILABLE
                       else found.status, detail=found.detail)
    reqs = found.requirements
    return _result(OK, requirements=reqs,
                   fields=ie_ux.describe_fields(reqs),
                   fingerprint=reqs.fingerprint())


# ═══════════════════════════════════════════════════════════════════════════
# Address
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_address(tenant: dict, *, submitted: dict,
                         tenant_location_id: str | None = None,
                         iso_country: str | None = None) -> dict:
    """Validate and persist the tenant's regulatory address.

    The address is SUPPLIED, never synthesised. Ireland's provider behaviour rejects
    an address it cannot validate (W9C measured 21628 both for an invented street and
    for a real one with no Eircode), so an incomplete address is refused here rather
    than sent to fail at the provider.
    """
    country = (iso_country or str(tenant.get("business_country_code") or "")).strip().upper()
    if not country:
        return _result(MISSING_COUNTRY)
    tenant_id = str(tenant.get("id") or "")
    client, sub_sid = _tenant_client(tenant)
    if client is None:
        return _result(OWNERSHIP_CONFLICT, detail="missing_twilio_credentials")

    # A tenant_location must belong to this tenant. The composite FK in migration
    # 027 enforces it at write time; checking here turns a 23503 into a clean refusal.
    if tenant_location_id:
        from db.supabase import get_client
        loc = (get_client().table("tenant_locations").select("id")
               .eq("id", tenant_location_id).eq("tenant_id", tenant_id)
               .limit(1).execute().data or [])
        if not loc:
            return _result(OWNERSHIP_CONFLICT, detail="tenant_location_not_owned")

    required = ("customer_name", "street", "city", "iso_country")
    if country == "IE":
        # Eircode is mandatory for Ireland: the provider refuses the address without
        # one, and a refusal after creation is more confusing than one before.
        required = required + ("postal_code",)
    values = {k: str((submitted or {}).get(k) or "").strip() for k in
              ("customer_name", "street", "street_secondary", "city", "region",
               "postal_code")}
    values["iso_country"] = country
    missing = [k for k in required if not values.get(k)]
    if missing:
        return _result(INVALID_CUSTOMER_DATA, missing=missing)

    existing = await db_reg.find_address(tenant_id, country, tenant_location_id)

    # Already created at the provider? Reconcile instead of creating a second one.
    if existing and existing.get("address_sid"):
        if str(existing.get("provider_account_sid") or "") != sub_sid:
            return _result(OWNERSHIP_CONFLICT, detail="address_account_mismatch")
        try:
            live = client.addresses(existing["address_sid"]).fetch()
        except Exception as e:
            return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
        patch = {"validated": bool(getattr(live, "validated", False)),
                 "provider_locality": str(getattr(live, "city", "") or "") or None,
                 "provider_region": str(getattr(live, "region", "") or "") or None,
                 "validation_error": None}
        row = await db_reg.update_address(existing["id"], patch)
        return _result(OK, address=row or {**existing, **patch}, reused=True)

    try:
        created = client.addresses.create(
            customer_name=values["customer_name"], street=values["street"],
            city=values["city"], region=values["region"] or values["city"],
            postal_code=values["postal_code"], iso_country=country,
            street_secondary=values["street_secondary"] or None,
            friendly_name=f"OpenLines regulatory address ({country})",
            emergency_enabled=False, auto_correct_address=True)
    except Exception as e:
        detail = _safe_provider_error(e)
        code = getattr(e, "code", None)
        # 21628 is Twilio refusing to validate the address -- a customer-data
        # problem, not an outage, and the two must not share a state.
        if code == 21628:
            row = existing or await db_reg.insert_address({
                "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
                "iso_country": country, "provider_account_sid": sub_sid,
                "validated": False, **{k: v or None for k, v in values.items()
                                       if k != "iso_country"}})
            if row:
                await db_reg.update_address(row["id"],
                                            {"validated": False,
                                             "validation_error": "provider_could_not_validate"})
            # NEVER log the address itself on failure.
            logger.warning("Regulatory address rejected by provider for tenant %s (%s)",
                           tenant_id, detail)
            return _result(ADDRESS_VALIDATION_FAILED, detail=detail,
                           address=row)
        logger.error("Regulatory address creation failed for tenant %s: %s",
                     tenant_id, detail)
        return _result(PROVIDER_UNAVAILABLE, detail=detail)

    row_patch = {
        "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
        "iso_country": country, "provider_account_sid": sub_sid,
        "address_sid": created.sid,
        "validated": bool(getattr(created, "validated", False)),
        "validation_error": None,
        "provider_locality": str(getattr(created, "city", "") or "") or None,
        "provider_region": str(getattr(created, "region", "") or "") or None,
        **{k: (v or None) for k, v in values.items() if k != "iso_country"},
    }
    row = (await db_reg.update_address(existing["id"], row_patch) if existing
           else await db_reg.insert_address(row_patch))
    return _result(OK, address=row, reused=False)


# ═══════════════════════════════════════════════════════════════════════════
# EndUser  (no table by design -- reuse is derived from sibling profiles)
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_end_user(tenant: dict, *, requirements, attributes: dict,
                           client, sub_sid: str) -> dict:
    """Find or create the tenant's EndUser for this country and type.

    Migration 027 deliberately has no EndUser table: Twilio documents EndUsers as
    reusable across bundles, and one SID per tenant/country/type is derivable from
    the sibling profiles that already reference it. The rule is strict on purpose --
    if siblings disagree about which EndUser represents this tenant, that is a
    regulatory identity conflict and a human has to look, because picking one would
    file a bundle against an identity nobody chose.
    """
    tenant_id = str(tenant.get("id") or "")
    siblings = [p for p in await db_reg.list_profiles(tenant_id)
                if p.get("iso_country") == requirements.iso_country
                and p.get("end_user_type") == requirements.end_user_type
                and p.get("end_user_sid")]
    sids = {str(p["end_user_sid"]) for p in siblings}
    if len(sids) > 1:
        logger.error("Regulatory identity conflict for tenant %s: %d distinct "
                     "EndUser SIDs among sibling profiles", tenant_id, len(sids))
        return _result(REGULATORY_IDENTITY_CONFLICT, count=len(sids))

    if len(sids) == 1:
        sid = sids.pop()
        accounts = {str(p.get("provider_account_sid") or "") for p in siblings}
        if accounts and accounts != {sub_sid}:
            return _result(OWNERSHIP_CONFLICT, detail="end_user_account_mismatch")
        try:
            client.numbers.v2.regulatory_compliance.end_users(sid).fetch()
        except Exception as e:
            return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
        return _result(OK, end_user_sid=sid, reused=True)

    # Only the fields THIS regulation asks for. Sending an obsolete field would be
    # submitting a statement the current regulation does not define.
    asked = set(requirements.end_user_field_names)
    payload = {k: str(v) for k, v in (attributes or {}).items()
               if k in asked and str(v if v is not None else "").strip() != ""}
    try:
        created = client.numbers.v2.regulatory_compliance.end_users.create(
            friendly_name=f"OpenLines tenant {tenant_id[:8]} "
                          f"({requirements.iso_country} {requirements.end_user_type})",
            type=requirements.end_user_type, attributes=payload)
    except Exception as e:
        # NEVER log the attribute bag: it holds the representative's name and email.
        logger.error("EndUser creation failed for tenant %s: %s",
                     tenant_id, _safe_provider_error(e))
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    return _result(OK, end_user_sid=created.sid, reused=False)


# ═══════════════════════════════════════════════════════════════════════════
# Supporting document
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_supporting_document(tenant: dict, *, requirements, address_row: dict,
                                     client, sub_sid: str) -> dict:
    """Create or reuse the document that satisfies the provider's address requirement.

    Ireland's single requirement is satisfied by referencing Address SIDs, so nothing
    is uploaded and no document contents are ever stored. If the provider starts
    asking for an actual FILE, this stops with UNSUPPORTED_DOCUMENT_REQUIREMENT
    rather than improvising storage for identity documents -- that needs its own
    security design, not a quiet `files.create` here.
    """
    docs = [d for d in requirements.documents if d.required]
    if not docs:
        return _result(OK, supporting_document_sid=None, detail="no_document_required")
    if len(docs) > 1:
        return _result(UNSUPPORTED_DOCUMENT_REQUIREMENT,
                       detail=f"{len(docs)} required documents; one document per "
                              f"bundle is the proven provider cardinality")
    doc = docs[0]
    if not doc.satisfied_by_address_sids:
        return _result(UNSUPPORTED_DOCUMENT_REQUIREMENT,
                       detail=f"type={doc.accepted_type} "
                              f"fields={[f.name for f in doc.fields]}",
                       next_requirement="document upload + storage architecture")

    if not address_row or not address_row.get("address_sid"):
        return _result(NOT_READY, detail="address_not_created")
    if str(address_row.get("provider_account_sid") or "") != sub_sid:
        return _result(OWNERSHIP_CONFLICT, detail="address_account_mismatch")

    existing_sid = str(address_row.get("supporting_document_sid") or "")
    if existing_sid:
        try:
            client.numbers.v2.regulatory_compliance.supporting_documents(
                existing_sid).fetch()
        except Exception as e:
            return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
        return _result(OK, supporting_document_sid=existing_sid, reused=True)

    try:
        created = client.numbers.v2.regulatory_compliance.supporting_documents.create(
            friendly_name=f"Proof of address ({requirements.iso_country})",
            type=doc.accepted_type,
            attributes={"address_sids": [address_row["address_sid"]]})
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    await db_reg.update_address(address_row["id"],
                               {"supporting_document_sid": created.sid})
    return _result(OK, supporting_document_sid=created.sid, reused=False)


# ═══════════════════════════════════════════════════════════════════════════
# Bundle, assignments, evaluation
# ═══════════════════════════════════════════════════════════════════════════

def callback_url() -> str:
    """The public callback URL Twilio will sign. Configured, never guessed from a
    request -- see routers/regulatory.py for why."""
    from services import vapi as _vapi
    return f"{_vapi.APP_BACKEND_URL}/webhooks/twilio/regulatory"


async def ensure_bundle(tenant: dict, *, profile: dict, requirements,
                        end_user_sid: str, client, sub_sid: str) -> dict:
    """Create or reuse the Bundle for this profile."""
    if profile.get("bundle_sid"):
        if str(profile.get("provider_account_sid") or "") != sub_sid:
            return _result(OWNERSHIP_CONFLICT, detail="bundle_account_mismatch")
        try:
            live = client.numbers.v2.regulatory_compliance.bundles(
                profile["bundle_sid"]).fetch()
        except Exception as e:
            return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
        return _result(OK, bundle_sid=profile["bundle_sid"],
                       bundle_status=str(getattr(live, "status", "") or ""), reused=True)

    email = str((tenant or {}).get("email") or "").strip() or "compliance@openlines.ai"
    try:
        created = client.numbers.v2.regulatory_compliance.bundles.create(
            friendly_name=f"OpenLines {requirements.iso_country} "
                          f"{requirements.number_type} — tenant {str(tenant.get('id'))[:8]}",
            email=email, status_callback=callback_url(),
            regulation_sid=requirements.regulation_sid)
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    return _result(OK, bundle_sid=created.sid,
                   bundle_status=str(getattr(created, "status", "") or ""), reused=False)


async def ensure_item_assignments(*, bundle_sid: str, object_sids: list[str],
                                  client) -> dict:
    """Attach each object to the Bundle exactly once.

    Reads the existing assignments first, so a retry after a partial failure adds
    only what is missing. Twilio also rejects a duplicate itself (W9C saw 22214
    "EndUser already exists on bundle"), which is treated as already-assigned rather
    than as an error.
    """
    wanted = [s for s in object_sids if s]
    try:
        existing = client.numbers.v2.regulatory_compliance.bundles(
            bundle_sid).item_assignments.list(limit=50)
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    have = {str(getattr(a, "object_sid", "")) for a in existing}
    assigned, already = [], [s for s in wanted if s in have]
    for sid in [s for s in wanted if s not in have]:
        try:
            client.numbers.v2.regulatory_compliance.bundles(
                bundle_sid).item_assignments.create(object_sid=sid)
            assigned.append(sid)
        except Exception as e:
            if getattr(e, "code", None) in (22214,):
                already.append(sid)
                continue
            return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e),
                           assigned=assigned)
    return _result(OK, assigned=assigned, already_assigned=already)


async def evaluate(*, bundle_sid: str, client) -> dict:
    """Run Evaluation. A structural compliance check, synchronous.

    COMPLIANT / NONCOMPLIANT are statements about the customer's data. A provider
    error is neither -- it must never be recorded as noncompliant, because that would
    tell a customer their details are wrong when Twilio simply failed.
    """
    try:
        ev = client.numbers.v2.regulatory_compliance.bundles(
            bundle_sid).evaluations.create()
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    status = str(getattr(ev, "status", "") or "").lower()
    results = getattr(ev, "results", None) or []
    failed = []
    for r in results:
        if isinstance(r, dict) and r.get("passed") is False:
            failed.append(str(r.get("requirement_name") or "requirement"))
    # The reason is stored for the customer to act on, and deliberately NOT logged.
    reason = "; ".join(f"{name} not satisfied" for name in failed) or None
    return _result(OK, evaluation_status=status,
                   compliant=status == "compliant",
                   failed_requirements=failed, failure_reason=reason)


def submission_blockers(*, profile: dict, requirements, attributes: dict,
                        address_row: dict | None) -> list[str]:
    """Everything standing between this profile and a submission.

    Ordered so the most fundamental problem is first. An empty list is the only
    thing that permits submission.
    """
    blockers: list[str] = []
    if not profile.get("bundle_sid"):
        blockers.append("bundle_missing")
    if not profile.get("end_user_sid"):
        blockers.append("end_user_missing")
    if requirements.documents and not (address_row or {}).get("supporting_document_sid"):
        blockers.append("supporting_document_missing")
    if not (address_row or {}).get("validated"):
        blockers.append("address_not_validated")
    missing = ie_ux.missing_fields(requirements, attributes)
    if missing:
        blockers.append("missing_fields:" + ",".join(missing))
    bad = ie_ux.invalid_enum_fields(requirements, attributes)
    if bad:
        blockers.append("invalid_enum:" + ",".join(bad))
    unresolved = ie_ux.unresolved_declarations(requirements, attributes)
    if unresolved:
        # The ISV/sub-assignment declaration nobody has established the wording for.
        blockers.append(UNRESOLVED_ISV_DECLARATION + ":" + ",".join(unresolved))
    if str(profile.get("evaluation_status") or "").lower() != "compliant":
        blockers.append("evaluation_not_compliant")
    return blockers


async def submit(tenant: dict, *, profile: dict, requirements, attributes: dict,
                 address_row: dict | None, client, sub_sid: str) -> dict:
    """Submit the Bundle for Twilio review.

    Re-discovers the regulation first: submitting against requirements that changed
    since collection would file stale answers. Once submitted, the historical
    regulation identity on the profile is never rewritten -- reconciliation tracks
    the bundle Twilio actually holds.
    """
    if str(profile.get("provider_account_sid") or "") != sub_sid:
        return _result(OWNERSHIP_CONFLICT, detail="bundle_account_mismatch")

    fresh = await rq.discover_regulation(iso_country=requirements.iso_country,
                                        number_type=requirements.number_type,
                                        end_user_type=requirements.end_user_type,
                                        client=client)
    if not fresh.ok:
        return _result(PROVIDER_UNAVAILABLE if fresh.status == rq.UNAVAILABLE
                       else fresh.status, detail=fresh.detail)
    if (fresh.requirements.regulation_sid != requirements.regulation_sid
            or fresh.requirements.fingerprint() != requirements.fingerprint()):
        return _result(REQUIREMENTS_CHANGED,
                       detail="regulation or required fields changed since collection",
                       regulation_sid=fresh.requirements.regulation_sid)

    blockers = submission_blockers(profile=profile, requirements=requirements,
                                   attributes=attributes, address_row=address_row)
    if blockers:
        return _result(NOT_READY, blockers=blockers)

    try:
        updated = client.numbers.v2.regulatory_compliance.bundles(
            profile["bundle_sid"]).update(status="pending-review")
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    provider_status = str(getattr(updated, "status", "") or "")
    return _result(OK, bundle_status=provider_status,
                   state=st.state_for_provider_status(provider_status)[0])


# ═══════════════════════════════════════════════════════════════════════════
# Profile preparation — the resumable step that builds every provider resource
# ═══════════════════════════════════════════════════════════════════════════

async def read_end_user_attributes(*, end_user_sid: str, client) -> dict:
    """The attributes actually filed with the provider.

    THE ATTRIBUTE BAG IS NEVER STORED LOCALLY. It holds the authorised
    representative's name and email, and the only thing that needs it is the provider.
    So when a later step must check what was filed -- e.g. whether the ISV declaration
    fields were answered -- it reads them back from Twilio rather than keeping a copy.
    """
    try:
        eu = client.numbers.v2.regulatory_compliance.end_users(end_user_sid).fetch()
    except Exception as e:
        return {}
    attrs = getattr(eu, "attributes", None)
    return dict(attrs) if isinstance(attrs, dict) else {}


async def prepare_profile(tenant: dict, *, attributes: dict,
                          tenant_location_id: str | None = None,
                          number_type: str = DEFAULT_NUMBER_TYPE,
                          end_user_type: str = DEFAULT_END_USER_TYPE) -> dict:
    """Build every provider resource for one regulatory workflow, resumably.

    Order matters and each step is idempotent, so calling this again after any
    failure continues rather than duplicating: address -> EndUser -> document ->
    profile row -> Bundle -> assignments.
    """
    tenant_id = str(tenant.get("id") or "")
    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not country:
        return _result(MISSING_COUNTRY)
    client, sub_sid = _tenant_client(tenant)
    if client is None:
        return _result(OWNERSHIP_CONFLICT, detail="missing_twilio_credentials")

    found = await rq.discover_regulation(iso_country=country, number_type=number_type,
                                        end_user_type=end_user_type, client=client)
    if not found.ok:
        return _result(PROVIDER_UNAVAILABLE if found.status == rq.UNAVAILABLE
                       else found.status, detail=found.detail)
    reqs = found.requirements

    address_row = await db_reg.find_address(tenant_id, country, tenant_location_id)
    if not address_row or not address_row.get("address_sid"):
        return _result(NOT_READY, detail="address_not_created")
    if not address_row.get("validated"):
        return _result(ADDRESS_VALIDATION_FAILED, detail="address_not_validated")

    bad = ie_ux.invalid_enum_fields(reqs, attributes)
    if bad:
        return _result(INVALID_CUSTOMER_DATA, invalid_enum=bad)
    missing = ie_ux.missing_fields(reqs, attributes)
    # The declaration fields are reported separately: they are not the customer's to
    # supply, so listing them as "missing customer data" would misdirect the fix.
    unresolved = ie_ux.unresolved_declarations(reqs, attributes)
    missing = [m for m in missing if m not in unresolved]
    if missing:
        return _result(INVALID_CUSTOMER_DATA, missing=missing)

    eu = await resolve_end_user(tenant, requirements=reqs, attributes=attributes,
                               client=client, sub_sid=sub_sid)
    if not eu["ok"]:
        return eu

    doc = await ensure_supporting_document(tenant, requirements=reqs,
                                          address_row=address_row, client=client,
                                          sub_sid=sub_sid)
    if not doc["ok"]:
        return doc

    profile = await db_reg.find_profile_for_address(
        tenant_id, country, number_type, end_user_type, address_row["id"])
    if not profile:
        profile = await db_reg.insert_profile({
            "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
            "regulatory_address_id": address_row["id"], "provider": "twilio",
            "provider_account_sid": sub_sid, "iso_country": country,
            "number_type": number_type, "end_user_type": end_user_type,
            "regulation_sid": reqs.regulation_sid,
            "regulation_friendly_name": reqs.friendly_name,
            "end_user_sid": eu["end_user_sid"], "state": st.DETAILS_REQUIRED,
        })
        if not profile:
            return _result(PROVIDER_REJECTED, detail="profile_insert_failed")
    elif profile.get("end_user_sid") != eu["end_user_sid"]:
        await db_reg.update_profile(profile["id"],
                                   {"end_user_sid": eu["end_user_sid"]})
        profile = {**profile, "end_user_sid": eu["end_user_sid"]}

    bundle = await ensure_bundle(tenant, profile=profile, requirements=reqs,
                                end_user_sid=eu["end_user_sid"], client=client,
                                sub_sid=sub_sid)
    if not bundle["ok"]:
        return bundle
    if profile.get("bundle_sid") != bundle["bundle_sid"]:
        profile = await db_reg.update_profile(profile["id"], {
            "bundle_sid": bundle["bundle_sid"],
            "bundle_status": bundle["bundle_status"],
            "regulation_sid": reqs.regulation_sid,
        }) or profile

    objects = [eu["end_user_sid"]]
    if doc.get("supporting_document_sid"):
        objects.append(doc["supporting_document_sid"])
    assigned = await ensure_item_assignments(bundle_sid=bundle["bundle_sid"],
                                            object_sids=objects, client=client)
    if not assigned["ok"]:
        return assigned

    return _result(OK, profile=profile, requirements=reqs, address=address_row,
                   end_user_sid=eu["end_user_sid"],
                   supporting_document_sid=doc.get("supporting_document_sid"),
                   bundle_sid=bundle["bundle_sid"],
                   unresolved_declarations=unresolved,
                   assigned=assigned.get("assigned", []),
                   already_assigned=assigned.get("already_assigned", []))


async def evaluate_profile(tenant: dict, *, profile: dict) -> dict:
    """Run Evaluation for a profile and persist only the durable outcome."""
    client, sub_sid = _tenant_client(tenant)
    if client is None:
        return _result(OWNERSHIP_CONFLICT, detail="missing_twilio_credentials")
    if str(profile.get("provider_account_sid") or "") != sub_sid:
        return _result(OWNERSHIP_CONFLICT, detail="bundle_account_mismatch")
    if not profile.get("bundle_sid"):
        return _result(NOT_READY, detail="bundle_missing")

    ev = await evaluate(bundle_sid=profile["bundle_sid"], client=client)
    if not ev["ok"]:
        # A provider error is NOT noncompliance. The profile's evaluation_status is
        # left untouched so a customer is never told their data is wrong because
        # Twilio was briefly unavailable.
        return ev

    patch = {"evaluation_status": ev["evaluation_status"],
             "failure_reason": ev["failure_reason"],
             "failure_code": ("evaluation_noncompliant" if not ev["compliant"] else None)}
    current = str(profile.get("state") or "")
    target = st.READY_TO_SUBMIT if ev["compliant"] else st.DETAILS_REQUIRED
    outcome, _reason = st.transition(current, target)
    if outcome == st.APPLIED:
        await db_reg.transition_profile(profile["id"], expected_state=current,
                                       new_state=target, patch=patch)
    else:
        await db_reg.update_profile(profile["id"], patch)
    return _result(OK, evaluation_status=ev["evaluation_status"],
                   compliant=ev["compliant"],
                   failed_requirements=ev["failed_requirements"],
                   state=target if outcome == st.APPLIED else current)


async def submit_profile(tenant: dict, *, profile: dict) -> dict:
    """Submit for review, after re-checking everything that could have moved."""
    client, sub_sid = _tenant_client(tenant)
    if client is None:
        return _result(OWNERSHIP_CONFLICT, detail="missing_twilio_credentials")
    country = str(profile.get("iso_country") or "")
    found = await rq.discover_regulation(iso_country=country,
                                        number_type=str(profile.get("number_type") or ""),
                                        end_user_type=str(profile.get("end_user_type") or ""),
                                        client=client)
    if not found.ok:
        return _result(PROVIDER_UNAVAILABLE if found.status == rq.UNAVAILABLE
                       else found.status, detail=found.detail)
    reqs = found.requirements
    if str(profile.get("regulation_sid") or "") != reqs.regulation_sid:
        # The regulation itself was replaced. Submitting collected answers against a
        # different regulation would file the wrong form.
        return _result(REQUIREMENTS_CHANGED, detail="regulation_sid_changed",
                       regulation_sid=reqs.regulation_sid)

    address_row = (await db_reg.get_address(str(profile["tenant_id"]),
                                           str(profile["regulatory_address_id"]))
                   if profile.get("regulatory_address_id") else None)
    attributes = (await read_end_user_attributes(end_user_sid=profile["end_user_sid"],
                                                 client=client)
                  if profile.get("end_user_sid") else {})
    blockers = submission_blockers(profile=profile, requirements=reqs,
                                  attributes=attributes, address_row=address_row)
    if blockers:
        return _result(NOT_READY, blockers=blockers)

    current = str(profile.get("state") or "")
    if current == st.PENDING_REVIEW:
        # Already submitted. Idempotent, not an error.
        return _result(OK, state=st.PENDING_REVIEW,
                       bundle_status=str(profile.get("bundle_status") or ""),
                       already_submitted=True)
    outcome, reason = st.transition(current, st.SUBMITTING)
    if outcome != st.APPLIED:
        return _result(NOT_READY, blockers=[f"illegal_transition:{reason}"])
    if not await db_reg.transition_profile(profile["id"], expected_state=current,
                                          new_state=st.SUBMITTING):
        return _result(NOT_READY, blockers=["lost_race_to_another_submitter"])

    try:
        updated = client.numbers.v2.regulatory_compliance.bundles(
            profile["bundle_sid"]).update(status="pending-review")
    except Exception as e:
        # Put it back so a retry is possible.
        await db_reg.transition_profile(profile["id"], expected_state=st.SUBMITTING,
                                        new_state=st.READY_TO_SUBMIT)
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))

    from datetime import datetime, timezone
    provider_status = str(getattr(updated, "status", "") or "")
    target = st.state_for_provider_status(provider_status)[0] or st.PENDING_REVIEW
    await db_reg.transition_profile(
        profile["id"], expected_state=st.SUBMITTING, new_state=target,
        patch={"bundle_status": provider_status,
               "submitted_at": datetime.now(timezone.utc).isoformat()})
    return _result(OK, state=target, bundle_status=provider_status)
