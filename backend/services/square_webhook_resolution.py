"""
W7A — deciding which ONE tenant location a Square webhook belongs to.

THE RULE
    MERCHANT IDENTIFIES THE CANDIDATE SET.
    LOCATION IDENTIFIES THE EXACT BINDING.
    AMBIGUITY FAILS CLOSED.

WHY THE LOCATION LEADS AND THE MERCHANT ONLY CROSS-CHECKS
A Square merchant can legitimately map to more than one OpenLines tenant, so
merchant_id cannot select a tenant. The provider location can: an appointment
happens somewhere, and that somewhere is bound to exactly one tenant location --
or the binding is ambiguous and nothing may be mutated at all.

Production already contains the ambiguity this exists to catch. One Square
location currently carries two bindings owned by two different tenants. It is
survivable today only because one of those tenants has appointments switched off,
which the eligibility predicate below treats as decisive.

EVERYTHING HERE IS PURE
resolve_square_tenant_location() reads no database, holds no credentials, calls
no provider, and never uses list order as a tiebreaker. Given the same evidence in
any order it returns the same answer. That is what makes the decision testable
without a database and what stops "whichever row came back first" from ever
becoming policy again.

CREDENTIALS ARE NOT PART OF IDENTITY
Nothing here selects or returns a Square token, and a tenant is never preferred
because it happens to hold one. Choosing a credential before identity is settled
is how a provider read gets performed as the wrong tenant.

W7A IS NOT WIRED IN. No webhook handler calls any of this yet -- that is W7B/C/D.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROVIDER_SQUARE = "square"

# Square's own status string for a location we may route appointments to. Any
# other value -- including NULL -- is refused here. services.call_location's
# binding_is_usable() is deliberately laxer (it accepts NULL) because W6A2 relies
# on that behaviour; webhook routing needs the strict reading and gets its own.
PROVIDER_STATUS_ACTIVE = "ACTIVE"

# ---------------------------------------------------------------------------
# Outcomes
#
# UNKNOWN_LOCATION / UNBOUND_LOCATION / INACTIVE_BINDING are three different
# operator problems and are kept apart on purpose:
#   UNKNOWN_LOCATION  we could not even determine a provider location -- our
#                     extraction is wrong, or this event family has no location
#   UNBOUND_LOCATION  a real Square location nobody has onboarded -- usually
#                     benign (the merchant added a location) and self-resolving
#   INACTIVE_BINDING  we know this location and it is switched off -- a config
#                     problem an operator can actually fix
# Collapsing them would tell an operator "not routed" and nothing about why.
# ---------------------------------------------------------------------------
RESOLVED = "resolved"
UNKNOWN_LOCATION = "unknown_location"
UNBOUND_LOCATION = "unbound_location"
INACTIVE_BINDING = "inactive_binding"
AMBIGUOUS_BINDING = "ambiguous_binding"
IDENTITY_CONFLICT = "identity_conflict"

# Reserved for the future merchant-only resolver (catalog events carry no
# location, so merchant_id is the only key they have). The LOCATION resolver
# below never returns it, and a test pins that -- an outcome that cannot occur
# would otherwise rot into a branch nobody can reason about.
UNKNOWN_MERCHANT = "unknown_merchant"

# Nothing may be mutated under any of these.
FAIL_CLOSED = frozenset({UNKNOWN_LOCATION, UNBOUND_LOCATION, INACTIVE_BINDING,
                         AMBIGUOUS_BINDING, IDENTITY_CONFLICT, UNKNOWN_MERCHANT})

# --- merchant classification (W7A §5) --------------------------------------
# "No merchant id in the payload" and "a merchant id nobody has onboarded" are
# different facts, and both currently produce an empty candidate set. Recording
# which one occurred keeps merchant identity meaningful even while the resolver
# tolerates an empty set for backward compatibility.
MERCHANT_ABSENT = "merchant_absent"      # payload carried no merchant_id
MERCHANT_UNMAPPED = "merchant_unmapped"  # merchant_id present, no tenant claims it
MERCHANT_MAPPED = "merchant_mapped"      # at least one tenant claims it


class Resolution:
    """The answer, plus enough context for an operator to act on a refusal."""

    __slots__ = ("outcome", "tenant_id", "tenant_location_id", "provider_location_id",
                 "binding_id", "merchant_status", "detail", "eligible_count",
                 "candidate_count")

    def __init__(self, outcome: str, *, tenant_id: str = "", tenant_location_id: str = "",
                 provider_location_id: str = "", binding_id: str = "",
                 merchant_status: str = "", detail: str = "",
                 eligible_count: int = 0, candidate_count: int = 0):
        self.outcome = outcome
        self.tenant_id = tenant_id
        self.tenant_location_id = tenant_location_id
        self.provider_location_id = provider_location_id
        self.binding_id = binding_id
        self.merchant_status = merchant_status
        self.detail = detail
        self.eligible_count = eligible_count
        self.candidate_count = candidate_count

    @property
    def ok(self) -> bool:
        return self.outcome == RESOLVED

    @property
    def may_mutate(self) -> bool:
        """The only property a caller should gate a write on."""
        return self.outcome == RESOLVED and bool(self.tenant_id and self.tenant_location_id)

    def __repr__(self):
        return (f"Resolution({self.outcome}, tenant={self.tenant_id or '-'}, "
                f"location={self.tenant_location_id or '-'}, {self.detail!r})")


def classify_merchant(merchant_id: str, merchant_candidates: list[dict]) -> str:
    """Distinguish an absent merchant id from an unmapped one. See §5."""
    if not (merchant_id or "").strip():
        return MERCHANT_ABSENT
    return MERCHANT_MAPPED if merchant_candidates else MERCHANT_UNMAPPED


def binding_is_routing_eligible(candidate: dict) -> tuple[bool, str]:
    """May a Square webhook route an APPOINTMENT to this binding? (ok, why_not).

    Strict on purpose, and stricter than W6A2's binding_is_usable(): every
    condition must be positively proven from the rows themselves. A NULL
    provider_status means the binding has never been confirmed against Square,
    which is not evidence that it is live.
    """
    binding = candidate.get("binding") or {}
    location = candidate.get("location")
    tenant = candidate.get("tenant")

    if (binding.get("provider") or "") != PROVIDER_SQUARE:
        return False, f"provider {binding.get('provider')!r}"
    if not str(binding.get("provider_location_id") or "").strip():
        return False, "binding has no provider_location_id"
    if (binding.get("provider_status") or "").upper() != PROVIDER_STATUS_ACTIVE:
        return False, f"provider_status {binding.get('provider_status')!r}"
    if not location:
        return False, "binding points at a missing tenant_location"
    if not location.get("active"):
        return False, "tenant_location is not active"
    if not location.get("booking_enabled"):
        return False, "tenant_location is not booking-enabled"
    if not tenant:
        return False, "tenant row is missing"
    if not tenant.get("square_appointments_enabled"):
        return False, "tenant does not have square_appointments_enabled"

    # The binding and the location must agree about who owns this. A disagreement
    # is an integrity fault, and routing an appointment under it would stamp a row
    # for one tenant using another tenant's binding.
    b_tid = str(binding.get("tenant_id") or "")
    l_tid = str(location.get("tenant_id") or "")
    if b_tid and l_tid and b_tid != l_tid:
        return False, f"binding tenant {b_tid} != location tenant {l_tid}"

    return True, ""


def eligible_candidates(candidates: list[dict]) -> list[dict]:
    return [c for c in candidates if binding_is_routing_eligible(c)[0]]


def resolve_square_tenant_location(
    *,
    merchant_id: str,
    merchant_candidates: list[dict],
    provider_location_id: str,
    location_bindings: list[dict],
) -> Resolution:
    """Decide the one tenant location this event belongs to, or refuse.

    `location_bindings` are the bundles built by db.square_routing --
    {"binding", "location", "tenant"} -- already fetched. This function performs
    no I/O.

    Order of the inputs is never consulted. Every branch either names exactly one
    binding or refuses; there is no path that picks from several.
    """
    merchant_status = classify_merchant(merchant_id, merchant_candidates or [])
    pid = str(provider_location_id or "").strip()

    if not pid:
        return Resolution(UNKNOWN_LOCATION, merchant_status=merchant_status,
                          detail="no provider location id in the evidence")

    candidates = list(location_bindings or [])
    if not candidates:
        return Resolution(UNBOUND_LOCATION, provider_location_id=pid,
                          merchant_status=merchant_status, candidate_count=0,
                          detail=f"no square binding exists for {pid}")

    eligible = eligible_candidates(candidates)

    if not eligible:
        reasons = sorted({binding_is_routing_eligible(c)[1] for c in candidates})
        return Resolution(INACTIVE_BINDING, provider_location_id=pid,
                          merchant_status=merchant_status,
                          candidate_count=len(candidates), eligible_count=0,
                          detail=f"{len(candidates)} binding(s), none eligible: "
                                 f"{'; '.join(reasons)}")

    if len(eligible) > 1:
        owners = sorted({str((c.get("location") or {}).get("tenant_id") or "")
                         for c in eligible})
        logger.error("square routing: AMBIGUOUS — provider location %s is eligible "
                     "for %d bindings across tenants %s; refusing to route",
                     pid, len(eligible), owners)
        return Resolution(AMBIGUOUS_BINDING, provider_location_id=pid,
                          merchant_status=merchant_status,
                          candidate_count=len(candidates), eligible_count=len(eligible),
                          detail=f"{len(eligible)} eligible bindings across "
                                 f"{len(owners)} tenant(s)")

    winner = eligible[0]
    binding = winner["binding"]
    location = winner["location"]
    tenant_id = str(location.get("tenant_id") or "")
    location_id = str(location.get("id") or "")

    # --- merchant cross-check ------------------------------------------------
    # When local merchant mappings EXIST they are mandatory: a location resolving
    # to a tenant that does not claim this merchant means our two sources of
    # identity disagree, and the safe reading of a disagreement is to stop.
    #
    # When NO tenant claims the merchant, the location is allowed to resolve on
    # its own. This is TRANSITIONAL COMPATIBILITY, not a design position: the only
    # appointment-enabled tenant in production today has square_merchant_id NULL,
    # so requiring the cross-check would refuse every one of its events. Retire
    # this branch once every Square-connected tenant records its merchant id.
    if merchant_candidates:
        claimed = {str(t.get("id") or "") for t in merchant_candidates}
        if tenant_id not in claimed:
            logger.error("square routing: IDENTITY CONFLICT — location %s resolves to "
                         "tenant %s, which does not claim merchant %s",
                         pid, tenant_id, merchant_id)
            return Resolution(IDENTITY_CONFLICT, provider_location_id=pid,
                              merchant_status=merchant_status,
                              candidate_count=len(candidates), eligible_count=1,
                              detail=f"location tenant {tenant_id} is not among the "
                                     f"{len(claimed)} tenant(s) claiming this merchant")

    return Resolution(RESOLVED, tenant_id=tenant_id, tenant_location_id=location_id,
                      provider_location_id=pid,
                      binding_id=str(binding.get("id") or ""),
                      merchant_status=merchant_status,
                      candidate_count=len(candidates), eligible_count=1,
                      detail="")
