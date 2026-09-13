"""One Stripe Customer per signup attempt, and never a second (W9I-H.0.2).

THE CORRECTION THIS MODULE IS BUILT AROUND
An earlier design of mine said: if neither idempotency recovery nor a metadata
lookup answers, the claim stays unattached and the next attempt simply retries.
That is wrong, and it is the kind of wrong that bills a customer twice.

ABSENCE OF POSITIVE RECONCILIATION IS NOT PROOF THAT CUSTOMER.CREATE FAILED.
A search returns zero because the object does not exist, OR because the index is
eventually consistent, OR because the query could not run at all. Only the first
of those means there is nothing there, and nothing distinguishes them from here.

So the rule is asymmetric on purpose: a POSITIVE identification attaches a
Customer; nothing else ever authorises creating one. Zero results, an error, a
rate limit, an outage -- all produce the same answer, which is that a human
looks at it.

THREE LAYERS, IN ORDER OF AUTHORITY
  1. the payment-session row     the durable truth; decides who may call Stripe
  2. the idempotency key         collapses concurrent and same-day retries at the
                                 provider, inside its ~24h retention
  3. metadata on the Customer    evidence for positive reconciliation afterwards

The database is the authority. The provider's idempotency window is a
convenience that expires; the row does not.
"""
from __future__ import annotations

import logging
import os

from db import payment_sessions as sessions

logger = logging.getLogger(__name__)

OK = "ok"
#: Country access said no. Nothing was touched.
NOT_ALLOWED = "country_onboarding_not_open"
#: A provider create may have succeeded and we cannot prove otherwise. A human
#: resolves this; no automatic path creates another Customer.
RECONCILIATION_REQUIRED = "payment_customer_reconciliation_required"
#: Another worker holds the attempt right now. Retryable in a moment.
IN_PROGRESS = "payment_setup_in_progress"
#: Two Customers carry this signup's marker. Never resolved by choosing one.
INTEGRITY = "payment_customer_integrity_error"
PROVIDER_UNAVAILABLE = "payment_provider_unavailable"

#: The metadata field carrying the signup identity. Namespaced so it cannot
#: collide with anything else we or Stripe put on a Customer, and stable forever:
#: changing it would orphan every Customer already reconcilable by it.
METADATA_KEY = "openlines_onboarding_key"

#: Derived from the onboarding key alone, so every retry of one signup sends the
#: same key. NEVER from the email -- two signups can share one, and one signup
#: can change it mid-flow. Never regenerated because an attempt failed: a fresh
#: key on a retry is precisely how a retry becomes a second Customer.
IDEMPOTENCY_PREFIX = "openlines-setup-customer"


def idempotency_key(onboarding_key: str) -> str:
    key = str(onboarding_key or "").strip().lower()
    if not key:
        raise ValueError("an idempotency key needs an onboarding key")
    return f"{IDEMPOTENCY_PREFIX}/{key}"


def _stripe():
    import stripe
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = key
    return stripe


def _unresolved(reason: str) -> dict:
    """A state a human resolves, carrying WHY -- never a licence to create.

    The reason never reaches the customer. It exists so an operator can tell an
    unreadable index ("search_failed") from one that ran and matched nothing
    ("no_match"); the first is retried, the second is investigated. Both refuse
    to create, and that refusal is the invariant -- the reason is triage.
    """
    return {"status": RECONCILIATION_REQUIRED, "customer_id": "", "reason": reason}


async def ensure_customer(*, onboarding_key: str, iso_country: str,
                          email: str = "", business_name: str = "",
                          plan: str = "") -> dict:
    """The Stripe Customer for this signup, creating at most one, ever.

    Returns {"status": ..., "customer_id": str}. The caller has already decided
    country access; this decides nothing about eligibility and everything about
    identity.
    """
    session = await sessions.get(onboarding_key)

    # ── STATE 3: already bound. The common path after the first call. ─────
    if session and session.get("stripe_customer_id"):
        return {"status": OK, "customer_id": str(session["stripe_customer_id"]),
                "created": False}

    # ── STATE 2: a provider attempt happened and we never saw the answer ──
    if session and session.get("provider_attempt_at"):
        return await _reconcile(onboarding_key)

    # ── STATE 0/1: claim, then take the attempt, then call Stripe ─────────
    if not session:
        await sessions.claim(onboarding_key=onboarding_key, iso_country=iso_country)
        # The claim may have been lost to a concurrent caller. That is fine --
        # what matters is who wins the ATTEMPT below, which is the write that
        # authorises a provider call.

    if not await sessions.mark_attempt(onboarding_key):
        # Someone else owns the attempt. Re-read: they may already have attached.
        fresh = await sessions.get(onboarding_key)
        if fresh and fresh.get("stripe_customer_id"):
            return {"status": OK, "customer_id": str(fresh["stripe_customer_id"]),
                    "created": False}
        # In flight, or unresolved. Either way this caller must not create.
        return {"status": IN_PROGRESS, "customer_id": ""}

    # We own the attempt, and it is now durably recorded. Everything from here
    # is recoverable BECAUSE that write committed first.
    try:
        stripe = _stripe()
        params: dict = {"metadata": {METADATA_KEY: onboarding_key,
                                     "source": "onboarding"}}
        if plan:
            params["metadata"]["signup_plan"] = plan
        if email:
            params["email"] = email
        if business_name:
            params["name"] = business_name[:200]
        customer = stripe.Customer.create(
            **params, idempotency_key=idempotency_key(onboarding_key))
    except Exception as e:
        # The response did not arrive. The attempt is recorded, so no later run
        # will create another -- they will reconcile instead.
        logger.error("Customer.create outcome unknown for a signup: %s",
                     type(e).__name__)
        return await _reconcile(onboarding_key)

    if not await sessions.attach_customer(onboarding_key=onboarding_key,
                                          customer_id=str(customer.id)):
        # Another worker attached first. With the same idempotency key Stripe
        # returns the SAME Customer, so this should be identical -- but that is
        # checked rather than assumed.
        fresh = await sessions.get(onboarding_key)
        bound = str((fresh or {}).get("stripe_customer_id") or "")
        if bound and bound != str(customer.id):
            logger.error("PAYMENT SESSION INTEGRITY: two Customers for one signup")
            return {"status": INTEGRITY, "customer_id": ""}
        return {"status": OK, "customer_id": bound, "created": False}

    return {"status": OK, "customer_id": str(customer.id), "created": True}


