"""Acquiring a tenant's permanent regulated number (W9I-F).

WHERE THIS STOPS, AND WHY THAT IS THE POINT
It buys the +353, records it, and wires the voice path. It does NOT mark the
number ACTIVE, does not touch the legacy scalar, does not start a trial, does
not send anything, and does not retire the temporary line. W9I-G owns the
promotion transaction, and separating them is deliberate: acquisition is the
part that spends money and can fail halfway, promotion is the part that is
visible to callers and starts billing. A single operation that did both would
have no safe place to stop.

At the end of a fully successful run the number is:

    purpose = permanent, status = provisioning

which is ours, not routable, and exactly what W9I-G expects to find.

TWO INDEPENDENT GATES, AND THEY ANSWER DIFFERENT QUESTIONS
Twilio approving a regulatory Bundle says the CUSTOMER's identity documents
satisfy the Irish regulator. It says nothing about whether OpenLines' own
commercial use of Irish numbering under a per-customer sub-account architecture
is permitted by the terms we operate under. Those are different questions asked
of different parties, and conflating them would let a regulatory approval
authorise a commercial decision nobody has made.

So there is a hard server-side gate, defaulting OFF, and when it is off no
inventory search happens at all -- not merely no purchase. A search that could
lead to a purchase is the start of the thing being gated.

APPROVAL IS RE-READ FROM THE PROVIDER, EVERY TIME
Persisted "approved" is a memory of a callback or a sweep. Between that moment
and this one a bundle can be withdrawn, rejected, or have been recorded from a
delivery we misread. Before any paid activity the Bundle is fetched with the
tenant's own credentials and must say approved NOW. A provider we cannot reach
is not an approval.
"""
from __future__ import annotations

import logging
import os

from db import phone_numbers as db_phones
from db import regulatory as db_reg
from db.supabase import get_client
from services import phone_lifecycle as lifecycle
from services import phone_registry
from services import regulatory_state as st
from services import telephony
from services import tenant_subaccount

logger = logging.getLogger(__name__)

# ── outcomes ───────────────────────────────────────────────────────────────
OK = "ok"
NOT_FOUND = "tenant_not_found"
GATE_CLOSED = "permanent_purchase_not_enabled"
NOT_ELIGIBLE = "permanent_number_not_eligible"
NOT_APPROVED = "regulatory_not_approved"
VERIFICATION_UNAVAILABLE = "regulatory_verification_unavailable"
INVENTORY_UNAVAILABLE = "permanent_number_inventory_unavailable"
PROVIDER_UNAVAILABLE = "provider_unavailable"
PURCHASE_OUTCOME_UNKNOWN = "permanent_purchase_outcome_unknown"
PURCHASE_REFUSED = "permanent_purchase_refused"
ROUTING_FAILED = "permanent_routing_failed"
ALREADY_HELD = "permanent_number_already_held"

#: Twilio's own vocabulary for an approved Bundle. ONE value. 'provisionally-
#: approved' is deliberately absent: W9C measured a purchase refused with
#: "status is not twilio-approved" on exactly that, and regulatory_state maps it
#: to pending_review for the same reason.
PROVIDER_APPROVED_STATUS = "twilio-approved"

#: Voice is what a receptionist needs. SMS is NOT required -- Irish local
#: inventory measured voice-only, and Square sends DANI-style booking
#: notifications, so demanding SMS would reject compliant numbers for a
#: capability nothing uses.
REQUIRED_CAPABILITIES = ("voice",)

PURCHASE_GATE_ENV = "IRELAND_PERMANENT_NUMBER_PURCHASE_ENABLED"


