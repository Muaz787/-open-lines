"""The single place a Square webhook's identity is computed.  (W7D.1)

WHY THIS MODULE EXISTS
----------------------
Two consumers need the same answer to the same question for every booking
delivery:

  * W7B telemetry  -- "what did routing decide, and why", persisted to the
                      provider_webhook_events ledger as evidence.
  * W7D correctness -- "which tenant and location may this event mutate".

Before W7D.1 they each computed it independently. W7B called shadow_resolve(),
W7D called _resolve_identity(), and both issued the SAME two PostgREST reads --
list_tenants_by_square_merchant_id and load_location_candidates -- against the
same inputs, in the same request, microseconds apart. Four routing reads per
delivery where two would do.

That redundancy is not merely wasteful. It doubles the exposure of the one code
path that took the API down: W7D's production failure was an HTTP/2 GOAWAY on a
long-lived pooled connection, and the reason it fired on EVERY delivery rather
than occasionally was precisely that W7D had increased the number of PostgREST
calls per webhook. W7T fixed the transport; this removes the amplifier.

THE SHAPE, AND THE INVARIANT IT PROTECTS
----------------------------------------
    DB inputs (merchant candidates, location bindings)
            |
            v
      resolve_square_tenant_location()        <- pure, unchanged
            |
            v
      ONE immutable Resolution
            |-> telemetry persistence
            `-> booking reconciliation

Never this:

      resolver -> ledger -> read the ledger back -> booking reconciliation

THE LEDGER IS NEVER ROUTING AUTHORITY. It is a receipt: a durable record of
what was decided and why, written by a telemetry path that is explicitly
allowed to fail open. Reading it back to decide a mutation would make a
telemetry table load-bearing for correctness and would let a failed ledger
write silently change routing. The in-memory Resolution is the authority; the
ledger row merely describes it.

WHY THIS IS ITS OWN MODULE RATHER THAN A SHARED IMPORT
------------------------------------------------------
If correctness imported the helper from the observability module, W7D would
depend on W7B -- correctness importing telemetry, which is the dependency
backwards. Neither consumer owns identity, so identity lives on its own and
both import it.
"""

import logging

from db import square_routing
from services import square_webhook_resolution as resolver

logger = logging.getLogger(__name__)

# The only event family whose envelope carries an authoritative location, and
# the only one W7D routes. Kept here, beside the resolution it gates, rather
# than imported from either consumer.
BOOKING_EVENTS = {"booking.created", "booking.updated"}


async def load_and_resolve(meta: dict) -> tuple[resolver.Resolution, dict]:
    """The two DB reads plus the pure resolver. The one identity computation.

    Returns the Resolution and the binding it selected. The binding is returned
    because the caller that needs it should not have to re-scan the candidate
    list, and returning it costs nothing.

    Raises whatever the DB layer raises -- deliberately. A caller that must not
    fail on a read error is responsible for saying so; this function does not
    decide that for them, because the two callers want opposite things:
    telemetry fails open, correctness must not.
    """
    merchant_id = meta.get("merchant_id") or ""
    provider_location_id = meta.get("provider_location_id") or ""

    merchant_candidates = await square_routing.list_tenants_by_square_merchant_id(
        merchant_id)
    location_bindings = await square_routing.load_location_candidates(
        provider_location_id)

    res = resolver.resolve_square_tenant_location(
        merchant_id=merchant_id,
        merchant_candidates=merchant_candidates,
        provider_location_id=provider_location_id,
        location_bindings=location_bindings)

    binding = next((c for c in location_bindings
                    if str((c.get("binding") or {}).get("id") or "") == res.binding_id), {})
    return res, binding


async def resolve_event(event: dict) -> resolver.Resolution | None:
    """Resolve one envelope, once, for whoever needs it. Never raises.

    Returns None for a non-booking event, and None if identity could not be
    computed at all. None is not a routing decision -- it means "no answer is
    available here", and every consumer must treat it as "compute it yourself
    or do nothing", never as a refusal.

    Failing open matters: this runs at the top of a webhook endpoint whose real
    job is payments and bookings. If it raised, a routing-read hiccup would
    become a payment outage. When it returns None, W7D falls back to resolving
    for itself -- so correctness degrades to exactly the pre-W7D.1 behaviour,
    never to a wrong answer.
    """
    try:
        # Deferred import: observability imports this module at load time, so a
        # module-level import here would be circular. extract() lives in W7B
        # because that is where it is specified and tested, and duplicating it
        # to avoid one local import would be the worse trade.
        from services import square_webhook_observability as obs
        meta = obs.extract(event)
        if meta.get("event_type") not in BOOKING_EVENTS:
            return None
        res, _binding = await load_and_resolve(meta)
        return res
    except Exception as e:
        logger.error("W7D.1: could not resolve identity for a Square event: %s — "
                     "consumers will fall back to resolving independently", e)
        return None