async def _reconcile(onboarding_key: str) -> dict:
    """Find the Customer an unconfirmed create may have produced. Never creates.

    Two routes, both requiring POSITIVE identification:

      * retry the create with the SAME idempotency key. Inside Stripe's retention
        this returns the original object rather than making a new one -- it is a
        lookup wearing a create's clothing, which is exactly why the key must
        never be regenerated.
      * search the metadata marker, for when that window has passed.

    Every other outcome -- zero results, an error, a rate limit, two matches --
    returns a state a human resolves. None of them creates anything.
    """
    try:
        stripe = _stripe()
    except Exception:
        return _unresolved("provider_unconfigured")

    # Route 1: the same key. Inside retention Stripe replays the original.
    try:
        replayed = stripe.Customer.create(
            metadata={METADATA_KEY: onboarding_key, "source": "onboarding"},
            idempotency_key=idempotency_key(onboarding_key))
        found = str(getattr(replayed, "id", "") or "")
        if found:
            if await sessions.attach_customer(onboarding_key=onboarding_key,
                                              customer_id=found):
                logger.warning("recovered a Stripe Customer by idempotency replay")
                return {"status": OK, "customer_id": found, "created": False}
            fresh = await sessions.get(onboarding_key)
            bound = str((fresh or {}).get("stripe_customer_id") or "")
            if bound and bound != found:
                return {"status": INTEGRITY, "customer_id": ""}
            return {"status": OK, "customer_id": bound, "created": False}
    except Exception as e:
        # A mismatched-payload replay, an expired key, or an outage. None tells
        # us the Customer does not exist.
        logger.info("idempotency replay did not resolve the Customer: %s",
                    type(e).__name__)

    # Route 2: the metadata marker.
    try:
        results = stripe.Customer.search(
            query=f"metadata['{METADATA_KEY}']:'{onboarding_key}'", limit=3)
        matches = [str(c.id) for c in (getattr(results, "data", None) or [])]
    except Exception as e:
        # THE POINT OF THIS MODULE. A failed search is not an absent Customer.
        # THE distinction an operator needs. A search that could not run is
        # not a search that found nothing, and the two want different actions:
        # this one is retried once the account is readable again.
        logger.error("Customer search failed during reconciliation: %s",
                     type(e).__name__)
        return _unresolved("search_failed")

    if len(matches) == 1:
        if await sessions.attach_customer(onboarding_key=onboarding_key,
                                          customer_id=matches[0]):
            logger.warning("recovered a Stripe Customer by metadata")
            return {"status": OK, "customer_id": matches[0], "created": False}
        fresh = await sessions.get(onboarding_key)
        return {"status": OK,
                "customer_id": str((fresh or {}).get("stripe_customer_id") or ""),
                "created": False}
    if len(matches) > 1:
        logger.error("PAYMENT SESSION INTEGRITY: %d Customers carry one signup's "
                     "marker", len(matches))
        return {"status": INTEGRITY, "customer_id": ""}

    # Zero. Which may mean it does not exist, or that the index has not caught
    # up, or that this account cannot be searched. Not a licence to create.
    # A search that ran and matched nothing. Still not proof -- the index is
    # eventually consistent -- but a different investigation from the above.
    logger.error("a signup's Customer could not be positively identified -- "
                 "operator reconciliation required")
    return _unresolved("no_match")


async def resolve_for_tenant(onboarding_key: str) -> str:
    """The Customer bound to this signup, from OUR records. "" if none.

    Used at tenant creation instead of believing the customer id the browser
    hands back in its setup token. The onboarding key is already trusted -- it is
    what claims and resumes the tenant -- so the Customer can be resolved from it
    rather than accepted from the client.
    """
    session = await sessions.get(onboarding_key)
    return str((session or {}).get("stripe_customer_id") or "")
