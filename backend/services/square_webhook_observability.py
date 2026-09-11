"""
W7B — see what Square is actually delivering, and change nothing.

WHAT THIS IS FOR
Three questions have no answer today: what does Square send us, how often does it
send the same thing twice, and where would W7A's resolver route it? The existing
endpoint answers none of them -- Square events are processed inline and never
persisted, so there is no ledger, no delivery count, and no dead letter.

WHAT THIS IS NOT
It is not deduplication. A repeat delivery is COUNTED and then handed to the
legacy handler exactly as before. Short-circuiting duplicates would change
behaviour, and "persist, dedupe, and change nothing" is a contradiction -- true
dedupe belongs with the safe routing cutover, where the handler it protects is
also the one being replaced. A test pins that the duplicate still dispatches.

It is not routing either. The shadow resolution is recorded and read by nobody;
the legacy handler still picks its tenant with get_tenant_by_square_merchant_id().

FAIL OPEN, LOUDLY
Observability must never be able to take down bookings or payments. Every call
here is wrapped so that a ledger outage degrades to "we lost the evidence", not
"Square got a 500 and will retry your payment webhook for a day". The failure is
logged at ERROR because silently losing the evidence is still a real fault.
"""
from __future__ import annotations

import logging
import os

from db import provider_webhook_events as ledger
from db import square_routing
from services import square_webhook_resolution as resolver

logger = logging.getLogger(__name__)

PROVIDER = "square"

# Legacy dispatch outcomes, recorded around the existing match statement.
LEGACY_COMPLETED = "legacy_completed"
LEGACY_ERROR = "legacy_error"
LEGACY_UNHANDLED = "unhandled"

BOOKING_EVENTS = ("booking.created", "booking.updated")


def capture_raw_enabled() -> bool:
    """One real booking envelope is needed to confirm W7's core assumption.

    W7's design rests on booking webhooks carrying data.object.booking.location_id,
    which is inferred from the Booking object read live from the API -- no actual
    webhook envelope has ever been captured. This flag allows recording one, and
    is read at call time so it can be switched off without a deploy.
    """
    return (os.getenv("SQUARE_WEBHOOK_CAPTURE_RAW", "") or "").strip().lower() in (
        "1", "true", "yes", "on")


def extract(event: dict) -> dict:
    """Pull the identifiers out of a Square envelope. Side-effect free, total.

    Tolerates every event family, including ones no handler exists for: an
    unrecognised type still yields a row, because "what is Square actually
    sending us" is the question this workstream exists to answer.

    Only identifiers are extracted. A Square booking carries customer_id -- an
    opaque provider handle -- and no name or phone, and nothing here reaches for
    contact details from any envelope.
    """
    event = event or {}
    data = event.get("data") or {}
    obj = data.get("object") or {}

    out = {
        "provider_event_id": str(event.get("event_id") or ""),
        "event_type": str(event.get("type") or ""),
        "merchant_id": str(event.get("merchant_id") or ""),
        "object_type": str(data.get("type") or ""),
        "object_id": str(data.get("id") or ""),
        "provider_location_id": "",
        "provider_version": None,
        "provider_status": "",
        "provider_updated_at": "",
    }

    booking = obj.get("booking")
    if isinstance(booking, dict):
        out["object_id"] = str(booking.get("id") or out["object_id"])
        out["provider_location_id"] = str(booking.get("location_id") or "")
        out["provider_status"] = str(booking.get("status") or "")
        out["provider_updated_at"] = str(booking.get("updated_at") or "")
        if booking.get("version") is not None:
            try:
                out["provider_version"] = int(booking["version"])
            except (TypeError, ValueError):
                out["provider_version"] = None
        return out

    payment = obj.get("payment")
    if isinstance(payment, dict):
        out["object_id"] = str(payment.get("id") or out["object_id"])
        out["provider_location_id"] = str(payment.get("location_id") or "")
        out["provider_status"] = str(payment.get("status") or "")
        out["provider_updated_at"] = str(payment.get("updated_at") or "")
        # order_id is the key the legacy payment path actually routes on. Recorded
        # so the ledger can be joined to payments without a second lookup.
        if payment.get("order_id"):
            out["object_type"] = out["object_type"] or "payment"
        return out

    refund = obj.get("refund")
    if isinstance(refund, dict):
        out["object_id"] = str(refund.get("id") or out["object_id"])
        out["provider_location_id"] = str(refund.get("location_id") or "")
        out["provider_status"] = str(refund.get("status") or "")
        return out

    location = obj.get("location")
    if isinstance(location, dict):
        out["object_id"] = str(location.get("id") or out["object_id"])
        out["provider_location_id"] = str(location.get("id") or "")
        out["provider_status"] = str(location.get("status") or "")
        return out

    return out


