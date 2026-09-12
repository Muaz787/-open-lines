"""Claim markers for Twilio regulatory resources (W9H-QA.4).

A claim marker is the string we put in a provider resource's FriendlyName so that,
later, we can ask the provider "did anyone already create one for THIS claim?" and
get an exact answer. It is what lets a worker adopt a crashed worker's resource
instead of creating a second one, and it is the only thing that makes deleting a
provider resource defensible: we remove one only when its marker names a claim we
hold.

WHY THIS IS CENTRALISED. W9H-QA.3 built the same idea inline for Addresses and got
the length wrong -- a 65-character marker exceeded Twilio's 64-character
FriendlyName FILTER limit, which silently disabled the reconciliation lookup that
the whole design depended on. One definition, one length budget, one test.

MEASURED PROVIDER LIMITS (W9H-QA.4, live, disposable sub-account):

    resource             FriendlyName max    list filter
    Address              64 (filter limit)   server-side
    EndUser              255                 NONE -- client-side match
    SupportingDocument   255                 NONE -- client-side match
    Bundle               255                 server-side

MARKER_MAX is set to the TIGHTEST of those, so one scheme is valid everywhere
rather than four schemes that are each valid somewhere.

Also measured: Twilio deduplicates none of these resources. Two identical creates
produce two resources. Our claim is the only protection, and a marker collision is
therefore a real signal -- more than one match means fail closed, never pick one.
"""
from __future__ import annotations

# The tightest measured FriendlyName budget across every resource we mark.
MARKER_MAX = 64

PREFIX = "ol"

# Short, distinguishable codes. Each resource must be tellable from the others, so
# a lookup for one kind can never match another's marker.
RESOURCE_CODES = {
    "address": "ad",
    "end_user": "eu",
    "supporting_document": "doc",
    "bundle": "bu",
}


def marker(resource: str, claim_id: str) -> str:
    """The FriendlyName for a provider resource created under one claim.

    Non-PII by construction: a fixed prefix, a resource code, and an opaque row id.
    No business name, no address, no representative, nothing about the customer --
    these strings are visible in the Twilio console and in provider logs.
    """
    code = RESOURCE_CODES.get(resource)
    if not code:
        raise ValueError(f"unknown provider resource: {resource!r}")
    claim = str(claim_id or "").strip()
    if not claim:
        raise ValueError("a claim marker needs a claim id")
    out = f"{PREFIX}:{code}:{claim}"
    if len(out) > MARKER_MAX:
        # Raised rather than truncated: a truncated marker still looks like a
        # marker but matches the wrong thing, or nothing at all.
        raise ValueError(f"claim marker is {len(out)} chars, over the {MARKER_MAX} "
                         f"budget for {resource}")
    return out


def is_marked(obj, expected: str) -> bool:
    """Does this provider object carry exactly this marker?

    Exact equality, never a prefix or substring test: an object marked for a
    different claim must not look like a match, and a claim id is a uuid whose
    string form can appear inside another only by exact equality anyway.
    """
    return str(getattr(obj, "friendly_name", "") or "") == expected


def matching(objects, expected: str) -> list:
    """Every object carrying this marker.

    Returns a LIST, not a first match, because the count is the decision: zero
    means nothing was created, one means adopt it, more than one means two workers
    both created and the caller must fail closed rather than choose.
    """
    return [o for o in (objects or []) if is_marked(o, expected)]


# ── logical scopes ─────────────────────────────────────────────────────────
# Deterministic, so two requests for the same logical resource compute the same
# claim. Ids and enums only -- never customer data, because scope_key is stored.

def end_user_scope(iso_country: str, end_user_type: str) -> str:
    """One EndUser per tenant, country and end-user type.

    NOT per profile or per address. W9G established that Twilio EndUsers are
    reusable across bundles and that one business identity is shared by all of a
    tenant's sibling profiles for a country -- resolve_end_user derives reuse from
    exactly that set. Scoping the claim any narrower would create a second
    regulatory identity for the same business the moment a tenant added a location.
    """
    return f"{iso_country}:{end_user_type}"


def supporting_document_scope(address_row_id: str, document_type: str) -> str:
    """One document per validated address, per document type.

    The address is the scope because Ireland's business_address document IS a
    reference to one validated Address SID -- a different premises needs a
    different document, and the same premises needs only one.
    """
    return f"{address_row_id}:{document_type}"


def bundle_scope(profile_id: str) -> str:
    """One Bundle per regulatory profile.

    The profile already carries the full filing scope -- tenant, country, number
    type, end-user type and address -- so keying on it is what stops a Bundle
    being shared across two distinct filings.
    """
    return str(profile_id)
