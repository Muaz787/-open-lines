"""Catalog webhook routing for a merchant that more than one tenant claims. (W7E)

THE PROBLEM THIS EXISTS TO FIX
------------------------------
`catalog.version.updated` was the last Square webhook family still choosing its
tenant with:

    get_tenant_by_square_merchant_id(merchant_id)   ->  .limit(1), no ORDER BY

That was tolerable while a merchant mapped to exactly one tenant. After the W7F
cutover it does not: ML66K1YVCD1P0 is claimed by both Shahid (appointments off)
and DANI (appointments on), and PostgREST returns whichever row it likes.

  * lands on Shahid  -> appointments disabled -> early return -> DANI silently
                        never learns its catalog changed
  * lands on DANI    -> correct

Same event, same data, two different outcomes decided by database row order.
Neither corrupts anything, which is exactly what makes it dangerous: the failure
is a refresh that quietly does not happen.

WHY CATALOG CANNOT REUSE THE BOOKING RESOLVER
---------------------------------------------
W7A resolves a booking by LOCATION: the merchant supplies a candidate set and
`booking.location_id` picks the exact binding out of it. A catalog envelope
carries no location -- it says "this merchant's catalog changed" and nothing
more. There is no location to resolve, and inventing one would mean guessing.

Catalog is MERCHANT-LEVEL provider truth, so the honest routing is not "pick a
tenant" at all:

    catalog.version.updated
            |
        merchant_id
            |
      ALL tenant candidates          <- no .limit(1), no first-row choice
            |
      filter by catalog eligibility  <- an explicit, independently testable rule
            |
      for EACH eligible tenant, independently:
            sync that tenant's own catalog
            record that tenant's own outcome
            isolate that tenant's own failure

Two tenants sharing a merchant both get refreshed. One tenant failing does not
stop the other from being attempted. A tenant that is deliberately ineligible
cannot suppress one that is not.

WHAT IS DELIBERATELY UNCHANGED
------------------------------
`sync()` itself. Its writes are already strictly tenant-scoped
(replace_square_services / replace_square_staff delete and insert under
.eq("tenant_id", ...)), so a shared merchant cannot leak one tenant's catalog
into another's cache. This module decides WHO gets synced; it does not change
WHAT a sync does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from db import square_routing

logger = logging.getLogger(__name__)

# Per-tenant outcomes. Never collapsed into a single ambiguous answer.
SYNCED = "synced"
SKIPPED = "skipped"
FAILED = "failed"

# Why a candidate was skipped. Each is a deliberate, permanent decision about
# that tenant -- never a transient error, and never a reason to retry.
SKIP_MERCHANT_MISMATCH = "merchant_mismatch"
SKIP_TENANT_INACTIVE = "tenant_inactive"
SKIP_NOT_CONNECTED = "square_not_connected"
SKIP_APPOINTMENTS_DISABLED = "appointments_disabled"

# Event-level results, written to the ledger as evidence.
RESULT_SYNCED = "catalog_synced"
RESULT_PARTIAL = "catalog_partial"
RESULT_FAILED = "catalog_failed"
RESULT_NO_ELIGIBLE = "catalog_no_eligible"
RESULT_NO_CANDIDATES = "catalog_no_candidates"
RESULT_NO_MERCHANT = "catalog_no_merchant_id"


@dataclass(frozen=True)
class TenantOutcome:
    """What happened for ONE tenant. Frozen: an outcome is a record, not a slot."""
    tenant_id: str
    result: str
    detail: str = ""

    def __repr__(self):
        return f"{self.tenant_id[:8]}…={self.result}" + (f"({self.detail})" if self.detail else "")


@dataclass(frozen=True)
class CatalogRouting:
    """The whole event's outcome, per tenant and in aggregate."""
    merchant_id: str = ""
    candidate_count: int = 0
    outcomes: tuple[TenantOutcome, ...] = field(default_factory=tuple)

    def _of(self, result: str) -> tuple[TenantOutcome, ...]:
        return tuple(o for o in self.outcomes if o.result == result)

    @property
    def synced(self) -> tuple[TenantOutcome, ...]:
        return self._of(SYNCED)

    @property
    def failed(self) -> tuple[TenantOutcome, ...]:
        return self._of(FAILED)

    @property
    def skipped(self) -> tuple[TenantOutcome, ...]:
        return self._of(SKIPPED)

    @property
    def eligible_count(self) -> int:
        return len(self.synced) + len(self.failed)

    @property
    def result(self) -> str:
        """Failures are classified BEFORE candidate counts, deliberately.

        A failed candidate lookup has zero candidates, and reporting that as
        "no candidates" would dress a transient, retryable error up as a
        permanent fact about our data — which is exactly the class of silent
        swallowing this workstream exists to remove.
        """
        if not self.merchant_id:
            return RESULT_NO_MERCHANT
        if self.failed:
            return RESULT_FAILED if not self.synced else RESULT_PARTIAL
        if self.synced:
            return RESULT_SYNCED
        if not self.candidate_count:
            return RESULT_NO_CANDIDATES
        return RESULT_NO_ELIGIBLE

    @property
    def should_retry(self) -> bool:
        """Retry only for failures a later attempt could actually fix.

        A raised exception is assumed transient -- a provider hiccup, a dropped
        connection -- and is worth another delivery. Everything else is not:

          * no candidates / none eligible  -- a permanent fact about our data.
            Retrying cannot make a tenant eligible, and Square would redeliver
            forever over a state we deliberately chose.
          * sync() returning ok=False      -- it reports exactly two structural
            conditions this way (tenant_not_found, not_connected) rather than
            raising. Neither improves by being asked again.
        """
        return any(o.detail.startswith("raised:") for o in self.failed)

    @property
    def summary(self) -> str:
        """A compact, non-sensitive line that answers the operator's question:
        which merchant, how many candidates, how many eligible, what happened.
        Carries tenant ids and outcome names only -- no credential, no catalog."""
        return (f"merchant={self.merchant_id or '-'} candidates={self.candidate_count} "
                f"eligible={self.eligible_count} synced={len(self.synced)} "
                f"failed={len(self.failed)} skipped={len(self.skipped)}"
                + (f" | {', '.join(repr(o) for o in self.outcomes)}" if self.outcomes else ""))