def purchase_enabled() -> bool:
    """The commercial gate. OFF unless a human turned it on.

    Separate from IRELAND_ONBOARDING_ENABLED on purpose: that one controls
    whether Irish businesses may sign up at all, this one controls whether we
    are willing to buy Irish numbering commercially. They can legitimately move
    at different times and for different reasons.
    """
    return os.getenv(PURCHASE_GATE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


# ── Stage B/C: eligibility, and approval re-read from the provider ─────────

async def _tenant(tenant_id: str) -> dict | None:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    return rows[0] if rows else None


async def eligibility(tenant: dict, *, regulatory_address_id: str = "") -> dict:
    """May this tenant have a permanent regulated number? LOCAL state only.

    Spends nothing and touches no provider. This is the preflight that stops a
    predictable purchase; `verify_approval` is what asks the provider.
    """
    tenant_id = str(tenant.get("id") or "")
    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not country:
        return _no("business_country_not_confirmed")

    from services import onboarding_lifecycle as ob
    if not ob.needs_regulatory_clearance(country):
        return _no("country_is_not_regulated")

    rows = await db_phones.list_for_tenant(tenant_id)
    live_perm = [r for r in rows
                 if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                 and r.get("status") in (lifecycle.STATUS_PROVISIONING,
                                         lifecycle.STATUS_ACTIVE,
                                         lifecycle.STATUS_RETIRING)]
    if live_perm:
        # Includes a row this very flow created on a previous attempt. Reported
        # as "already held" rather than refused, so a retry resumes.
        return {"eligible": False, "reason": ALREADY_HELD, "detail": "",
                "profile": None, "address": None, "existing": live_perm[0]}

    profiles = [p for p in await db_reg.list_profiles(tenant_id)
                if str(p.get("iso_country") or "").upper() == country]
    if not profiles:
        return _no("no_regulatory_filing")

    if regulatory_address_id:
        candidates = [p for p in profiles
                      if str(p.get("regulatory_address_id") or "") == regulatory_address_id]
        if not candidates:
            return _no("no_filing_for_that_address")
    else:
        candidates = profiles

    approved = [p for p in candidates if str(p.get("state") or "") == st.APPROVED]
    if not approved:
        states = sorted({str(p.get("state") or "") for p in candidates})
        return _no("filing_not_approved", detail=states[0] if states else None)

    profile = approved[0]
    if not profile.get("bundle_sid"):
        return _no("filing_has_no_bundle")

    address = await db_reg.get_address(tenant_id,
                                       str(profile.get("regulatory_address_id") or ""))
    if not address:
        return _no("regulatory_address_missing")
    if not (address.get("validated") and address.get("address_sid")):
        return _no("regulatory_address_not_validated")

    # The Bundle and the Address must live in the SAME account the credentials
    # belong to. Numbers v2 is credential-scoped, so a bundle from anywhere else
    # is invisible at purchase time -- and a bundle from ANOTHER TENANT would be
    # filing one customer's number against another's identity.
    sub_sid = str(tenant.get("twilio_subaccount_sid") or "")
    for label, row in (("profile", profile), ("address", address)):
        owner = str(row.get("provider_account_sid") or "")
        if owner and sub_sid and owner != sub_sid:
            logger.error("tenant %s: %s belongs to account %s, not the tenant's %s",
                         tenant_id, label, owner[:10], sub_sid[:10])
            return _no(f"{label}_account_mismatch")

    return {"eligible": True, "reason": "", "detail": None,
            "profile": profile, "address": address, "existing": None}


def _no(reason: str, detail=None) -> dict:
    return {"eligible": False, "reason": reason, "detail": detail,
            "profile": None, "address": None, "existing": None}


async def verify_approval(*, sub_sid: str, sub_tok: str, profile: dict) -> dict:
    """Ask TWILIO whether this Bundle is approved right now.

    The stored state is a memory of a delivery; this is the fact. Only an
    explicit `twilio-approved` permits spending, and only a successful fetch
    counts -- a timeout, 401, 403, 429, 5xx or malformed body all mean we do not
    know, and "we do not know" never buys a phone number.
    """
    bundle_sid = str(profile.get("bundle_sid") or "")
    if not bundle_sid:
        return {"ok": False, "status": NOT_APPROVED, "detail": "no_bundle_sid"}
    try:
        client = telephony.regulatory_client(sub_sid, sub_tok)
        live = client.numbers.v2.regulatory_compliance.bundles(bundle_sid).fetch()
    except Exception as e:
        logger.error("Could not verify bundle approval before purchase: %s",
                     type(e).__name__)
        return {"ok": False, "status": VERIFICATION_UNAVAILABLE,
                "detail": type(e).__name__}
    provider_status = str(getattr(live, "status", "") or "").strip().lower()
    if provider_status != PROVIDER_APPROVED_STATUS:
        logger.warning("Bundle for profile %s is %s at the provider -- not buying",
                       profile.get("id"), provider_status)
        return {"ok": False, "status": NOT_APPROVED, "detail": provider_status,
                "provider_status": provider_status}
    # The account that holds the bundle must be the one we authenticated as.
    holder = str(getattr(live, "account_sid", "") or "")
    if holder and holder != sub_sid:
        return {"ok": False, "status": NOT_ELIGIBLE, "detail": "bundle_account_mismatch"}
    return {"ok": True, "status": OK, "provider_status": provider_status}


# ── Stage D/E/F/H/I: the one acquisition operation ────────────────────────

async def ensure_permanent_irish_number(tenant_id: str, *,
                                        regulatory_address_id: str = "",
                                        locality: str = "") -> dict:
    """Acquire and wire this tenant's permanent regulated number. Stops there.

    The caller names a tenant, optionally a premises and a desired locality. It
    never names a country, an account, a Bundle, an Address, a number or a
    status -- every provider identifier is chosen here from canonical rows.
    """
    tenant = await _tenant(tenant_id)
    if not tenant:
        return {"status": NOT_FOUND}

    # ── 1. THE COMMERCIAL GATE, BEFORE ANYTHING ELSE ──────────────────────
    # Before eligibility, before the provider, before inventory. A search that
    # could lead to a purchase is part of what is being gated, and doing it
    # anyway would also bill us for lookups we have not decided to make.
    if not purchase_enabled():
        return {"status": GATE_CLOSED,
                "reason": "awaiting_platform_enablement"}

    # ── 2. LOCAL PREFLIGHT ────────────────────────────────────────────────
    elig = await eligibility(tenant, regulatory_address_id=regulatory_address_id)
    if not elig["eligible"]:
        if elig["reason"] == ALREADY_HELD:
            row = elig["existing"]
            return {"status": ALREADY_HELD, "row": row, "e164": row.get("e164")}
        return {"status": NOT_ELIGIBLE, "reason": elig["reason"],
                "detail": elig["detail"]}
    profile, address = elig["profile"], elig["address"]

    sub = await tenant_subaccount.ensure(tenant)
    if sub["status"] != tenant_subaccount.OK:
        return {"status": PROVIDER_UNAVAILABLE, "reason": "subaccount_unavailable"}
    sub_sid, sub_tok = sub["sid"], sub["auth_token"]

    # ── 3. APPROVAL, RE-READ FROM THE PROVIDER ────────────────────────────
    verified = await verify_approval(sub_sid=sub_sid, sub_tok=sub_tok, profile=profile)
    if not verified["ok"]:
        return {"status": verified["status"], "reason": verified.get("detail"),
                "profile_id": profile.get("id")}

    # ── 4. HAVE WE ALREADY BOUGHT ONE? ────────────────────────────────────
    # A previous attempt may have purchased and lost the response. Ask before
    # spending, exactly as the temporary path does.
    held = await _held_regulated_numbers(sub_sid, sub_tok, iso_country="IE")
    if held["status"] != OK:
        return {"status": PROVIDER_UNAVAILABLE, "reason": "inventory_unreadable"}
    if held["numbers"]:
        adopted = _pick_unambiguous(held["numbers"])
        if adopted is None:
            # More than one candidate and no way to tell which was ours. Guessing
            # would attach a customer's regulatory filing to an arbitrary number.
            logger.error("tenant %s holds %d unassigned regulated numbers -- "
                         "operator review required", tenant_id, len(held["numbers"]))
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "multiple_unassigned_numbers"}
        logger.warning("tenant %s already holds a regulated number -- adopting "
                       "rather than purchasing", tenant_id)
        return await _record_and_route(
            tenant=tenant, e164=adopted["e164"], provider_sid=adopted["sid"],
            sub_sid=sub_sid, sub_tok=sub_tok, profile=profile, address=address,
            adopted=True)

    # ── 5. INVENTORY ──────────────────────────────────────────────────────
    # NEVER widens. A locality with no inventory is reported, not substituted:
    # a business that asked for Cork must not be handed Dublin silently.
    try:
        candidates = await telephony.find_regulated_candidates(
            sub_sid, sub_tok, "IE", locality=locality, limit=10)
    except telephony.CountryNotSupported:
        return {"status": NOT_ELIGIBLE, "reason": "country_not_supported"}
    except Exception as e:
        logger.error("Regulated inventory search failed for tenant %s: %s",
                     tenant_id, type(e).__name__)
        return {"status": PROVIDER_UNAVAILABLE, "reason": "inventory_search_failed"}

    usable = [c for c in candidates if c.supports(*REQUIRED_CAPABILITIES)]
    if not usable:
        return {"status": INVENTORY_UNAVAILABLE,
                "reason": "no_voice_capable_inventory" if candidates
                          else "no_inventory",
                "locality": locality}
    candidate = usable[0]

    # ── 6. PURCHASE, WITH THE REGULATORY BINDINGS ─────────────────────────
    try:
        e164, provider_sid = await telephony.purchase_regulated_number(
            sub_sid, sub_tok, candidate.phone_number,
            address_sid=str(address["address_sid"]),
            bundle_sid=str(profile["bundle_sid"]))
    except Exception as e:
        # Two very different things look alike here, so they are separated by
        # asking the provider what it now holds -- never by guessing.
        detail = telephony._safe_provider_error(e)
        recheck = await _held_regulated_numbers(sub_sid, sub_tok, iso_country="IE")
        if recheck["status"] != OK:
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "provider_unreachable_after_purchase"}
        if not recheck["numbers"]:
            # Nothing was bought: a genuine refusal, commonly the address being
            # incompatible with this number's locality. The customer's data is
            # not wrong, so this is not reported as their error.
            logger.error("Regulated purchase refused for tenant %s: %s",
                         tenant_id, detail)
            return {"status": PURCHASE_REFUSED, "reason": "provider_refused"}
        got = _pick_unambiguous(recheck["numbers"])
        if got is None:
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "multiple_unassigned_numbers"}
        logger.warning("Regulated purchase for tenant %s errored but the provider "
                       "holds the number -- adopting", tenant_id)
        # ADOPTED, not purchased: our call failed and the number was found at the
        # provider afterwards. Reporting it as a clean purchase would make the
        # logs claim a confirmation we never received.
        return await _record_and_route(
            tenant=tenant, e164=got["e164"], provider_sid=got["sid"],
            sub_sid=sub_sid, sub_tok=sub_tok, profile=profile, address=address,
            adopted=True)

    return await _record_and_route(
        tenant=tenant, e164=e164, provider_sid=provider_sid, sub_sid=sub_sid,
        sub_tok=sub_tok, profile=profile, address=address, adopted=False)


