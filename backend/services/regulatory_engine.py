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

import asyncio
import logging

from db import regulatory as db_reg
from services import provider_claims as pc
from services import regulatory_declaration as decl
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
DECLARATION_POLICY_UNRESOLVED = "declaration_policy_unresolved"
DECLARATION_REJECTED_BY_REGULATION = "declaration_rejected_by_regulation"
NOT_READY = "not_ready"
MISSING_COUNTRY = "business_country_not_confirmed"
UNSUPPORTED_REQUIREMENT_FIELD = "unsupported_requirement_field"
REQUIREMENTS_NOT_RECORDED = "requirements_not_recorded"
# Another request currently owns creating this address. A NORMAL, RETRYABLE state --
# deliberately not address_validation_failed (nothing was rejected) and deliberately
# not an error (nothing is wrong), because telling a customer their address failed
# because they double-clicked would be a lie.
ADDRESS_CREATE_IN_PROGRESS = "address_create_in_progress"
# Another request owns creating this provider resource. Normal and retryable.
PROVIDER_CREATE_IN_PROGRESS = "provider_create_in_progress"
# Two provider resources carry the same claim marker. FAIL CLOSED: choosing one
# would attach a regulatory identity nobody selected, and the other would linger.
PROVIDER_IDENTITY_CONFLICT = "provider_identity_conflict"

# How long a request that lost the claim will wait for the winner before returning
# ADDRESS_CREATE_IN_PROGRESS. A Twilio Address.create round-trip measured ~0.5s, so
# this usually resolves into a reuse; it is bounded because a web request must not
# hang on another request's provider call.
CLAIM_WAIT_ATTEMPTS = 4
CLAIM_WAIT_SECONDS = 0.4

DEFAULT_NUMBER_TYPE = "local"
DEFAULT_END_USER_TYPE = "business"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()



async def _resolve_declaration(reqs, stored_details: dict | None) -> dict:
    """Resolve the system-sourced declaration and reconcile it with the live regulation.

    ── HISTORICAL IMMUTABILITY ───────────────────────────────────────────────
    If values were already persisted for this tenant -- i.e. a filing has been built
    on them -- they are REUSED, not recomputed. A policy change later must not
    silently rewrite what an earlier filing actually declared to a regulator. Only a
    profile with nothing stored yet takes today's policy.
    """
    existing = {k: str((stored_details or {}).get(k) or "").strip()
                for k in decl.POLICY_FIELDS}
    if all(existing.values()):
        # Already declared. Honour history.
        return _result(OK, attributes={k: v for k, v in existing.items()
                                       if k in set(reqs.end_user_field_names)},
                       source="persisted")

    policy = decl.resolve(iso_country=reqs.iso_country,
                          number_type=reqs.number_type,
                          end_user_type=reqs.end_user_type)
    if policy is None:
        # Twilio has not told us the answer for this combination. Not a default.
        return _result(DECLARATION_POLICY_UNRESOLVED,
                       context=f"{reqs.iso_country}/{reqs.number_type}/"
                               f"{reqs.end_user_type}",
                       next_requirement="provider confirmation for this exact "
                                        "country, number type and end-user type")

    status, detail = decl.validate_against_regulation(policy, reqs)
    if status != decl.RESOLVED:
        # The regulation changed under the answer. A support reply from the past is
        # not licence to file a value the provider now rejects.
        return _result(DECLARATION_REJECTED_BY_REGULATION, detail=detail)
    return _result(OK, attributes=decl.applicable_attributes(policy, reqs),
                   source=policy.source)


