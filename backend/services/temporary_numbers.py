"""The temporary test number a regulated tenant uses while review is pending
(W9I-E).

THE PRODUCT PROMISE THIS IMPLEMENTS
"Temporary test access is free WHILE GENUINE REGULATORY REVIEW IS PENDING." Both
halves are load-bearing, and the second is what most of this module is about: a
number handed out before anything was filed is not free test access during
review, it is a free phone line. So eligibility is grounded in a Bundle that has
actually been submitted -- not in the tenant's country, not in an onboarding
label, not in a form having been filled in.

NO COUNTRY IS EVER CHOSEN SILENTLY
The source of a temporary number is CONFIGURED, never inferred and never
defaulted. W9I-B found `purchase_number` silently falling back to Canada when a
country was unsupported, which is how an Irish business would have been given a
Canadian number and told it was theirs. If no source is configured, this module
says so and stops; it does not pick one.

WHAT IT DELIBERATELY DOES NOT DO
It does not start a trial, touch Stripe, send the permanent activation email,
buy a +353, promote anything, or retire anything. W9I-F and W9I-G own those. The
billing firewall is asserted structurally in the tests, because the failure mode
-- a customer charged for a line they were promised free while waiting on a
regulator -- is not one to discover from a support ticket.
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
NOT_ELIGIBLE = "temp_number_not_eligible"
UNAVAILABLE = "temp_number_unavailable"
ALREADY_ACTIVE = "temp_number_already_active"
PROVIDER_UNAVAILABLE = "provider_unavailable"
NO_INVENTORY = "temp_number_no_inventory"
HEALTH_FAILED = "temp_number_health_failed"
PURCHASE_OUTCOME_UNKNOWN = "temp_number_purchase_outcome_unknown"
NOT_FOUND = "tenant_not_found"


# ── Stage B: when is a tenant genuinely entitled to one? ───────────────────
#
# Pinned against W9I-D's state machine rather than described in prose, because
# "under review" has to mean one exact set of states.

#: A filing the provider is actually holding for review. PENDING_REVIEW is
#: Twilio's `pending-review` AND `in-review` (the state map folds both), and
#: `provisionally-approved` too -- W9C measured a purchase refused on the latter,
#: so it is not approval, but it IS the provider holding the filing.
REVIEW_PENDING_STATES = (st.PENDING_REVIEW,)

#: The PROVIDER's own status strings that mean a regulator is genuinely holding
#: the filing. Deliberately distinct from the local state map above: this is what
#: a fresh Bundle read must return before a number may be issued. Draft,
#: unsubmitted, rejected, action-required and expired are all absent, and so is
#: every local-only value -- none of them is a review in progress.
PROVIDER_REVIEW_STATES = ("pending-review", "in-review", "provisionally-approved")

#: The provider has decided, or asked for corrections. The customer KEEPS a
#: temporary number they already have -- taking a working line away on a
#: correction request would punish someone for a form -- but no NEW one is
#: issued, because nothing is pending review any more.
#:
#: How long free access should persist after a decision is an OPEN PRODUCT
#: QUESTION (W9I-E Stage N). Deliberately no 7- or 30-day rule is encoded here:
#: an arbitrary deadline nobody approved would quietly become the policy.
DECIDED_STATES = (st.MORE_INFORMATION_REQUIRED, st.REJECTED, st.APPROVED)

#: Not yet filed. A temporary number here would be free service with no review
#: pending at all.
NOT_YET_FILED_STATES = (st.NOT_STARTED, st.DETAILS_REQUIRED,
                        st.ADDRESS_VALIDATION_FAILED, st.READY_TO_SUBMIT)

#: The submit call's outcome was never confirmed. Not a refusal and not an
#: entitlement: it is a question, and the answer is at the provider. The caller
#: reconciles before asking again.
NEEDS_RECONCILIATION_STATES = (st.SUBMITTING,)


# ── Stage C: the source policy ─────────────────────────────────────────────

class TemporarySource:
    """Where a temporary number comes from, and what it is allowed to be."""

    def __init__(self, *, enabled: bool, iso_country: str, number_type: str,
                 area_code: str = "", customer_visible: bool = True,
                 max_attempts: int = 3):
        self.enabled = enabled
        self.iso_country = iso_country
        self.number_type = number_type
        self.area_code = area_code
        self.customer_visible = customer_visible
        self.max_attempts = max_attempts

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (f"TemporarySource(enabled={self.enabled}, "
                f"iso_country={self.iso_country!r}, number_type={self.number_type!r})")


#: Voice is the only capability a temporary number MUST have -- it exists so a
#: caller can reach the receptionist. SMS is explicitly NOT required: Irish and
#: many other numbers are voice-only, and W9 already established that Square
#: sends DANI's appointment notifications rather than OpenLines SMS. Requiring
#: SMS here would reject perfectly good inventory for a capability nothing uses.
REQUIRED_CAPABILITIES = ("voice",)

SOURCE_ENV = "TEMP_NUMBER_SOURCE_COUNTRY"
TYPE_ENV = "TEMP_NUMBER_TYPE"
ENABLED_ENV = "TEMP_NUMBER_ENABLED"


def source_policy() -> TemporarySource:
    """The configured source. Disabled, and country-less, until someone says.

    There is NO default country on purpose. A default is exactly how a business
    ends up with a number from a country nobody chose, and "it was the fallback"
    is not something to explain to a customer afterwards.
    """
    return TemporarySource(
        enabled=os.getenv(ENABLED_ENV, "").strip().lower() in ("1", "true", "yes", "on"),
        iso_country=os.getenv(SOURCE_ENV, "").strip().upper(),
        number_type=os.getenv(TYPE_ENV, "local").strip().lower(),
    )


def source_problem(policy: TemporarySource) -> str:
    """Why this policy cannot be used, or "". Never guesses a usable one."""
    if not policy.enabled:
        return "temporary_numbers_disabled"
    if not policy.iso_country:
        return "no_source_country_configured"
    if policy.iso_country not in telephony.SUPPORTED_COUNTRIES:
        return f"source_country_not_supported:{policy.iso_country}"
    from services import onboarding_lifecycle as ob
    if ob.needs_regulatory_clearance(policy.iso_country):
        # A regulated source would buy through the unregulated path, which carries
        # no Bundle and no Address -- sidestepping the permanent gate and the
        # filing the number is supposed to depend on. It would also hand the
        # customer a +353 that is NOT the one their regulatory filing covers,
        # while the whole point of the temporary line is that it is not theirs.
        return f"source_country_is_regulated:{policy.iso_country}"
    return ""


# ── eligibility ────────────────────────────────────────────────────────────

async def eligibility(tenant: dict) -> dict:
    """May this tenant have a temporary test number right now, and why/why not?

    Read-only. Spends nothing, and is the preflight that stops a predictable
    purchase before it happens.
    """
    tenant_id = str(tenant.get("id") or "")
    country = str(tenant.get("business_country_code") or "").strip().upper()

    if not country:
        return _no("business_country_not_confirmed")
    from services import onboarding_lifecycle as ob
    if not ob.needs_regulatory_clearance(country):
        # An unregulated country gets its permanent number at signup. A temporary
        # one would be a second line nobody needs and someone pays for.
        return _no("country_is_not_regulated")

    rows = await db_phones.list_for_tenant(tenant_id)
    live_perm = [r for r in rows
                 if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                 and r.get("status") in lifecycle.CURRENT_PERMANENT_STATUSES]
    if live_perm:
        # They have the real thing, or are moments from it. W9I-G retires the
        # temporary after promotion; issuing one now would invert that.
        return _no("permanent_number_already_live")

    live_temp = [r for r in rows
                 if r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
                 and r.get("status") in lifecycle.LIVE_TEMPORARY_STATUSES]
    if live_temp:
        row = live_temp[0]
        return {"eligible": False, "reason": ALREADY_ACTIVE, "detail": "",
                "profile": None, "existing": row,
                "active": row.get("status") == lifecycle.STATUS_ACTIVE}

    profiles = [p for p in await db_reg.list_profiles(tenant_id)
                if str(p.get("iso_country") or "").upper() == country]
    if not profiles:
        return _no("no_regulatory_filing")

    # The furthest-along filing decides. A tenant with two premises who has filed
    # one of them is genuinely under review.
    states = {str(p.get("state") or "") for p in profiles}
    if states & set(NEEDS_RECONCILIATION_STATES):
        return _no("filing_outcome_unconfirmed", detail="reconcile_before_asking_again")
    pending = [p for p in profiles if str(p.get("state") or "") in REVIEW_PENDING_STATES]
    if pending:
        return {"eligible": True, "reason": "", "detail": "",
                "profile": pending[0], "existing": None, "active": False}
    if states & set(DECIDED_STATES):
        # Not eligible for a NEW one. Says which, so the caller can tell a
        # customer whose filing was rejected apart from one who is approved and
        # about to get the real number.
        decided = sorted(states & set(DECIDED_STATES))
        return _no("filing_already_decided", detail=decided[0])
    return _no("filing_not_submitted",
               detail=sorted(states & set(NOT_YET_FILED_STATES))[:1] or None)


def _no(reason: str, detail=None) -> dict:
    return {"eligible": False, "reason": reason, "detail": detail,
            "profile": None, "existing": None, "active": False}


# ── Stage E: the one acquisition entry point ───────────────────────────────

async def ensure_temporary_number(tenant_id: str, *,
                                  verified_provider_status: str) -> dict:
    """Give this tenant a working test line, if they are genuinely entitled to one.

    Server-owned end to end. The caller names a tenant and nothing else: not a
    country, not an account, not a number, not a status. Every one of those is
    decided here or by configuration.

    Never purchases twice. Never marks a number routable before the voice path is
    proved. Never touches billing.

    `verified_provider_status` is REQUIRED and must be a state the caller read
    DIRECTLY from the provider moments ago. It is a keyword with no default so
    that acquiring a number without provider proof is not something a caller can
    do by forgetting: W9I-H.AUTO found eligibility resting on
    tenant_regulatory_profiles.state, a local memory of a delivery, where a
    stale or forged `pending_review` would have bought someone a free line.
    """
    if str(verified_provider_status or "").strip().lower() not in PROVIDER_REVIEW_STATES:
        # Includes "" -- a caller with nothing to show gets nothing.
        logger.error("temporary number refused for tenant %s: provider status %r "
                     "is not a verified review state", tenant_id,
                     verified_provider_status)
        return {"status": NOT_ELIGIBLE, "reason": "provider_review_not_verified",
                "detail": str(verified_provider_status or "")}
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    if not rows:
        return {"status": NOT_FOUND}
    tenant = rows[0]

    # ── 1. PREFLIGHT, BEFORE ANY SPEND ────────────────────────────────────
    elig = await eligibility(tenant)
    if not elig["eligible"]:
        if elig["reason"] == ALREADY_ACTIVE:
            row = elig["existing"]
            return {"status": ALREADY_ACTIVE, "row": row,
                    "e164": row.get("e164"), "active": elig["active"]}
        return {"status": NOT_ELIGIBLE, "reason": elig["reason"],
                "detail": elig["detail"]}

    policy = source_policy()
    problem = source_problem(policy)
    if problem:
        # A configuration gap is OUR problem, and it is reported as one. It is
        # emphatically not a reason to pick a country.
        logger.error("temporary number requested for tenant %s but the source "
                     "policy is unusable: %s", tenant_id, problem)
        return {"status": UNAVAILABLE, "reason": problem}

    # ── 2. THE TENANT'S ONE SUB-ACCOUNT ───────────────────────────────────
    sub = await tenant_subaccount.ensure(tenant)
    if sub["status"] != tenant_subaccount.OK:
        return {"status": PROVIDER_UNAVAILABLE, "reason": "subaccount_unavailable"}
    sub_sid, sub_tok = sub["sid"], sub["auth_token"]

    # ── 3. RECONCILE BEFORE BUYING (Stage L) ──────────────────────────────
    # A previous attempt may have bought a number and lost the response. Asking
    # the provider what this sub-account already holds is what stops a purchase
    # loop, and it is cheap compared with what it prevents.
    held = await held_numbers(sub_sid, sub_tok)
    if held["status"] != OK:
        return {"status": PROVIDER_UNAVAILABLE, "reason": "inventory_unreadable"}
    if held["numbers"]:
        # We already own something on this tenant's account. Adopt it rather than
        # buy another; the canonical row is what was missing, not the number.
        existing = pick_unambiguous(held["numbers"])
        if existing is None:
            # More than one candidate and no way to tell which is ours. Guessing
            # would bind a test line -- and its eventual RELEASE -- to an
            # arbitrary number. Nothing is bought and nothing is adopted.
            logger.error("tenant %s holds %d unassigned numbers -- operator review "
                         "required before a temporary line can be adopted",
                         tenant_id, len(held["numbers"]))
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "multiple_unassigned_numbers"}
        logger.warning("tenant %s already holds a number on its sub-account -- "
                       "adopting rather than purchasing", tenant_id)
        return await _register_and_activate(
            tenant=tenant, e164=existing["e164"], provider_sid=existing["sid"],
            sub_sid=sub_sid, sub_tok=sub_tok, iso_country=policy.iso_country,
            adopted=True)

    # ── 4. INVENTORY ──────────────────────────────────────────────────────
    try:
        candidate = await telephony.find_available_number(
            sub_sid, sub_tok, policy.iso_country,
            preferred_area_code=policy.area_code or "")
    except telephony.CountryNotSupported:
        return {"status": UNAVAILABLE,
                "reason": f"source_country_not_supported:{policy.iso_country}"}
    except Exception as e:
        logger.error("temporary number search failed for tenant %s: %s", tenant_id, e)
        return {"status": PROVIDER_UNAVAILABLE, "reason": "inventory_search_failed"}
    if not candidate:
        return {"status": NO_INVENTORY, "reason": "no_numbers_available",
                "iso_country": policy.iso_country}

    # ── 5. PURCHASE, EXACTLY ONCE ─────────────────────────────────────────
    try:
        e164, provider_sid = await telephony.purchase_number_with_sid(
            sub_sid, sub_tok, candidate)
    except Exception as e:
        # UNKNOWN OUTCOME. The purchase may have succeeded before the error; a
        # blind retry is how a tenant ends up paying for two numbers. Ask the
        # provider what it now holds, exactly as the submission path does.
        logger.error("temporary number purchase errored for tenant %s: %s", tenant_id, e)
        recheck = await held_numbers(sub_sid, sub_tok)
        if recheck["status"] != OK:
            # We cannot tell. Fail closed and say so: an operator reconciles, and
            # nothing here loops.
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "provider_unreachable_after_purchase"}
        got = pick_unambiguous(recheck["numbers"])
        if got is None:
            if not recheck["numbers"]:
                # Nothing held. That may mean the purchase failed, or that the
                # listing is momentarily wrong. Neither is proof, so the caller
                # reconciles rather than buying again.
                return {"status": PURCHASE_OUTCOME_UNKNOWN,
                        "reason": "purchase_unconfirmed_and_nothing_held"}
            return {"status": PURCHASE_OUTCOME_UNKNOWN,
                    "reason": "multiple_unassigned_numbers"}
        logger.warning("temporary purchase for tenant %s errored but the provider "
                       "holds %s -- adopting", tenant_id, got["sid"][:8])
        e164, provider_sid = got["e164"], got["sid"]

    return await _register_and_activate(
        tenant=tenant, e164=e164, provider_sid=provider_sid, sub_sid=sub_sid,
        sub_tok=sub_tok, iso_country=policy.iso_country, adopted=False)


async def held_numbers(sub_sid: str, sub_tok: str) -> dict:
    """What this sub-account actually holds. The answer to "did I already buy?".

    Twilio's per-sub-account listing is authoritative and immediately consistent,
    which is what makes it a usable oracle here -- unlike a search index, whose
    silence proves nothing.
    """
    listing = await telephony.fetch_subaccount_numbers(sub_sid, sub_tok)
    if not listing.ok:
        return {"status": PROVIDER_UNAVAILABLE, "numbers": []}
    return {"status": OK,
            "numbers": [{"e164": n.phone_number, "sid": n.sid}
                        for n in listing.numbers]}


#: Kept only for tests written against the old private name. NOT used by this
#: module: an alias binds at definition time, so calling through it would make
#: the real function unpatchable and silently skip a test's fake.
_held_numbers = held_numbers


def pick_unambiguous(numbers: list[dict]) -> dict | None:
    """The one number this tenant's temporary line is, or None.

    W9I-H.AUTO found this path adopting numbers[0]. The permanent path already
    refuses to guess, and the reason applies just as hard here: picking
    arbitrarily attaches a customer's test line -- and later its retirement,
    which RELEASES a number -- to whichever row happened to sort first.

    Zero is not ambiguous, it is absent. Two or more is a question for a human.
    """
    if len(numbers) != 1:
        return None
    return numbers[0]


async def _register_and_activate(*, tenant: dict, e164: str, provider_sid: str,
                                 sub_sid: str, sub_tok: str, iso_country: str,
                                 adopted: bool) -> dict:
    """Record the number, wire the voice path, prove it, then make it routable.

    The order is the activation contract and is NOT weakened for temporary
    numbers: a row becomes `active` only after the voice path is configured and
    checked. A number that answers with silence is worse than no number, because
    the customer tells their callers to use it.
    """
    from services import vapi

    tenant_id = str(tenant["id"])

    reg = await phone_registry.register_temporary(
        tenant_id=tenant_id, e164=e164, provider_account_sid=sub_sid,
        provider_sid=provider_sid, iso_country=iso_country)
    if reg["status"] != phone_registry.OK or not reg.get("row"):
        # The uniqueness indexes refused it -- another worker won the race after
        # our preflight. Hand the number back rather than leave it billing for a
        # row that does not exist.
        logger.error("canonical temporary registration refused for tenant %s (%s)",
                     tenant_id, reg.get("detail"))
        if not adopted:
            try:
                await telephony.release_number(sub_sid, sub_tok, e164)
            except Exception as e:
                logger.error("rollback release of %s failed: %s", e164, e)
        return {"status": NOT_ELIGIBLE, "reason": reg.get("detail") or "conflict"}

    row = reg["row"]

    # ── Vapi: the SAME assistant, a SECOND phone record ───────────────────
    # One assistant serves every number a tenant has. Creating a second assistant
    # because a second number exists would give the temporary line a different
    # receptionist -- different prompt, different knowledge base, drifting apart
    # from the day the permanent number arrives.
    assistant_id = str(tenant.get("vapi_assistant_id") or "")
    if not assistant_id:
        return {"status": HEALTH_FAILED, "reason": "no_assistant_on_tenant",
                "row": row}
    # FAIL CLOSED on an unrecoverable tenant credential (W9I-H.AUTO.1 Stage J).
    # Falling back to the parent organisation here would create this tenant's
    # phone record under shared ownership, autonomously and invisibly.
    key = vapi.resolve_tenant_key(tenant)
    if not key["ok"]:
        return {"status": HEALTH_FAILED, "reason": vapi.KEY_UNAVAILABLE, "row": row}
    try:
        vapi_phone_id = await vapi.import_twilio_number(
            phone_number=e164, twilio_account_sid=sub_sid, twilio_auth_token=sub_tok,
            label=f"{tenant.get('business_name') or 'Open Lines'} (temporary)",
            server_url=f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended",
            api_key=key["key"],
            assistant_id=assistant_id)
    except Exception as e:
        logger.error("Vapi import failed for temporary number on tenant %s: %s",
                     tenant_id, e)
        return {"status": HEALTH_FAILED, "reason": "vapi_import_failed", "row": row}

    health = await _health_check(sub_sid, sub_tok, e164)
    if not health["ok"]:
        # Left `provisioning`: ours, not routable, and deterministically
        # retryable. NOT released -- a health blip must not throw away a number we
        # just paid for.
        logger.error("temporary number %s for tenant %s failed its health check: %s",
                     e164[-4:], tenant_id, health["reason"])
        return {"status": HEALTH_FAILED, "reason": health["reason"], "row": row}

    activated = await phone_registry.mark_temporary_active(
        tenant_id=tenant_id, number_row_id=str(row["id"]),
        vapi_phone_number_id=vapi_phone_id)
    return {"status": OK, "row": activated.get("row") or row, "e164": e164,
            "iso_country": iso_country, "adopted": adopted,
            "vapi_phone_number_id": vapi_phone_id}


async def _health_check(sub_sid: str, sub_tok: str, e164: str) -> dict:
    """Is an inbound call to this number actually going to reach us?

    THE SAME QUESTION the permanent contract asks, and deliberately not a weaker
    one: the number is read back FROM THE PROVIDER and must carry a voice route.
    Trusting the import call's return value would prove only that we asked.
    """
    try:
        listing = await telephony.fetch_subaccount_numbers(sub_sid, sub_tok)
    except Exception as e:
        return {"ok": False, "reason": f"provider_unreadable:{type(e).__name__}"}
    if not listing.ok:
        return {"ok": False, "reason": "provider_unreadable"}
    for n in listing.numbers:
        if n.phone_number != e164:
            continue
        if getattr(n, "voice_url", "") or getattr(n, "voice_application_sid", ""):
            return {"ok": True, "reason": ""}
        return {"ok": False, "reason": "no_voice_route_configured"}
    return {"ok": False, "reason": "number_not_held_by_subaccount"}


# ── Stage S: what a customer is told ───────────────────────────────────────

REGULATORY_UNDER_REVIEW = "REGULATORY_UNDER_REVIEW"
TEMP_NUMBER_PREPARING = "TEMP_NUMBER_PREPARING"
TEMP_NUMBER_READY = "TEMP_NUMBER_READY"
TEMP_NUMBER_UNAVAILABLE = "TEMP_NUMBER_UNAVAILABLE"


def customer_view(row: dict | None, *, source_iso: str = "") -> dict:
    """How the temporary line looks to the customer.

    ALWAYS labelled temporary, and never described as their Irish number. If the
    source is not their own country, that is stated rather than left to be
    discovered from the dialling code -- a business that thinks a +44 number is
    its new Irish line will put it on its website.
    """
    if not row:
        return {"status": TEMP_NUMBER_UNAVAILABLE, "number": "", "temporary": True,
                "message": "We will set up a temporary test number while your "
                           "registration is reviewed."}
    status = str(row.get("status") or "")
    if status != lifecycle.STATUS_ACTIVE:
        return {"status": TEMP_NUMBER_PREPARING, "number": "", "temporary": True,
                "message": "Your temporary test number is being set up."}
    iso = str(row.get("iso_country") or source_iso or "").upper()
    return {
        "status": TEMP_NUMBER_READY,
        "number": row.get("e164"),
        "temporary": True,
        "iso_country": iso,
        "message": ("This is a temporary test number so you can try your "
                    "receptionist while your phone-number registration is "
                    "reviewed. It is not your permanent business number."),
    }