async def _held_regulated_numbers(sub_sid: str, sub_tok: str, *,
                                  iso_country: str) -> dict:
    """Numbers on this sub-account in the regulated country, with their SIDs."""
    listing = await telephony.fetch_subaccount_numbers(sub_sid, sub_tok)
    if not listing.ok:
        return {"status": PROVIDER_UNAVAILABLE, "numbers": []}
    prefix = {"IE": "+353"}.get(iso_country.upper(), "")
    out = [{"e164": n.phone_number, "sid": n.sid}
           for n in listing.numbers
           if not prefix or str(n.phone_number or "").startswith(prefix)]
    return {"status": OK, "numbers": out}


def _pick_unambiguous(numbers: list[dict]) -> dict | None:
    """Exactly one candidate, or nothing.

    Adoption attaches a customer's regulatory filing to a specific number. With
    two candidates and no evidence distinguishing them, the honest answer is that
    we cannot tell -- and an operator reconciles rather than a coin being flipped.
    """
    return numbers[0] if len(numbers) == 1 else None


# ── Stage J/L: record it, wire it, and stop ───────────────────────────────

async def _record_and_route(*, tenant: dict, e164: str, provider_sid: str,
                            sub_sid: str, sub_tok: str, profile: dict,
                            address: dict, adopted: bool) -> dict:
    """Canonical row, then Vapi, then STOP at provisioning.

    Nothing here activates. Nothing here touches the legacy scalar, which stays
    the compatibility pointer to the ACTIVE permanent line until W9I-G promotes
    this one. Nothing here touches the temporary number, which keeps taking the
    customer's calls throughout.
    """
    from services import vapi

    tenant_id = str(tenant["id"])

    reg = await phone_registry.register_permanent(
        tenant_id=tenant_id, e164=e164, provider_account_sid=sub_sid,
        provider_sid=provider_sid, iso_country="IE",
        tenant_location_id=address.get("tenant_location_id") or None,
        regulatory_profile_id=str(profile.get("id") or "") or None)
    if reg["status"] != phone_registry.OK or not reg.get("row"):
        # Another worker won after our preflight. The number is real and paid
        # for, so it is NOT released -- releasing would throw away a regulated
        # number that took a regulator's approval to obtain, and the winner's row
        # may already describe it. Loud, and left for reconciliation.
        logger.error("Canonical permanent registration refused for tenant %s (%s) "
                     "-- number %s is held and needs reconciliation",
                     tenant_id, reg.get("detail"), e164[-4:])
        return {"status": PURCHASE_OUTCOME_UNKNOWN,
                "reason": "canonical_registration_conflict", "e164": e164}

    row = reg["row"]

    # ── routing, on the tenant's EXISTING assistant ───────────────────────
    assistant_id = str(tenant.get("vapi_assistant_id") or "")
    if not assistant_id:
        return {"status": ROUTING_FAILED, "reason": "no_assistant_on_tenant",
                "row": row}
    try:
        vapi_phone_id = await vapi.import_twilio_number(
            phone_number=e164, twilio_account_sid=sub_sid, twilio_auth_token=sub_tok,
            label=str(tenant.get("business_name") or "Open Lines"),
            server_url=f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended",
            api_key=vapi.get_tenant_vapi_key(tenant),
            assistant_id=assistant_id)
    except Exception as e:
        # The row stays `provisioning`: ours, not routable, retryable. The number
        # is NOT released. A month's rental is cheap next to losing a number that
        # required regulatory approval, and the customer still has their
        # temporary line while this is retried.
        logger.error("Vapi import failed for the permanent number on tenant %s: %s",
                     tenant_id, type(e).__name__)
        return {"status": ROUTING_FAILED, "reason": "vapi_import_failed", "row": row}

    updated = await phone_registry.attach_routing(
        number_row_id=str(row["id"]), vapi_phone_number_id=vapi_phone_id)

    return {"status": OK, "row": updated.get("row") or row, "e164": e164,
            "adopted": adopted, "vapi_phone_number_id": vapi_phone_id,
            # Said explicitly, because the whole gate turns on it.
            "activated": False,
            "next_gate": "w9i_g_health_and_promotion"}