async def _ensure_draft_profile(tenant_id, country, number_type, end_user_type,
                                address_row, reqs, sub_sid, tenant_location_id):
    """A profile row with NO provider identity yet.

    Exists so a workflow stalled on the unresolved declaration is visible and
    resumable, without filing anything. Deliberately carries no end_user_sid and no
    bundle_sid -- 027's trp_submitted_identity_chk only demands those once the state
    has reached the provider, and this state has not.
    """
    profile = await db_reg.find_profile_for_address(
        tenant_id, country, number_type, end_user_type, address_row["id"])
    patch = {"regulation_sid": reqs.regulation_sid,
             "regulation_friendly_name": reqs.friendly_name,
             "requirements_fingerprint": reqs.fingerprint(),
             "requirements_observed_at": _now_iso()}
    if profile:
        return await db_reg.update_profile(profile["id"], patch) or {**profile, **patch}
    return await db_reg.insert_profile({
        "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
        "regulatory_address_id": address_row["id"], "provider": "twilio",
        "provider_account_sid": sub_sid, "iso_country": country,
        "number_type": number_type, "end_user_type": end_user_type,
        "state": st.DETAILS_REQUIRED, **patch})


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
        return await _reconcile_existing_address(existing, client, sub_sid)

    submitted_columns = {k: (v or None) for k, v in values.items() if k != "iso_country"}

    # ── THE CLAIM, BEFORE ANY PROVIDER WRITE (W9H-QA.3) ───────────────────
    # W9H-QA.2 measured two processes both reaching Address.create before either
    # owned the row: two provider Addresses, one orphaned, and a raw 23505 out of
    # the loser's request. Ordering is the fix -- the database decides who may
    # spend a provider resource, using the partial unique indexes that were already
    # there, and it decides BEFORE the resource is spent rather than after.
    claim = existing
    i_created_the_claim = False
    if claim is None:
        claim = await db_reg.claim_address({
            "tenant_id": tenant_id, "tenant_location_id": tenant_location_id,
            "iso_country": country, "provider_account_sid": sub_sid,
            "validated": False, **submitted_columns})
        i_created_the_claim = claim is not None
        if claim is None:
            # Someone else claimed this scope between our read and our insert. The
            # loser NEVER calls the provider -- it waits briefly for the winner and
            # then reports honestly that work is in flight.
            return await _await_claim_winner(tenant_id, country, tenant_location_id,
                                             client, sub_sid)

    if str(claim.get("provider_account_sid") or "") not in ("", sub_sid):
        return _result(OWNERSHIP_CONFLICT, detail="address_account_mismatch")

    # ── DID ANYONE ALREADY CREATE FOR THIS CLAIM? ─────────────────────────
    # Asked of the PROVIDER, not of our own row, because the dangerous gap is
    # exactly the one where an Address exists at Twilio and our row does not know
    # it yet -- a worker that died between create and attach. The claim id travels
    # in FriendlyName, so this is an exact lookup rather than a guess at matching
    # street text, and it is what makes takeover adopt an orphan instead of minting
    # a second one.
    marker = db_reg.claim_marker(claim["id"])
    try:
        already = client.addresses.list(friendly_name=marker, limit=20)
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    if already:
        return await _adopt_provider_address(claim, already, client, sub_sid,
                                             submitted_columns)

    # ── MAY I CREATE? ─────────────────────────────────────────────────────
    # Only the claim's owner may. We own it if we just inserted it, or if we won an
    # atomic takeover of one that is abandoned or terminally failed.
    if not i_created_the_claim:
        taken = await db_reg.take_over_address_claim(claim["id"])
        if taken is None:
            # A live worker holds it. Wait briefly, then say so.
            return await _await_claim_winner(tenant_id, country, tenant_location_id,
                                             client, sub_sid)
        claim = taken

    try:
        created = client.addresses.create(
            customer_name=values["customer_name"], street=values["street"],
            city=values["city"], region=values["region"] or values["city"],
            postal_code=values["postal_code"], iso_country=country,
            street_secondary=values["street_secondary"] or None,
            friendly_name=marker,
            emergency_enabled=False, auto_correct_address=True)
    except Exception as e:
        detail = _safe_provider_error(e)
        code = getattr(e, "code", None)
        # 21628 is Twilio refusing to validate the address -- a customer-data
        # problem, not an outage, and the two must not share a state.
        if code == 21628:
            await db_reg.record_address_failure(claim["id"], "provider_could_not_validate")
            # NEVER log the address itself on failure.
            logger.warning("Regulatory address rejected by provider for tenant %s (%s)",
                           tenant_id, detail)
            row = await db_reg.get_address(tenant_id, claim["id"])
            return _result(ADDRESS_VALIDATION_FAILED, detail=detail, address=row or claim)

        # ANYTHING ELSE IS AN UNKNOWN OUTCOME, NOT A FAILURE. A timeout or a
        # transport error can arrive after Twilio has already created the Address;
        # retrying the create blindly is how duplicates are born. Ask the provider
        # what actually happened, using the claim marker.
        logger.error("Regulatory address creation failed for tenant %s: %s",
                     tenant_id, detail)
        try:
            found = client.addresses.list(friendly_name=marker, limit=20)
        except Exception:
            found = []
        if found:
            return await _adopt_provider_address(claim, found, client, sub_sid,
                                                 submitted_columns)
        await db_reg.release_address_claim(claim["id"])
        return _result(PROVIDER_UNAVAILABLE, detail=detail)

    return await _adopt_provider_address(claim, [created], client, sub_sid,
                                         submitted_columns)


async def _reconcile_existing_address(existing: dict, client, sub_sid: str) -> dict:
    """Re-read an address we already created, so our state matches the provider's."""
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