async def shadow_resolve(meta: dict) -> resolver.Resolution:
    """What WOULD W7A decide for this event? Reads only; decides nothing.

    Scoped to booking events for now: they are the only family whose envelope
    carries an authoritative location, and the only one W7D will route first.
    """
    merchant_id = meta.get("merchant_id") or ""
    provider_location_id = meta.get("provider_location_id") or ""

    merchant_candidates = await square_routing.list_tenants_by_square_merchant_id(
        merchant_id)
    location_bindings = await square_routing.load_location_candidates(
        provider_location_id)

    return resolver.resolve_square_tenant_location(
        merchant_id=merchant_id,
        merchant_candidates=merchant_candidates,
        provider_location_id=provider_location_id,
        location_bindings=location_bindings)


async def observe(event: dict) -> dict | None:
    """Record one delivery, and shadow-resolve it when it is a booking event.

    Returns the ledger row, or None when nothing could be recorded. Never raises:
    the caller is a webhook endpoint whose real job is payments and bookings.
    """
    try:
        meta = extract(event)
    except Exception as e:
        logger.error("W7B: could not extract Square envelope metadata: %s", e)
        return None

    if not meta["provider_event_id"]:
        # Nothing to key a ledger row on. Square always sends event_id; if it did
        # not, that itself is worth seeing in the logs.
        logger.warning("W7B: Square event of type %r arrived with no event_id",
                       meta.get("event_type"))
        return None

    raw = None
    if capture_raw_enabled() and meta["event_type"] in BOOKING_EVENTS:
        raw = event

    try:
        row = await ledger.record_delivery(
            provider=PROVIDER, raw_envelope=raw, **meta)
    except Exception as e:
        logger.error("W7B: ledger write failed for Square event %s (%s): %s — "
                     "continuing to the legacy handler",
                     meta["provider_event_id"], meta["event_type"], e)
        return None

    if not row:
        return None

    if int(row.get("delivery_count") or 1) > 1:
        logger.warning("W7B: Square event %s (%s) delivered again — delivery #%s. "
                       "NOT suppressed: the legacy handler still runs.",
                       meta["provider_event_id"], meta["event_type"],
                       row.get("delivery_count"))

    if meta["event_type"] in BOOKING_EVENTS:
        try:
            res = await shadow_resolve(meta)
            await ledger.set_shadow_resolution(
                row["id"], resolution=res.outcome, resolution_detail=res.detail,
                merchant_status=res.merchant_status,
                resolved_tenant_id=res.tenant_id if res.ok else "",
                resolved_tenant_location_id=res.tenant_location_id if res.ok else "")
            log = logger.info if res.ok else logger.warning
            log("W7B shadow: event %s location %s -> %s (tenant=%s location=%s) "
                "[observation only; legacy routing unchanged]",
                meta["provider_event_id"], meta["provider_location_id"] or "-",
                res.outcome, res.tenant_id or "-", res.tenant_location_id or "-")
        except Exception as e:
            logger.error("W7B: shadow resolution failed for %s: %s",
                         meta["provider_event_id"], e)

    return row


async def record_legacy_result(row: dict | None, result: str, error: str = "") -> None:
    """Best effort, never raises. The legacy outcome is evidence, not control."""
    if not row or not row.get("id"):
        return
    try:
        await ledger.set_legacy_result(row["id"], result, error)
    except Exception as e:
        logger.error("W7B: could not record legacy result for %s: %s",
                     row.get("provider_event_id"), e)