# ── Stage P: what a customer is told ──────────────────────────────────────

REGULATORY_APPROVED = "REGULATORY_APPROVED"
PENDING_PLATFORM_ENABLEMENT = "PERMANENT_NUMBER_PENDING_PLATFORM_ENABLEMENT"
SEARCHING = "PERMANENT_NUMBER_SEARCHING"
INVENTORY_NONE = "PERMANENT_NUMBER_INVENTORY_UNAVAILABLE"
PROVISIONING = "PERMANENT_NUMBER_PROVISIONING"
ROUTING_SETUP = "PERMANENT_NUMBER_ROUTING_SETUP"
READY_FOR_ACTIVATION = "PERMANENT_NUMBER_READY_FOR_ACTIVATION"
NEEDS_REVIEW = "PERMANENT_NUMBER_NEEDS_REVIEW"

_CUSTOMER_MESSAGE = {
    REGULATORY_APPROVED: "Your business registration was approved.",
    PENDING_PLATFORM_ENABLEMENT:
        "Your registration is approved. We are completing the final setup for "
        "your permanent number and will let you know as soon as it is ready.",
    SEARCHING: "We are selecting your permanent number.",
    INVENTORY_NONE:
        "No numbers are available for your area right now. We are looking, and "
        "will contact you if this continues.",
    PROVISIONING: "Your permanent number is being set up.",
    ROUTING_SETUP: "Your permanent number is being connected to your receptionist.",
    READY_FOR_ACTIVATION:
        "Your permanent number is ready and will go live shortly.",
    NEEDS_REVIEW:
        "Your permanent number needs a manual check. Our team is on it.",
}