async def _await_claim_winner(tenant_id: str, country: str,
                              tenant_location_id: str | None,
                              client, sub_sid: str) -> dict:
    """A request that does not own the claim: wait briefly, then report honestly.

    Bounded on purpose. The winner's provider call takes well under a second, so
    most losers return the winner's validated address; but a web request must never
    be held open waiting on another request, so when the wait runs out this returns
    a distinct retryable status rather than inventing a failure.
    """
    for attempt in range(CLAIM_WAIT_ATTEMPTS):
        await asyncio.sleep(CLAIM_WAIT_SECONDS)
        row = await db_reg.find_address(tenant_id, country, tenant_location_id)
        if row and row.get("address_sid"):
            return await _reconcile_existing_address(row, client, sub_sid)
        if row and row.get("validation_error"):
            return _result(ADDRESS_VALIDATION_FAILED,
                           detail=str(row.get("validation_error")), address=row)
    return _result(ADDRESS_CREATE_IN_PROGRESS, detail="another_request_is_creating_it")


async def _adopt_provider_address(claim: dict, candidates: list, client, sub_sid: str,
                                  submitted_columns: dict) -> dict:
    """Attach ONE provider Address to the claim, and clean up any sibling.

    More than one candidate means a worker crashed mid-create and its replacement
    created another before the first became visible. Both carry this claim's marker,
    so both are provably ours -- which is the only condition under which deleting a
    provider resource is defensible. We keep the one we attach and remove the rest.

    If the fenced attach finds the claim already finalised, we are the stale worker:
    we do not overwrite the current owner, and we withdraw our own Address instead
    of leaving it orphaned.
    """
    chosen = candidates[0]
    patch = {"provider_account_sid": sub_sid, "address_sid": chosen.sid,
             "validated": bool(getattr(chosen, "validated", False)),
             "validation_error": None,
             "provider_locality": str(getattr(chosen, "city", "") or "") or None,
             "provider_region": str(getattr(chosen, "region", "") or "") or None,
             **submitted_columns}
    row = await db_reg.attach_address_sid(claim["id"], patch)

    if row is None:
        # Lost the claim. Somebody else already attached an address.
        current = await db_reg.get_address(claim["tenant_id"], claim["id"])
        winner_sid = str((current or {}).get("address_sid") or "")
        for extra in candidates:
            if extra.sid != winner_sid:
                _discard_provider_address(client, extra.sid, claim["id"])
        if current and current.get("address_sid"):
            return await _reconcile_existing_address(current, client, sub_sid)
        return _result(ADDRESS_CREATE_IN_PROGRESS, detail="claim_taken_over")

    for extra in candidates[1:]:
        _discard_provider_address(client, extra.sid, claim["id"])
    return _result(OK, address=row, reused=False)


def _discard_provider_address(client, address_sid: str, claim_id: str) -> None:
    """Delete a provider Address that is provably ours and provably unused.

    "Provably ours" is the whole point: the caller only ever passes a SID it found
    by this claim's FriendlyName marker, or one it created itself under that marker.
    An address whose ownership we cannot establish is never touched.
    """
    try:
        client.addresses(address_sid).delete()
    except Exception as e:
        # Not fatal -- the claim is already correct. Worth a line so a leaked
        # resource is findable, with no address content in it.
        logger.warning("Could not remove superseded regulatory address for claim %s: %s",
                       claim_id, _safe_provider_error(e))


# ═══════════════════════════════════════════════════════════════════════════
# Claim-guarded provider creation  (migration 030, W9H-QA.4)
# ═══════════════════════════════════════════════════════════════════════════
#
# W9H-QA.3 measured the defect for Addresses: two processes both crossed
# Address.create before either owned the database row, leaving a duplicate and an
# orphan, because Twilio deduplicates nothing. W9H.1A found the same shape in
# EndUser, SupportingDocument and Bundle creation. This is the one implementation
# all three now go through, so they cannot drift apart.
#
# The order is the whole point:
#
#   claim (DB insert)  ->  ask the provider what exists  ->  create  ->  fenced attach
#
# and the provider question is what makes crash recovery possible: the claim id
# travels in FriendlyName, so a worker can tell "nothing was created" from "a dead
# worker created one and never attached it".