def catalog_sync_eligibility(tenant: dict, merchant_id: str) -> tuple[bool, str]:
    """May an UNSOLICITED catalog event rewrite this tenant's cached menu?

    Pure, total, and independently testable -- it takes a tenant row and answers
    yes/no with a reason, touching nothing.

    The bar is deliberately the one handle_catalog_update already enforced, kept
    verbatim rather than re-litigated, because it was set by a real incident:
    without the appointments gate, any catalog edit on a shared merchant
    rewrites the service and team caches of EVERY tenant connected to it,
    including tenants that do not book through Square. That fired once during W3
    fixture work and wrote an unrelated merchant's services into a live tenant.

    The merchant re-check is defensive. The caller already filtered by merchant,
    but this function is the thing that says "yes, write to this tenant", and it
    should not have to trust its caller to have done that correctly.
    """
    if not (tenant or {}).get("id"):
        return False, SKIP_MERCHANT_MISMATCH
    if (tenant.get("square_merchant_id") or "") != (merchant_id or ""):
        return False, SKIP_MERCHANT_MISMATCH
    # An operator-deactivated tenant does not receive unsolicited provider writes.
    if tenant.get("is_active") is False:
        return False, SKIP_TENANT_INACTIVE
    if not tenant.get("square_access_token"):
        return False, SKIP_NOT_CONNECTED
    if not tenant.get("square_appointments_enabled"):
        return False, SKIP_APPOINTMENTS_DISABLED
    return True, ""


async def route_catalog_event(event: dict) -> CatalogRouting:
    """Route one catalog.version.updated to every eligible tenant. Never raises.

    Returns a per-tenant record. The caller decides the HTTP response from
    `should_retry`; this function's job is to attempt every eligible tenant and
    report honestly, not to choose one.
    """
    merchant_id = str((event or {}).get("merchant_id") or "").strip()
    if not merchant_id:
        logger.warning("W7E: catalog event arrived with no merchant_id — nothing to route")
        return CatalogRouting()

    try:
        candidates = await square_routing.list_tenants_by_square_merchant_id(merchant_id)
    except Exception as e:
        # The candidate lookup is the one read with no per-tenant fallback. A
        # failure here means we do not know who to sync, which is transient and
        # worth a redelivery -- so it is reported as a failed pseudo-tenant.
        logger.error("W7E: candidate lookup failed for merchant %s: %s", merchant_id, e)
        return CatalogRouting(merchant_id=merchant_id, candidate_count=0,
                              outcomes=(TenantOutcome("", FAILED, f"raised: candidate lookup: {e}"),))

    # Sorted by tenant id so the ORDER of work is deterministic even though the
    # SET of work is what actually matters. Row order from the database must
    # never decide anything, and a stable order makes logs diffable.
    candidates = sorted(candidates, key=lambda t: str(t.get("id") or ""))

    outcomes: list[TenantOutcome] = []
    for tenant in candidates:
        tenant_id = str(tenant.get("id") or "")
        ok, reason = catalog_sync_eligibility(tenant, merchant_id)
        if not ok:
            logger.info("W7E: catalog event for merchant %s skips tenant %s — %s",
                        merchant_id, tenant_id or "?", reason)
            outcomes.append(TenantOutcome(tenant_id, SKIPPED, reason))
            continue

        # ── per-tenant isolation ────────────────────────────────────────────
        # One tenant's failure must never stop another from being attempted.
        # That is the whole point of routing to all of them.
        try:
            from services import square_booking
            result = await square_booking.sync(tenant_id)
        except Exception as e:
            logger.error("W7E: catalog sync RAISED for tenant %s (merchant %s): %s",
                         tenant_id, merchant_id, e)
            outcomes.append(TenantOutcome(tenant_id, FAILED, f"raised: {type(e).__name__}"))
            continue

        if not (result or {}).get("ok"):
            detail = str((result or {}).get("error") or "unknown")
            logger.error("W7E: catalog sync refused for tenant %s (merchant %s): %s",
                         tenant_id, merchant_id, detail)
            outcomes.append(TenantOutcome(tenant_id, FAILED, detail))
            continue

        logger.info("W7E: catalog refreshed for tenant %s (merchant %s): "
                    "%d services, %d staff",
                    tenant_id, merchant_id,
                    len(result.get("services") or []), len(result.get("staff") or []))
        outcomes.append(TenantOutcome(tenant_id, SYNCED))

    routing = CatalogRouting(merchant_id=merchant_id, candidate_count=len(candidates),
                             outcomes=tuple(outcomes))
    log = logger.warning if routing.failed else logger.info
    log("W7E catalog routing: %s", routing.summary)
    return routing