def customer_status(result_status: str, row: dict | None = None) -> dict:
    """Translate one acquisition outcome for a person.

    Carries no Bundle SID, Address SID, number SID, sub-account or provider
    error. The number itself is shown only once it is real AND recorded -- never
    from an in-flight purchase, because a number that then fails to register is
    one the customer would have written down.
    """
    mapping = {
        GATE_CLOSED: PENDING_PLATFORM_ENABLEMENT,
        NOT_APPROVED: REGULATORY_APPROVED,
        VERIFICATION_UNAVAILABLE: PROVISIONING,
        INVENTORY_UNAVAILABLE: INVENTORY_NONE,
        PROVIDER_UNAVAILABLE: PROVISIONING,
        PURCHASE_REFUSED: NEEDS_REVIEW,
        PURCHASE_OUTCOME_UNKNOWN: NEEDS_REVIEW,
        ROUTING_FAILED: ROUTING_SETUP,
        ALREADY_HELD: PROVISIONING,
        OK: READY_FOR_ACTIVATION,
        NOT_ELIGIBLE: PROVISIONING,
        NOT_FOUND: NEEDS_REVIEW,
    }
    status = mapping.get(str(result_status or ""), PROVISIONING)
    out = {"status": status, "message": _CUSTOMER_MESSAGE[status],
           # Never true in this gate. W9I-G is what makes a number live, and a
           # screen that says "ready to use" before then sends real callers to a
           # number that is not yet routable.
           "active": False}
    if status == READY_FOR_ACTIVATION and row and row.get("e164"):
        out["number"] = row["e164"]
    return out