async def _ensure_provider_resource(*, tenant_id: str, resource: str, scope_key: str,
                                    sub_sid: str, lookup, create,
                                    delete=None) -> dict:
    """Create at most one provider resource for one logical scope.

    lookup(marker) -> the provider objects carrying that marker. For Bundles that
        is a server-side FriendlyName filter; for EndUsers and SupportingDocuments
        Twilio offers no filter at all (measured), so the caller lists and matches
        client-side over a collection that holds a handful of rows per sub-account.
    create(marker)  -> creates the resource, stamped with the marker.
    delete(sid)     -> withdraws a resource this claim provably owns. Optional; a
        resource whose ownership we cannot prove is never touched.
    """
    claim = await db_reg.find_provider_claim(tenant_id=tenant_id, resource=resource,
                                             scope_key=scope_key)
    i_claimed_it = False
    if claim is None:
        claim = await db_reg.claim_provider_resource(
            tenant_id=tenant_id, resource=resource, scope_key=scope_key,
            provider_account_sid=sub_sid)
        i_claimed_it = claim is not None
        if claim is None:
            # Lost the race. The loser NEVER calls the provider.
            return await _await_provider_claim(tenant_id, resource, scope_key,
                                               sub_sid, lookup)

    if claim.get("provider_sid"):
        if str(claim.get("provider_account_sid") or "") != sub_sid:
            return _result(OWNERSHIP_CONFLICT, detail=f"{resource}_account_mismatch")
        return _result(OK, provider_sid=claim["provider_sid"], claim=claim, reused=True)

    if str(claim.get("provider_account_sid") or "") not in ("", sub_sid):
        return _result(OWNERSHIP_CONFLICT, detail=f"{resource}_account_mismatch")

    marker = pc.marker(resource, claim["id"])

    # DID ANYONE ALREADY CREATE FOR THIS CLAIM? Asked of the provider, because the
    # dangerous gap is the one where the resource exists at Twilio and our row does
    # not know it -- a worker that died between create and attach.
    found = await _lookup_marked(lookup, marker)
    if not found["ok"]:
        return found
    if found["objects"]:
        return await _adopt_provider_resource(claim, found["objects"], sub_sid,
                                              resource, delete)

    if not i_claimed_it:
        taken = await db_reg.take_over_provider_claim(claim["id"])
        if taken is None:
            return await _await_provider_claim(tenant_id, resource, scope_key,
                                               sub_sid, lookup)
        claim = taken

    try:
        created = create(marker)
    except Exception as e:
        detail = _safe_provider_error(e)
        code = getattr(e, "code", None)
        if code in _TERMINAL_PROVIDER_CODES:
            await db_reg.record_provider_claim_failure(claim["id"], detail)
            logger.warning("Provider refused %s for tenant %s (%s)",
                           resource, tenant_id, detail)
            return _result(PROVIDER_REJECTED, detail=detail, claim=claim)

        # UNKNOWN OUTCOME, not failure. A timeout can arrive after Twilio created
        # the resource; retrying create is how duplicates are born. Ask instead.
        logger.error("Provider %s creation failed for tenant %s: %s",
                     resource, tenant_id, detail)
        again = await _lookup_marked(lookup, marker)
        if again["ok"] and again["objects"]:
            return await _adopt_provider_resource(claim, again["objects"], sub_sid,
                                                  resource, delete)
        # Nothing was created. Let go of the lease so the next attempt is not told
        # that a request which has already ended is still in flight.
        await db_reg.release_provider_claim(claim["id"])
        return _result(PROVIDER_UNAVAILABLE, detail=detail, claim=claim)

    return await _adopt_provider_resource(claim, [created], sub_sid, resource, delete)


# The only provider codes we treat as a settled verdict about the REQUEST rather
# than an ambiguous outcome. Deliberately short: everything else -- including
# 22212 (incomplete attributes) and 70002 -- goes down the reconcile path, which
# both preserves the statuses callers already handle and, because the lease is
# released, lets a retry proceed at once.
_TERMINAL_PROVIDER_CODES = (21628,)


async def _lookup_marked(lookup, marker: str) -> dict:
    try:
        return _result(OK, objects=pc.matching(lookup(marker), marker))
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e),
                       objects=[])


async def _await_provider_claim(tenant_id: str, resource: str, scope_key: str,
                                sub_sid: str, lookup) -> dict:
    """A request that does not own the claim: wait briefly, then report honestly.

    Bounded, because a web request must never hang on another request's provider
    call. When the wait runs out this returns a distinct retryable status rather
    than inventing a failure.
    """
    for _ in range(CLAIM_WAIT_ATTEMPTS):
        await asyncio.sleep(CLAIM_WAIT_SECONDS)
        claim = await db_reg.find_provider_claim(tenant_id=tenant_id,
                                                 resource=resource,
                                                 scope_key=scope_key)
        if claim and claim.get("provider_sid"):
            if str(claim.get("provider_account_sid") or "") != sub_sid:
                return _result(OWNERSHIP_CONFLICT,
                               detail=f"{resource}_account_mismatch")
            return _result(OK, provider_sid=claim["provider_sid"], claim=claim,
                           reused=True)
        if claim and claim.get("failure"):
            return _result(PROVIDER_REJECTED, detail=str(claim["failure"]),
                           claim=claim)
    return _result(PROVIDER_CREATE_IN_PROGRESS,
                   detail=f"another_request_is_creating_the_{resource}")


