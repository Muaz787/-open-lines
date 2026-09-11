"""
W6A2-D1 — freeze a reschedule, and stop.

WHAT THIS DOES, AND DELIBERATELY DOES NOT
It resolves the caller's two opaque refs, takes global ownership of the source
appointment, re-proves everything under that ownership, resolves the target slot
ONE final time, and writes a durable operation row. It makes ZERO provider
mutations: no CreateBooking, no CancelBooking. Only GETs, and only to establish
source truth.

WHY THE ORDER IS WHAT IT IS
Everything checked before ownership is advisory — the appointment can move
between reading it and owning it, and acting on the earlier read is the race that
ownership exists to remove. So the authoritative pass runs again afterwards.

THE INVARIANT THE REST OF W6A2 RESTS ON
No Square CreateBooking may happen unless the mutation claim's operation_id names
a persisted operation row. That is why the operation UUID is allocated before
ownership and written into the claim atomically: a claim naming a row that does
not exist then PROVES nothing was created, which is what makes an interrupted D1
safe to clean up.

After a successful insert the operation owns the appointment. Ownership is NOT
released here — D2 inherits it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import db.supabase as db
from db import locations as db_loc
from db import reschedule_ops as db_ops
from services import appointment_refs, mutation_ownership, slot_offers, square_booking

logger = logging.getLogger(__name__)

# Outcomes. Stable strings so the eventual tool layer and the tests agree.
OK = "ok"
BUSY = "busy"                      # another mutation owns the appointment
IN_PROGRESS = "in_progress"        # a live reschedule already exists for this source
BAD_REF = "bad_ref"
NOT_ELIGIBLE = "not_eligible"      # source is not in a reschedulable state
CROSS_LOCATION = "cross_location"
LEGACY_LOCATION = "legacy_location"  # pre-multi-location row; cannot be proven safe
SOURCE_CANCELLED = "source_cancelled"
SOURCE_UNKNOWN = "source_unknown"  # provider unreadable
SLOT_TAKEN = "slot_taken"
FAILED = "failed"


class Result:
    __slots__ = ("status", "operation_id", "detail")

    def __init__(self, status: str, operation_id: str | None = None, detail: str = ""):
        self.status = status
        self.operation_id = operation_id
        self.detail = detail

    def __repr__(self):
        return f"Result({self.status}, op={self.operation_id}, {self.detail!r})"


async def begin_reschedule(*, vapi_call_id: str, tenant_id: str, caller_phone: str,
                           appointment_ref: str, slot_ref: str) -> Result:
    """Resolve, own, validate, freeze. No provider mutation."""
    # ── selection capabilities (call-scoped, advisory) ──────────────────────
    ref_status, ref = await appointment_refs.resolve_for_cancel(
        vapi_call_id=vapi_call_id, appointment_ref=appointment_ref,
        tenant_id=tenant_id, caller_phone=caller_phone)
    if ref_status != appointment_refs.OK or not ref:
        return Result(BAD_REF, detail=f"appointment_ref {ref_status}")

    offer_status, offer = await slot_offers.resolve_for_booking(
        vapi_call_id=vapi_call_id, slot_ref=slot_ref, tenant_id=tenant_id,
        active_location_id="")      # location agreement is proven against the SOURCE below
    if offer_status != slot_offers.OK or not offer:
        return Result(BAD_REF, detail=f"slot_ref {offer_status}")

    source_id = ref["appointment_id"]

    # ── allocate identity BEFORE ownership, so the claim names its operation ──
    operation_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())

    own_status, claim = await mutation_ownership.acquire_for_reschedule(
        source_id, tenant_id, operation_id)
    if own_status == mutation_ownership.BUSY:
        return Result(BUSY)
    if own_status != mutation_ownership.ACQUIRED or claim is None:
        return Result(FAILED, detail="could not acquire ownership")

    try:
        return await _under_ownership(
            claim=claim, operation_id=operation_id, idempotency_key=idempotency_key,
            vapi_call_id=vapi_call_id, tenant_id=tenant_id, caller_phone=caller_phone,
            source_id=source_id, slot_ref=slot_ref, offer=offer)
    except Exception as e:
        logger.error("reschedule: begin failed for appointment %s: %s", source_id, e)
        await mutation_ownership.release(claim)
        return Result(FAILED, detail=str(e)[:200])


async def _under_ownership(*, claim, operation_id, idempotency_key, vapi_call_id,
                           tenant_id, caller_phone, source_id, slot_ref, offer) -> Result:
    # ── AUTHORITATIVE re-read. Everything above this line was advisory. ──────
    appt = await db.get_appointment_by_id(source_id)
    if not appt or str(appt.get("tenant_id")) != str(tenant_id):
        await mutation_ownership.release(claim)
        return Result(BAD_REF, detail="source not found under ownership")
    if str(appt.get("caller_phone") or "") != caller_phone:
        logger.error("reschedule: INTEGRITY — ref resolved to another caller's appointment "
                     "(tenant %s)", tenant_id)
        await mutation_ownership.release(claim)
        return Result(BAD_REF, detail="caller mismatch")
    if (appt.get("status") or "") not in ("confirmed", "pending_payment"):
        await mutation_ownership.release(claim)
        return Result(NOT_ELIGIBLE, detail=f"source status {appt.get('status')!r}")

    source_booking_id = appt.get("google_event_id") or ""
    if not source_booking_id:
        await mutation_ownership.release(claim)
        return Result(NOT_ELIGIBLE, detail="source has no provider booking")

    # ── same-location hard gate, against the RE-READ source ─────────────────
    src_loc = str(appt.get("tenant_location_id") or "")
    src_pid = str(appt.get("provider_location_id") or "")
    if not src_loc or not src_pid:
        # Every appointment predating the multi-location model has these NULL.
        # Nothing here can prove the target is the same place, so refuse.
        await mutation_ownership.release(claim)
        return Result(LEGACY_LOCATION, detail="source predates location tracking")

    if str(offer.get("tenant_location_id") or "") != src_loc \
            or str(offer.get("provider_location_id") or "") != src_pid:
        await mutation_ownership.release(claim)
        return Result(CROSS_LOCATION,
                      detail=f"source {src_loc}/{src_pid} vs target "
                             f"{offer.get('tenant_location_id')}/{offer.get('provider_location_id')}")

    binding_ok = await _binding_is_live(tenant_id, src_loc, src_pid)
    if not binding_ok:
        await mutation_ownership.release(claim)
        return Result(CROSS_LOCATION, detail="location binding is not active")

    tenant = await db.get_tenant_by_id(tenant_id) or {}
    token = await square_booking.get_access_token(tenant)
    if not token:
        await mutation_ownership.release(claim)
        return Result(FAILED, detail="no provider credential")

    # ── authoritative source snapshot (GET only) ────────────────────────────
    fetch_status, booking = await square_booking.get_booking_detailed(token, source_booking_id)
    if fetch_status == square_booking.FETCH_UNKNOWN:
        # D1 performs no provider mutation, so there is nothing to reconcile and
        # no reason to manufacture a long-lived recovery state. Release and let
        # the caller try again.
        await mutation_ownership.release(claim)
        return Result(SOURCE_UNKNOWN)

    if fetch_status == square_booking.FETCH_NOT_FOUND:
        await _reconcile_source_cancelled(source_id)
        await mutation_ownership.release(claim)
        return Result(SOURCE_CANCELLED, detail="provider reports the booking absent")

    booking_status = (booking.get("status") or "").upper()
    if "CANCELLED" in booking_status or booking_status == "DECLINED":
        await _reconcile_source_cancelled(source_id)
        await mutation_ownership.release(claim)
        return Result(SOURCE_CANCELLED, detail=booking_status)

    if str(booking.get("id") or "") != source_booking_id:
        logger.error("reschedule: INTEGRITY — provider returned booking %s for %s",
                     booking.get("id"), source_booking_id)
        await mutation_ownership.release(claim)
        return Result(FAILED, detail="provider booking id mismatch")

    if str(booking.get("location_id") or "") != src_pid:
        logger.error("reschedule: INTEGRITY FAILURE — appointment %s says location %s but "
                     "Square booking %s is at %s", source_id, src_pid,
                     source_booking_id, booking.get("location_id"))
        await mutation_ownership.release(claim)
        return Result(CROSS_LOCATION, detail="provider source location mismatch")

    # ── THE LAST live resolution of the target ──────────────────────────────
    seg = await _resolve_target_once(token, offer)
    if not seg:
        await mutation_ownership.release(claim)
        return Result(SLOT_TAKEN, detail="target slot is no longer bookable")

    cust_status, customer_id = await square_booking.resolve_customer(
        tenant_id=tenant_id, token=token, phone=caller_phone)
    if cust_status != "ok" or not customer_id:
        await mutation_ownership.release(claim)
        return Result(FAILED, detail=f"customer resolution {cust_status}")

    # ── claim the slot; a loss here costs nothing durable ───────────────────
    if not await slot_offers.claim(vapi_call_id, slot_ref, tenant_id):
        await mutation_ownership.release(claim)
        return Result(SLOT_TAKEN, detail="lost the slot claim race")

    # ── freeze ──────────────────────────────────────────────────────────────
    row = {
        "id": operation_id,
        "tenant_id": tenant_id,
        "source_appointment_id": source_id,
        "target_tenant_location_id": offer.get("tenant_location_id") or None,
        "target_provider_location_id": offer["provider_location_id"],
        "target_provider_customer_id": customer_id,
        "target_service_variation_id": offer["service_variation_id"],
        "target_service_variation_version": seg.get("service_variation_version")
                                            or offer.get("service_variation_version"),
        "target_team_member_id": seg["team_member_id"],
        "target_start_at_utc": seg.get("start_at") or offer["start_at_utc"],
        "target_duration_minutes": seg.get("duration_minutes") or offer.get("duration_minutes"),
        "target_service_name": offer.get("service_name") or None,
        "provider_idempotency_key": idempotency_key,
        "source_provider_booking_id": source_booking_id,
        "source_booking_version": booking.get("version"),
        "source_start_at_utc": booking.get("start_at"),
        "claim_token": claim.token,
        "state": db_ops.STATE_IN_PROGRESS,
    }

    try:
        created = await db_ops.insert_operation(row)
    except Exception as e:
        await slot_offers.release(vapi_call_id, slot_ref)
        await mutation_ownership.release(claim)
        logger.error("reschedule: operation insert failed for %s: %s", source_id, e)
        return Result(FAILED, detail="operation insert failed")

    if created is None:
        # Migration 022's live-source uniqueness. Another LIVE operation already
        # owns this source. We do NOT adopt it: our claim names a different
        # operation_id, and a provider call under that mismatch is exactly what
        # the invariant forbids.
        await slot_offers.release(vapi_call_id, slot_ref)
        await mutation_ownership.release(claim)
        existing = await db_ops.get_live_operation_for_source(source_id)
        logger.warning("reschedule: a live operation (%s) already exists for source %s",
                       (existing or {}).get("id"), source_id)
        return Result(IN_PROGRESS, operation_id=(existing or {}).get("id"))

    # Ownership is deliberately NOT released: the operation owns the appointment
    # from here, and D2 inherits both the claim and the claimed slot.
    logger.info("reschedule: froze operation %s for appointment %s", operation_id, source_id)
    return Result(OK, operation_id=operation_id)


async def _binding_is_live(tenant_id: str, tenant_location_id: str,
                           provider_location_id: str) -> bool:
    """The location must still be active and still map to the same provider id."""
    try:
        locations = await db_loc.list_locations(tenant_id)
        loc = next((l for l in locations if str(l.get("id")) == tenant_location_id), None)
        if not loc or not loc.get("active") or not loc.get("booking_enabled"):
            return False
        bindings = await db_loc.list_bindings(tenant_id)
        return any(str(b.get("tenant_location_id")) == tenant_location_id
                   and str(b.get("provider_location_id")) == provider_location_id
                   and (b.get("provider_status") or "").upper() == "ACTIVE"
                   for b in bindings)
    except Exception as e:
        logger.warning("reschedule: binding check failed for %s: %s", tenant_id, e)
        return False


async def _resolve_target_once(token: str, offer: dict) -> dict | None:
    """The final live catalog read. Everything it returns is frozen immediately."""
    start = datetime.fromisoformat(str(offer["start_at_utc"]).replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    seg = await square_booking.resolve_slot(
        token, offer["provider_location_id"], offer["service_variation_id"],
        [offer["team_member_id"]] if offer.get("team_member_id") else [], start)
    return seg if seg and seg.get("team_member_id") else None


async def _reconcile_source_cancelled(source_id: str) -> None:
    try:
        await db.update_appointment(source_id, {"status": "cancelled"})
        logger.info("reschedule: source %s was already cancelled at the provider — "
                    "reconciled locally", source_id)
    except Exception as e:
        logger.error("reschedule: could not reconcile cancelled source %s: %s", source_id, e)


async def cleanup_orphan_reschedule_claims(limit: int = 20) -> dict:
    """Release reschedule claims whose operation row never landed.

    Safe ONLY because of the invariant above: no provider call may happen before
    the operation is persisted, so a claim naming an absent operation proves
    nothing was created. Verified twice — the claim must be stale AND the
    operation must still be absent on a second read — and the delete is fenced on
    operation_id, token and timestamp so a re-acquired claim is never removed.
    """
    from db import mutation_claims as db_mc

    try:
        rows = await db_mc.list_stale_reschedule_claims(limit=limit)
    except Exception as e:
        logger.error("reschedule: orphan scan failed: %s", e)
        return {"scanned": 0, "error": str(e)[:200]}

    outcomes: dict[str, int] = {}
    for row in rows:
        op_id = row.get("operation_id")
        if not op_id:
            outcomes["no_operation_id"] = outcomes.get("no_operation_id", 0) + 1
            continue
        if await db_ops.get_operation(op_id):
            # A real operation owns this appointment. Not an orphan, and not D1's
            # to recover — that is the reschedule recovery worker's job.
            outcomes["live_operation"] = outcomes.get("live_operation", 0) + 1
            continue
        if await db_ops.get_operation(op_id):          # second look; see docstring
            outcomes["live_operation"] = outcomes.get("live_operation", 0) + 1
            continue
        ok = await db_mc.release_orphan_reschedule_claim(
            row["appointment_id"], op_id, row["claim_token"], row["claimed_at"])
        key = "released" if ok else "fenced"
        outcomes[key] = outcomes.get(key, 0) + 1
        if ok:
            logger.warning("reschedule: released an orphan claim on appointment %s "
                           "(operation %s never persisted)", row["appointment_id"], op_id)
    return {"scanned": len(rows), "outcomes": outcomes}