async def _adopt_provider_resource(claim: dict, candidates: list, sub_sid: str,
                                   resource: str, delete) -> dict:
    """Attach ONE provider resource to the claim.

    MORE THAN ONE MATCH FAILS CLOSED. For an Address, two duplicates were
    interchangeable and one could simply be withdrawn. These are not: an EndUser is
    a regulatory identity and a Bundle is a filing, so picking one arbitrarily would
    attach an identity nobody chose and leave a second one behind. A human has to
    look.
    """
    if len(candidates) > 1:
        logger.error("Provider identity conflict: %d %s resources carry claim %s",
                     len(candidates), resource, claim["id"])
        return _result(PROVIDER_IDENTITY_CONFLICT, count=len(candidates),
                       claim=claim,
                       next_requirement=f"a human must decide which {resource} is "
                                        f"authoritative and remove the other")

    chosen = candidates[0]
    row = await db_reg.attach_provider_sid(claim["id"], chosen.sid, sub_sid)
    if row is None:
        # Lost the claim: somebody else already attached. Do not overwrite them, and
        # do not leave our own resource behind.
        current = await db_reg.find_provider_claim(
            tenant_id=claim["tenant_id"], resource=resource,
            scope_key=claim["scope_key"])
        winner = str((current or {}).get("provider_sid") or "")
        if winner and winner != chosen.sid and delete is not None:
            _withdraw_provider_resource(delete, chosen.sid, claim["id"], resource)
        if winner:
            return _result(OK, provider_sid=winner, claim=current, reused=True)
        return _result(PROVIDER_CREATE_IN_PROGRESS, detail="claim_taken_over")
    return _result(OK, provider_sid=chosen.sid, claim=row, reused=False)


def _withdraw_provider_resource(delete, sid: str, claim_id: str, resource: str) -> None:
    """Remove a provider resource that is provably ours and provably unused.

    "Provably ours" is the condition, not a formality: the caller only ever passes a
    SID it found by this claim's marker or created itself under that marker. A
    resource whose ownership we cannot establish is never deleted.
    """
    try:
        delete(sid)
    except Exception as e:
        # Not fatal -- the claim is already correct. Logged so a leaked resource
        # stays findable by its marker, with no customer content in the line.
        logger.warning("Could not withdraw superseded %s for claim %s: %s",
                       resource, claim_id, _safe_provider_error(e))


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

    # ── CLAIM BEFORE CREATE (W9H-QA.4) ────────────────────────────────────
    # The sibling scan above is a correct REUSE mechanism and a useless MUTUAL
    # EXCLUSION one: two requests for two different locations of the same business
    # both find no sibling SID, and both used to create an EndUser -- a second
    # regulatory identity for one company, with no DB uniqueness anywhere to stop
    # it because 027 deliberately has no EndUser table.
    #
    # The claim is scoped to (country, end_user_type), NOT to the profile or the
    # address, because that is what an EndUser actually is: one business identity
    # shared by all of this tenant's sibling filings for a country.
    eu = client.numbers.v2.regulatory_compliance.end_users
    out = await _ensure_provider_resource(
        tenant_id=tenant_id, resource="end_user", sub_sid=sub_sid,
        scope_key=pc.end_user_scope(requirements.iso_country,
                                    requirements.end_user_type),
        # Twilio offers NO list filter for EndUsers (measured live in W9H-QA.4), so
        # the marker is matched client-side over the sub-account's handful of rows.
        lookup=lambda marker: eu.list(limit=200),
        create=lambda marker: eu.create(friendly_name=marker,
                                        type=requirements.end_user_type,
                                        attributes=payload),
        delete=lambda sid: eu(sid).delete())
    if not out["ok"]:
        # NEVER log the attribute bag: it holds the representative's name and email.
        return out
    return _result(OK, end_user_sid=out["provider_sid"], reused=out.get("reused", False))


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

    # ── CLAIM BEFORE CREATE (W9H-QA.4) ────────────────────────────────────
    # `supporting_document_sid IS NULL` is a fine FENCE for attachment but cannot
    # say "somebody is creating one right now", so two requests both used to create
    # and an unfenced update let the last writer win -- silently orphaning the
    # loser's document with no error at all. The claim is scoped to the validated
    # address and the document type, because Ireland's business_address document IS
    # a reference to one Address SID.
    sd = client.numbers.v2.regulatory_compliance.supporting_documents
    out = await _ensure_provider_resource(
        tenant_id=str(address_row["tenant_id"]), resource="supporting_document",
        sub_sid=sub_sid,
        scope_key=pc.supporting_document_scope(address_row["id"], doc.accepted_type),
        # No list filter for SupportingDocuments either (measured).
        lookup=lambda marker: sd.list(limit=200),
        create=lambda marker: sd.create(
            friendly_name=marker, type=doc.accepted_type,
            attributes={"address_sids": [address_row["address_sid"]]}),
        delete=lambda sid: sd(sid).delete())
    if not out["ok"]:
        return out
    created_sid = out["provider_sid"]
    if str(address_row.get("supporting_document_sid") or "") != created_sid:
        await db_reg.update_address(address_row["id"],
                                   {"supporting_document_sid": created_sid})
    return _result(OK, supporting_document_sid=created_sid,
                   reused=out.get("reused", False))


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

    # ── CLAIM BEFORE CREATE (W9H-QA.4) ────────────────────────────────────
    # Keyed on the profile, which already carries the whole filing scope -- tenant,
    # country, number type, end-user type and address -- so a Bundle can never be
    # shared across two distinct filings. Before this, two requests both created a
    # Bundle and the unfenced bundle_sid write left one abandoned in draft.
    bu = client.numbers.v2.regulatory_compliance.bundles
    out = await _ensure_provider_resource(
        tenant_id=str(profile.get("tenant_id") or tenant.get("id") or ""),
        resource="bundle", sub_sid=sub_sid,
        scope_key=pc.bundle_scope(profile["id"]),
        # Bundles DO support a server-side FriendlyName filter (measured), so this
        # one is an exact provider-side query rather than a client-side scan.
        lookup=lambda marker: bu.list(friendly_name=marker, limit=50),
        create=lambda marker: bu.create(
            friendly_name=marker, email=email, status_callback=callback_url(),
            regulation_sid=requirements.regulation_sid),
        delete=lambda sid: bu(sid).delete())
    if not out["ok"]:
        return out
    sid = out["provider_sid"]
    try:
        live = bu(sid).fetch()
        status = str(getattr(live, "status", "") or "")
    except Exception as e:
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    return _result(OK, bundle_sid=sid, bundle_status=status,
                   reused=out.get("reused", False))


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
    # The profile must know WHICH requirement shape it was built against. Without a
    # stored fingerprint there is nothing to compare the live requirements to, so
    # drift cannot be detected and the submission fails closed rather than going
    # out on an unverifiable basis.
    if not str(profile.get("requirements_fingerprint") or "").strip():
        blockers.append(REQUIREMENTS_NOT_RECORDED)
    return blockers


# ═══════════════════════════════════════════════════════════════════════════
# Profile preparation — the resumable step that builds every provider resource
# ═══════════════════════════════════════════════════════════════════════════

async def read_end_user_attributes(*, end_user_sid: str, client) -> dict:
    """The attributes actually filed with the provider.

    A RECONCILIATION AID, NOT THE SOURCE OF TRUTH. W9G used this as the only place
    the answers lived, which meant a provider outage or a deleted EndUser destroyed
    them. The durable record is now tenant_regulatory_business_details; this exists
    to compare what we hold against what Twilio holds, so a divergence is visible.
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

    # A provider field with nowhere to store it stops the workflow. Personal data
    # must not accumulate in an untyped blob, and a requirement we cannot record is
    # a requirement we cannot show back to the customer to correct.
    unstorable = db_reg.unstorable_fields(reqs.end_user_field_names)
    if unstorable:
        return _result(UNSUPPORTED_REQUIREMENT_FIELD, fields=unstorable,
                       next_requirement="a column for each new provider field, or a "
                                        "reviewed design for storing it")

    # PERSIST WHAT THE CUSTOMER TYPED, BEFORE TOUCHING THE PROVIDER. Everything
    # after this can fail -- and if the answers only ever existed in this request,
    # every failure would mean asking them to retype. Merged, so a one-field
    # correction stays a one-field correction.
    # THE DECLARATION IS NOT THE CUSTOMER'S TO SUPPLY. Stripping it here rather
    # than merely ignoring it downstream is what stops a customer-supplied value
    # from being persisted and then read back as "history" on the next request --
    # which would let anyone inject a false regulatory declaration by POSTing it
    # once. The only writer of these columns is the policy path below.
    customer_supplied = {k: v for k, v in (attributes or {}).items()
                         if k not in decl.POLICY_FIELDS}
    stored = await db_reg.upsert_business_details(
        tenant_id, country, end_user_type=end_user_type,
        values={**db_reg.details_from_attributes(customer_supplied),
                "requirements_fingerprint": reqs.fingerprint(),
                "collected_at": _now_iso()})

    # The effective answers are the stored ones: this request's values merged over
    # whatever a previous request already established. That is what makes a retry
    # after a provider failure work without the customer present.
    effective = db_reg.attributes_from_details(stored, reqs.end_user_field_names)

    # ── THE ADDRESS GATE, AFTER PERSISTENCE ───────────────────────────────
    # It sits here, not above, because the customer's answers do not depend on the
    # address. W9H-QA found them being persisted downstream of this gate: a business
    # that filled in every field but whose address the provider refused lost
    # everything they had typed, which is precisely the recoverability defect W9G.1
    # was meant to close.
    #
    # The two failures are also reported differently. "No address submitted yet" and
    # "you submitted one and Twilio refused it" need different things from the
    # customer, and calling the second one address_not_created would tell them to add
    # an address they have already added.
    address_row = await db_reg.find_address(tenant_id, country, tenant_location_id)
    if not address_row:
        return _result(NOT_READY, detail="address_not_submitted", details_stored=True)
    if not address_row.get("address_sid"):
        return _result(ADDRESS_VALIDATION_FAILED,
                       detail=str(address_row.get("validation_error")
                                  or "address_rejected_by_provider"),
                       details_stored=True)
    if not address_row.get("validated"):
        return _result(ADDRESS_VALIDATION_FAILED, detail="address_not_validated",
                       details_stored=True)

    bad = ie_ux.invalid_enum_fields(reqs, effective)
    if bad:
        return _result(INVALID_CUSTOMER_DATA, invalid_enum=bad)
    unresolved = ie_ux.unresolved_declarations(reqs, effective)
    missing = [m for m in ie_ux.missing_fields(reqs, effective) if m not in unresolved]
    if missing:
        return _result(INVALID_CUSTOMER_DATA, missing=missing,
                       details_stored=True)

    # ── THE DECLARATION ───────────────────────────────────────────────────
    # business_identity and is_subassigned are not facts about the customer; they
    # are a statement in Twilio's terminology about the commercial relationship,
    # and Twilio Support has confirmed the answer for THIS architecture. So they
    # are SYSTEM-SOURCED -- resolved from the context we already know, not asked of
    # a business owner who would have to interpret provider jargon to answer.
    #
    # The policy is still subordinate to the live regulation: it says what we
    # believe, the Regulation API says what the provider currently accepts, and the
    # two are reconciled before anything is filed.
    declared = await _resolve_declaration(reqs, stored)
    if not declared["ok"]:
        profile = await _ensure_draft_profile(
            tenant_id, country, number_type, end_user_type, address_row, reqs,
            sub_sid, tenant_location_id)
        return {**declared, "profile": profile, "details_stored": True}
    effective = {**effective, **declared["attributes"]}

    # Anything the regulation asks for that the policy did NOT answer is still a
    # hard stop -- the block was never about these two fields specifically, it was
    # about never filing an identity the regulation calls incomplete.
    still_unresolved = ie_ux.unresolved_declarations(reqs, effective)
    if still_unresolved:
        profile = await _ensure_draft_profile(
            tenant_id, country, number_type, end_user_type, address_row, reqs,
            sub_sid, tenant_location_id)
        return _result(UNRESOLVED_ISV_DECLARATION,
                       unresolved_declarations=still_unresolved,
                       details_stored=True, profile=profile)

    # PERSIST THE DECLARATION BEFORE THE IDENTITY IS FILED. Whatever the EndUser
    # ends up stating must already be recorded on our side, so a retry files the
    # same thing and an audit can show what was declared.
    if declared.get("source") != "persisted" and declared["attributes"]:
        stored = await db_reg.upsert_business_details(
            tenant_id, country, end_user_type=end_user_type,
            values={**declared["attributes"],
                    "requirements_fingerprint": reqs.fingerprint()})
        effective = {**effective,
                     **db_reg.attributes_from_details(stored, reqs.end_user_field_names)}

    eu = await resolve_end_user(tenant, requirements=reqs, attributes=effective,
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
            # DURABLE, not an in-request value: this is what a later submission
            # compares the live requirements against.
            "requirements_fingerprint": reqs.fingerprint(),
            "requirements_observed_at": _now_iso(),
        })
        if not profile:
            # Another request inserted this profile between our read and our write
            # (migration 027's partial unique indexes decided). Re-read the
            # canonical row and continue against it -- both requests must end up
            # working on the SAME profile, and W9H.1A found this path leaking a raw
            # PostgreSQL 23505, constraint name and all, to the API instead.
            profile = await db_reg.find_profile_for_address(
                tenant_id, country, number_type, end_user_type, address_row["id"])
            if not profile:
                return _result(PROVIDER_UNAVAILABLE, detail="profile_claim_lost")
    else:
        patch = {"requirements_fingerprint": reqs.fingerprint(),
                 "requirements_observed_at": _now_iso()}
        if profile.get("end_user_sid") != eu["end_user_sid"]:
            patch["end_user_sid"] = eu["end_user_sid"]
        await db_reg.update_profile(profile["id"], patch)
        profile = {**profile, **patch}

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

    # ── DURABLE DRIFT CHECK ───────────────────────────────────────────────
    # The SID alone is not enough: Twilio can change a regulation's required
    # fields without reissuing it. The fingerprint stored on the profile when the
    # answers were collected is compared with the shape the provider reports NOW,
    # so a change that happened between two requests -- or across a restart -- is
    # caught. Comparing two in-memory values inside one request, which is what W9G
    # did, could never have detected this.
    stored_fp = str(profile.get("requirements_fingerprint") or "").strip()
    if not stored_fp:
        return _result(NOT_READY, blockers=[REQUIREMENTS_NOT_RECORDED])
    if stored_fp != reqs.fingerprint():
        return _result(REQUIREMENTS_CHANGED, detail="required_fields_changed",
                       regulation_sid=reqs.regulation_sid,
                       stored_fingerprint=stored_fp,
                       current_fingerprint=reqs.fingerprint())

    address_row = (await db_reg.get_address(str(profile["tenant_id"]),
                                           str(profile["regulatory_address_id"]))
                   if profile.get("regulatory_address_id") else None)
    # OUR OWN RECORD IS THE SOURCE, not the provider's copy. Reading the filed
    # attributes back from Twilio only works while Twilio has them and is
    # reachable, which is precisely when it is least useful. The stored details are
    # also what an operator edits after a rejection.
    details = await db_reg.get_business_details(
        str(profile["tenant_id"]), str(profile.get("iso_country") or ""),
        str(profile.get("end_user_type") or "business"))
    attributes = db_reg.attributes_from_details(details, reqs.end_user_field_names)
    # A submission must declare exactly what was persisted. If the declaration was
    # never stored, submission_blockers below refuses -- it is not recomputed here,
    # because a filing's declaration is history, not a live lookup.
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


async def recover_end_user(tenant: dict, *, profile: dict) -> dict:
    """Re-establish a provider EndUser from OUR stored answers.

    Covers the cases W9G had no answer for: the EndUser 404s, or a sibling's SID
    turns out to describe something inconsistent, or a create failed after the
    customer had already gone. Because the answers are durable, none of these needs
    the customer present.

    Fails closed if the declaration is still unresolved -- recovery must not become
    a side door that files an incomplete identity.
    """
    client, sub_sid = _tenant_client(tenant)
    if client is None:
        return _result(OWNERSHIP_CONFLICT, detail="missing_twilio_credentials")
    if str(profile.get("provider_account_sid") or "") != sub_sid:
        return _result(OWNERSHIP_CONFLICT, detail="profile_account_mismatch")

    country = str(profile.get("iso_country") or "")
    end_user_type = str(profile.get("end_user_type") or "business")
    found = await rq.discover_regulation(iso_country=country,
                                        number_type=str(profile.get("number_type") or ""),
                                        end_user_type=end_user_type, client=client)
    if not found.ok:
        return _result(PROVIDER_UNAVAILABLE if found.status == rq.UNAVAILABLE
                       else found.status, detail=found.detail)
    reqs = found.requirements

    details = await db_reg.get_business_details(str(profile["tenant_id"]), country,
                                               end_user_type)
    if not details:
        # Nothing stored: this profile predates the durable record, so the customer
        # genuinely has to be asked again. Said plainly rather than guessed around.
        return _result(NOT_READY, detail="no_stored_business_details")
    attributes = db_reg.attributes_from_details(details, reqs.end_user_field_names)

    # The same resolver prepare_profile uses, so recovery can never file a different
    # declaration from the one the original filing made.
    declared = await _resolve_declaration(reqs, details)
    if not declared["ok"]:
        return declared
    attributes = {**attributes, **declared["attributes"]}
    unresolved = ie_ux.unresolved_declarations(reqs, attributes)
    if unresolved:
        return _result(UNRESOLVED_ISV_DECLARATION,
                       unresolved_declarations=unresolved)
    missing = ie_ux.missing_fields(reqs, attributes)
    if missing:
        return _result(INVALID_CUSTOMER_DATA, missing=missing)

    existing_sid = str(profile.get("end_user_sid") or "")
    if existing_sid:
        try:
            client.numbers.v2.regulatory_compliance.end_users(existing_sid).fetch()
            return _result(OK, end_user_sid=existing_sid, recreated=False)
        except Exception as e:
            code = getattr(e, "status", None)
            if code != 404:
                # Only a 404 proves it is gone. Anything else is "we do not know",
                # and recreating on an unknown would risk a duplicate identity.
                return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))

    try:
        created = client.numbers.v2.regulatory_compliance.end_users.create(
            friendly_name=f"OpenLines tenant {str(profile['tenant_id'])[:8]} "
                          f"({country} {end_user_type})",
            type=end_user_type, attributes=attributes)
    except Exception as e:
        logger.error("EndUser recovery failed for profile %s: %s",
                     profile.get("id"), _safe_provider_error(e))
        return _result(PROVIDER_UNAVAILABLE, detail=_safe_provider_error(e))
    await db_reg.update_profile(profile["id"], {"end_user_sid": created.sid})
    return _result(OK, end_user_sid=created.sid, recreated=True)
