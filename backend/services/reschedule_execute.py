"""
W6A2-D2 — create the replacement, cancel the source, and survive every crash
window between the two.

WHAT D1 LEFT BEHIND
D1 froze an operation and made zero provider mutations. It holds two things this
module inherits and never re-derives: the global mutation claim on the source
appointment, and a row in appointment_reschedule_operations containing the
COMPLETE CreateBooking payload plus the idempotency key that payload will always
be sent with.

THE ONE RULE EVERYTHING ELSE FOLLOWS FROM
A retry is only safe when it is the SAME request. So the provider body is built
exclusively from frozen operation columns — never from a slot offer, a catalog
read, an availability response or a customer lookup, all of which move. A stable
idempotency key over a body that can change is worse than no stable key at all:
Square would answer a genuine duplicate with a conflict instead of the original
booking.

ORDERING, AND WHY IT IS NOT THE OBVIOUS ONE
Create the replacement FIRST, cancel the source SECOND. Cancel-then-book is the
ordering that loses a caller their appointment when the new time turns out to be
gone. The cost of this ordering is a window in which both bookings exist, and
that window is exactly what the operation states describe: replacement_created
is not an error, it is honest unfinished work, and it is findable without the
call that started it.

WHAT IS DELIBERATELY NOT AUTOMATED
If the merchant has touched the source booking since D1 read it, no automatic
cancellation happens — ever, in any recovery pass. The caller now has a real
replacement and the merchant has a real edit, and a sweeper that resolved that
by deleting one of them would be destroying information nobody asked it to
destroy. It becomes an operator incident with ownership held.

NO TOOL IS EXPOSED BY THIS MODULE. The reschedule tool schema, prompt flow and
spoken behaviour are deliberately absent until this lifecycle has passed its
gate.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import db.supabase as db
from db import appointment_refs as db_ar
from db import mutation_claims as db_mc
from db import reschedule_ops as db_ops
from services import slot_offers, square_booking

logger = logging.getLogger(__name__)

# Outcomes. Stable strings; the eventual tool layer and the tests agree on these.
COMPLETED = "completed"                  # replacement live, source cancelled
CREATE_FAILED = "create_failed"          # provider refused; source untouched
CREATE_UNKNOWN = "create_unknown"        # may or may not exist; replay later
CANCEL_RETRYABLE = "cancel_retryable"    # replacement live, cancel may be retried
CANCEL_UNKNOWN = "cancel_unknown"        # replacement live, cancel outcome unknown
SOURCE_CHANGED = "source_changed"        # replacement live, NEVER auto-cancel
FENCED = "fenced"                        # we are not the owner; we did nothing
INCIDENT = "incident"                    # contradictory truth; operator required

# migration 022's cancel_failure_reason CHECK values.
REASON_RETRYABLE = "provider_retryable"
REASON_UNKNOWN = "provider_unknown"
REASON_SOURCE_CHANGED = "source_changed"

_CANCELLED_STATUSES = ("CANCELLED", "DECLINED")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _instant(value) -> datetime | None:
    """Parse a timestamp to an instant. Returns None if it is not one.

    Comparison is on the INSTANT, never on the string: '...Z' and '...+00:00' are
    the same moment, and a raw string compare would report a merchant edit that
    never happened — which under §9 means refusing to cancel forever.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def booking_note(operation: dict) -> str:
    """The customer_note, derived ONLY from the frozen target service name.

    Pure function of one frozen column, so every replay produces the same bytes.
    """
    base = "Rescheduled via Open Lines AI receptionist"
    name = (operation.get("target_service_name") or "").strip()
    return f"{base} — {name}" if name else base


def create_booking_kwargs(operation: dict) -> dict:
    """The CreateBooking arguments, entirely from frozen operation columns.

    Every value here is a column of appointment_reschedule_operations. Nothing is
    resolved, matched, looked up or defaulted from live state — that is the
    property that makes provider_idempotency_key meaningful, and it is asserted
    structurally by the D2 tests rather than trusted.
    """
    return {
        "location_id": operation["target_provider_location_id"],
        "start_at_iso": str(operation["target_start_at_utc"]),
        "customer_id": operation["target_provider_customer_id"],
        "team_member_id": operation["target_team_member_id"],
        "service_variation_id": operation["target_service_variation_id"],
        "service_variation_version": operation.get("target_service_variation_version"),
        "duration_minutes": operation.get("target_duration_minutes"),
        "note": booking_note(operation),
        "idempotency_key": operation["provider_idempotency_key"],
    }


# ---------------------------------------------------------------------------
# §2 — the absolute provider-create gate
# ---------------------------------------------------------------------------

async def _gate(operation_id: str, claim_token: str) -> tuple[dict, dict, dict] | None:
    """Re-prove ownership from the database. Returns (operation, claim, source).

    None means we are not the owner and MUST NOT touch the provider. Every part
    is re-read here rather than trusted from the caller's dict: this runs
    immediately before a destructive HTTP call, and the whole point is that a
    takeover may have happened since the caller last looked.

    The claim and the operation must BOTH name our token. One alone is not
    enough — a worker that took the claim but died before adopting the operation
    leaves them disagreeing, and acting on either half would be acting without
    an election.
    """
    operation = await db_ops.get_operation(operation_id)
    if not operation:
        logger.warning("reschedule_execute: operation %s no longer exists", operation_id)
        return None

    source_id = str(operation["source_appointment_id"])
    claim = await db_mc.get_claim(source_id)
    if not claim:
        logger.warning("reschedule_execute: no claim holds appointment %s (operation %s)",
                       source_id, operation_id)
        return None
    if claim.get("operation_type") != db_mc.OP_RESCHEDULE:
        logger.warning("reschedule_execute: appointment %s is owned by a %s, not a reschedule",
                       source_id, claim.get("operation_type"))
        return None
    if str(claim.get("operation_id") or "") != str(operation_id):
        logger.warning("reschedule_execute: claim on %s names operation %s, not %s",
                       source_id, claim.get("operation_id"), operation_id)
        return None
    if str(claim.get("appointment_id")) != source_id:
        return None
    if str(claim.get("claim_token")) != str(claim_token) \
            or str(operation.get("claim_token")) != str(claim_token):
        logger.info("reschedule_execute: fenced on operation %s — the claim moved", operation_id)
        return None

    source = await db.get_appointment_by_id(source_id)
    if not source:
        logger.warning("reschedule_execute: source appointment %s is gone", source_id)
        return None
    if str(source.get("tenant_id")) != str(operation["tenant_id"]):
        logger.error("reschedule_execute: INTEGRITY — appointment %s belongs to tenant %s, "
                     "operation %s to %s", source_id, source.get("tenant_id"),
                     operation_id, operation["tenant_id"])
        return None

    return operation, claim, source


# ---------------------------------------------------------------------------
# §3–§8 — replacement creation and adoption
# ---------------------------------------------------------------------------

async def _adopt_or_insert_replacement(operation: dict, source: dict,
                                       booking: dict, *, vapi_call_id: str) -> tuple[str, dict]:
    """Make exactly one local replacement row exist for this source.

    Returns (outcome, replacement). Idempotent by construction: migration 018's
    partial unique index on rescheduled_from_appointment_id means the database,
    not this function's timing, decides that there is only ever one.
    """
    source_id = str(source["id"])
    booking_id = str(booking.get("id") or "")
    if not booking_id:
        logger.error("reschedule_execute: CONSISTENCY INCIDENT — Square returned a booking "
                     "with no id for operation %s", operation["id"])
        return INCIDENT, {}

    existing = await db.get_appointment_by_rescheduled_from(source_id)
    if existing:
        if str(existing.get("google_event_id") or "") != booking_id:
            # Two different provider bookings claim the same lineage. Overwriting
            # either identity would hide a real double booking from the merchant.
            logger.error("reschedule_execute: CONSISTENCY INCIDENT — replacement %s for source "
                         "%s holds booking %s but the provider returned %s. Not overwriting.",
                         existing.get("id"), source_id,
                         existing.get("google_event_id"), booking_id)
            return INCIDENT, existing
        return COMPLETED, existing

    status = (source.get("status") or "")
    row = {
        "tenant_id": operation["tenant_id"],
        # EXACTLY the source's phone. retention.delete_caller_data issues one
        # set-based DELETE keyed on caller_phone; a replacement carrying a
        # different one would make the source undeletable (23503) and break
        # PIPEDA erasure for that caller.
        "caller_phone": source.get("caller_phone"),
        "caller_name": source.get("caller_name"),
        "service": operation.get("target_service_name") or source.get("service") or "Appointment",
        "appointment_datetime": str(operation["target_start_at_utc"]),
        "duration_minutes": operation.get("target_duration_minutes")
                            or source.get("duration_minutes") or 60,
        # A deposit-pending source stays deposit-pending: silently promoting it to
        # confirmed would tell the merchant money had arrived.
        "status": status if status in ("confirmed", "pending_payment") else "confirmed",
        # Recovery has no call. Provider-insignificant, and the row is inserted
        # exactly once either way, so this cannot affect replay convergence.
        "vapi_call_id": vapi_call_id or source.get("vapi_call_id"),
        "google_event_id": booking_id,
        "tenant_location_id": operation.get("target_tenant_location_id"),
        "provider_location_id": operation["target_provider_location_id"],
        "rescheduled_from_appointment_id": source_id,
    }
    try:
        created = await db.insert_appointment(row)
    except Exception as e:
        if db_ops.is_unique_violation(e):
            # Another worker inserted the lineage between our read and our write.
            # The index did its job; adopt whatever it let through.
            existing = await db.get_appointment_by_rescheduled_from(source_id)
            if existing and str(existing.get("google_event_id") or "") == booking_id:
                return COMPLETED, existing
            logger.error("reschedule_execute: CONSISTENCY INCIDENT — lineage for source %s "
                         "was taken by booking %s, not %s", source_id,
                         (existing or {}).get("google_event_id"), booking_id)
            return INCIDENT, existing or {}
        logger.error("reschedule_execute: replacement insert failed for operation %s: %s",
                     operation["id"], e)
        raise
    if not created:
        raise RuntimeError("replacement insert returned no row")
    return COMPLETED, created


async def _create_phase(operation: dict, source: dict, token: str, claim_token: str, *,
                        vapi_call_id: str, slot_ref: str) -> str:
    """in_progress -> replacement_created, or a terminal create failure."""
    operation_id = str(operation["id"])
    source_id = str(source["id"])

    # §6 — a replacement lineage that already exists is the answer. Asking Square
    # for another booking when the database can already prove one exists is how a
    # caller ends up with two.
    existing = await db.get_appointment_by_rescheduled_from(source_id)
    if existing:
        logger.info("reschedule_execute: adopting existing replacement %s for operation %s",
                    existing.get("id"), operation_id)
        booking_id = str(existing.get("google_event_id") or "")
        return await _finish_create(operation, claim_token, existing, booking_id,
                                    vapi_call_id=vapi_call_id, slot_ref=slot_ref)

    kwargs = create_booking_kwargs(operation)
    try:
        booking = await square_booking.create_booking(token, **kwargs)
    except square_booking.BookingOutcomeUnknown as e:
        # The request may have been committed. Everything stays exactly as it is:
        # the state remains in_progress, the slot stays claimed, ownership is
        # held, and no new key is ever generated. Recovery replays these same
        # bytes with this same key, which Square answers with the original
        # booking if one was made.
        logger.error("reschedule_execute: CreateBooking outcome UNKNOWN for operation %s "
                     "(replay will use the frozen key): %s", operation_id, e)
        return CREATE_UNKNOWN
    except Exception as e:
        # Definitive rejection. Square created nothing, so the source is untouched
        # and the caller keeps the appointment they already had.
        logger.error("reschedule_execute: CreateBooking definitively failed for operation "
                     "%s: %s", operation_id, e)
        if not await db_ops.mark_create_failed(operation_id, claim_token):
            return FENCED
        if vapi_call_id and slot_ref:
            await slot_offers.release(vapi_call_id, slot_ref)
        await _release_claim(source_id, claim_token)
        return CREATE_FAILED

    outcome, replacement = await _adopt_or_insert_replacement(
        operation, source, booking, vapi_call_id=vapi_call_id)
    if outcome != COMPLETED:
        return outcome
    return await _finish_create(operation, claim_token, replacement,
                                str(booking.get("id") or ""),
                                vapi_call_id=vapi_call_id, slot_ref=slot_ref)


async def _finish_create(operation: dict, claim_token: str, replacement: dict,
                         booking_id: str, *, vapi_call_id: str, slot_ref: str) -> str:
    """§7 + §8 — consume the slot for good, then advance the operation."""
    if vapi_call_id and slot_ref and booking_id:
        # PERMANENT. The replacement exists, so this time is genuinely taken. It
        # is never released again, not even if cancelling the source fails —
        # handing the slot back would offer a time we have already booked.
        await slot_offers.mark_consumed(vapi_call_id, slot_ref, booking_id)

    if not await db_ops.mark_replacement_created(
            str(operation["id"]), claim_token, str(replacement["id"])):
        # Either a takeover moved the row, or it is already past in_progress.
        # Both mean somebody else is advancing it; we stop rather than guess.
        logger.info("reschedule_execute: replacement_created transition fenced for %s",
                    operation["id"])
        return FENCED
    return COMPLETED


# ---------------------------------------------------------------------------
# §9–§12 — source fingerprint, cancellation, completion
# ---------------------------------------------------------------------------

def fingerprint_matches(operation: dict, booking: dict, source: dict) -> tuple[bool, str]:
    """Is this still the booking D1 validated? Returns (ok, what_differs).

    version carries the whole comparison that D1 could not otherwise make. Square
    increments it on ANY mutation of the booking — time, service variation, team
    member, notes — so a matching version proves the appointment segments are the
    ones D1 saw, without D1 having had to freeze them field by field. start_at and
    location are compared as well because they are the two changes a merchant is
    most likely to make and the two whose consequences are worst.
    """
    booking_id = str(booking.get("id") or "")
    if booking_id != str(operation.get("source_provider_booking_id") or ""):
        return False, f"booking id {booking_id!r}"

    frozen_version = operation.get("source_booking_version")
    if frozen_version is not None and booking.get("version") is not None:
        if int(booking["version"]) != int(frozen_version):
            return False, (f"version {booking['version']} != frozen {frozen_version}")

    frozen_start = _instant(operation.get("source_start_at_utc"))
    live_start = _instant(booking.get("start_at"))
    if frozen_start and live_start and frozen_start != live_start:
        return False, f"start_at {live_start.isoformat()} != frozen {frozen_start.isoformat()}"

    expected_location = str(source.get("provider_location_id") or "")
    live_location = str(booking.get("location_id") or "")
    if expected_location and live_location and live_location != expected_location:
        return False, f"location {live_location!r} != {expected_location!r}"

    return True, ""


async def _cancel_phase(operation: dict, source: dict, token: str, claim_token: str, *,
                        vapi_call_id: str, appointment_ref: str) -> str:
    """replacement_created / cancel_failed -> completed, or a held failure."""
    operation_id = str(operation["id"])
    source_id = str(source["id"])
    booking_id = str(operation.get("source_provider_booking_id") or "")

    fetch_status, booking = await square_booking.get_booking_detailed(token, booking_id)

    if fetch_status == square_booking.FETCH_UNKNOWN:
        # We could not READ the source, which is not the same as having tried to
        # cancel it and not knowing. Nothing was mutated, so this is retryable.
        await db_ops.mark_cancel_failed(operation_id, claim_token, REASON_RETRYABLE)
        return CANCEL_RETRYABLE

    if fetch_status == square_booking.FETCH_NOT_FOUND:
        return await _complete(operation, claim_token, source_id,
                               vapi_call_id=vapi_call_id, appointment_ref=appointment_ref,
                               note="provider reports the source absent")

    status = (booking.get("status") or "").upper()
    if any(s in status for s in _CANCELLED_STATUSES):
        return await _complete(operation, claim_token, source_id,
                               vapi_call_id=vapi_call_id, appointment_ref=appointment_ref,
                               note=f"source already {status}")

    ok, differs = fingerprint_matches(operation, booking, source)
    if not ok:
        logger.error("reschedule_execute: SOURCE CHANGED — refusing to cancel booking %s for "
                     "operation %s (%s). Replacement remains; operator review required.",
                     booking_id, operation_id, differs)
        await db_ops.mark_cancel_failed(operation_id, claim_token, REASON_SOURCE_CHANGED)
        return SOURCE_CHANGED

    # Revalidate ownership immediately before the destructive call: everything
    # above this line was HTTP, and a takeover can have happened during it.
    if not await _still_ours(operation_id, claim_token):
        return FENCED

    cancel_status, _cancelled, error_code = await square_booking.cancel_booking_detailed(
        token, booking_id)

    if cancel_status in (square_booking.CANCEL_OK, square_booking.CANCEL_ALREADY,
                         square_booking.CANCEL_NOT_FOUND):
        return await _complete(operation, claim_token, source_id,
                               vapi_call_id=vapi_call_id, appointment_ref=appointment_ref,
                               note=cancel_status)

    if cancel_status == square_booking.CANCEL_UNKNOWN:
        # It may have landed. Ownership is held and recovery re-reads provider
        # truth before deciding anything at all.
        logger.error("reschedule_execute: source cancellation outcome UNKNOWN for operation "
                     "%s — ownership held", operation_id)
        await db_ops.mark_cancel_failed(operation_id, claim_token, REASON_UNKNOWN)
        return CANCEL_UNKNOWN

    if error_code == square_booking.ERR_VERSION_MISMATCH:
        # The booking moved between our fingerprint read and this call. Refetching
        # the new version and cancelling it is exactly what must not happen: that
        # version is the merchant's edit, not the appointment D1 validated.
        logger.error("reschedule_execute: VERSION_MISMATCH cancelling %s for operation %s — "
                     "treating as a merchant edit, not retrying", booking_id, operation_id)
        await db_ops.mark_cancel_failed(operation_id, claim_token, REASON_SOURCE_CHANGED)
        return SOURCE_CHANGED

    logger.error("reschedule_execute: source cancellation refused for operation %s (%s/%s)",
                 operation_id, cancel_status, error_code or "no code")
    await db_ops.mark_cancel_failed(operation_id, claim_token, REASON_RETRYABLE)
    return CANCEL_RETRYABLE


async def _complete(operation: dict, claim_token: str, source_id: str, *,
                    vapi_call_id: str, appointment_ref: str, note: str) -> str:
    """§12 — local source cancelled, then operation completed, then ownership."""
    try:
        await db.update_appointment(source_id, {"status": "cancelled"})
    except Exception as e:
        # The provider is done and our record is not. Ownership is HELD so
        # recovery reconciles the two rather than leaving a live local row
        # pointing at a cancelled booking.
        logger.error("reschedule_execute: source %s cancelled at the provider but the local "
                     "write failed (%s) — held for reconciliation", source_id, e)
        await db_ops.mark_cancel_failed(str(operation["id"]), claim_token, REASON_UNKNOWN)
        return CANCEL_UNKNOWN

    if not await db_ops.mark_completed(str(operation["id"]), claim_token):
        logger.info("reschedule_execute: completion transition fenced for %s", operation["id"])
        return FENCED

    await _release_claim(source_id, claim_token)
    if vapi_call_id and appointment_ref:
        # The selection capability has now been spent. Best effort: ownership,
        # not this row, is what prevented a second mutation.
        try:
            await db_ar.consume_ref(vapi_call_id, appointment_ref)
        except Exception as e:
            logger.warning("reschedule_execute: could not consume appointment_ref %s: %s",
                           appointment_ref, e)
    logger.info("reschedule_execute: operation %s completed (%s)", operation["id"], note)
    return COMPLETED


async def _still_ours(operation_id: str, claim_token: str) -> bool:
    gated = await _gate(operation_id, claim_token)
    return gated is not None


async def _release_claim(appointment_id: str, claim_token: str) -> None:
    """Release only our own claim, fenced on the token AND its timestamp."""
    claim = await db_mc.get_claim(appointment_id)
    if not claim or str(claim.get("claim_token")) != str(claim_token):
        logger.info("reschedule_execute: claim on %s is no longer ours — not releasing",
                    appointment_id)
        return
    await db_mc.release_claim(appointment_id, claim["claim_token"], claim["claimed_at"])


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

async def run_operation(operation_id: str, claim_token: str, *, vapi_call_id: str = "",
                        slot_ref: str = "", appointment_ref: str = "") -> str:
    """Advance one reschedule operation as far as provider truth allows.

    The same entry point serves the live request and the recovery worker; they
    differ only in whether call-scoped context exists. Nothing about correctness
    depends on it — call_slot_offers and call_appointment_refs are deleted at end
    of call, so recovery must and does work without them.
    """
    gated = await _gate(operation_id, claim_token)
    if gated is None:
        return FENCED
    operation, _claim, source = gated

    tenant = await db.get_tenant_by_id(str(operation["tenant_id"])) or {}
    token = await square_booking.get_access_token(tenant)
    if not token:
        logger.error("reschedule_execute: no provider credential for tenant %s",
                     operation["tenant_id"])
        return CANCEL_RETRYABLE if operation["state"] != db_ops.STATE_IN_PROGRESS \
            else CREATE_UNKNOWN

    state = operation["state"]

    if state == db_ops.STATE_IN_PROGRESS:
        outcome = await _create_phase(operation, source, token, claim_token,
                                      vapi_call_id=vapi_call_id, slot_ref=slot_ref)
        if outcome != COMPLETED:
            return outcome
        # Re-read: the create phase advanced the row, and the cancel phase must
        # act on the state the database now holds, not the one we arrived with.
        gated = await _gate(operation_id, claim_token)
        if gated is None:
            return FENCED
        operation, _claim, source = gated
        state = operation["state"]

    if state == db_ops.STATE_CANCEL_FAILED \
            and operation.get("cancel_failure_reason") == REASON_SOURCE_CHANGED:
        # §13 — no automatic provider mutation, in any pass, ever. Ownership stays
        # held and the incident stays visible.
        logger.error("reschedule_execute: operation %s is parked on source_changed — "
                     "operator resolution required", operation_id)
        return SOURCE_CHANGED

    if state in (db_ops.STATE_REPLACEMENT_CREATED, db_ops.STATE_CANCEL_FAILED):
        return await _cancel_phase(operation, source, token, claim_token,
                                   vapi_call_id=vapi_call_id,
                                   appointment_ref=appointment_ref)

    logger.info("reschedule_execute: operation %s is in terminal state %s — nothing to do",
                operation_id, state)
    return COMPLETED if state == db_ops.STATE_COMPLETED else CREATE_FAILED


# ---------------------------------------------------------------------------
# §13 — the recovery worker
# ---------------------------------------------------------------------------

async def run_reschedule_recovery(limit: int = 10) -> dict:
    """Advance abandoned reschedule operations, and release claims they no longer need.

    Driven from the CLAIMS side rather than the operations side because that is
    the complete set: D1 acquires the claim BEFORE inserting the operation and
    every D1 failure path releases it without leaving an operation behind, so a
    live operation always has a claim, while a claim can outlive its operation's
    usefulness. Scanning operations alone would miss §12's crash C — an operation
    that completed before its claim could be released, which leaves the
    appointment globally locked and is invisible to a LIVE_STATES query.
    """
    try:
        claims = await db_mc.list_stale_reschedule_claims(limit=limit)
    except Exception as e:
        logger.error("reschedule_execute: recovery scan failed: %s", e)
        return {"scanned": 0, "error": str(e)[:200]}

    outcomes: dict[str, int] = {}

    def _tally(key: str) -> None:
        outcomes[key] = outcomes.get(key, 0) + 1

    for claim in claims:
        operation_id = claim.get("operation_id")
        if not operation_id:
            _tally("no_operation_id")
            continue
        try:
            operation = await db_ops.get_operation(str(operation_id))
        except Exception as e:
            logger.error("reschedule_execute: could not read operation %s: %s", operation_id, e)
            _tally("read_failed")
            continue

        if not operation:
            # D1's orphan cleanup owns this case, and only it can prove the claim
            # is safe to drop (no operation row => no provider call was possible).
            _tally("orphan_left_to_d1")
            continue

        if operation["state"] not in db_ops.LIVE_STATES:
            # §12 crash C: the work is finished and only the lock outlived it.
            released = await db_mc.release_claim(
                claim["appointment_id"], claim["claim_token"], claim["claimed_at"])
            _tally("terminal_claim_released" if released else "terminal_claim_fenced")
            continue

        if operation.get("cancel_failure_reason") == REASON_SOURCE_CHANGED:
            # Deliberately not taken over and not advanced. Taking it over would
            # only refresh the claim's timestamp and hide the incident from the
            # next scan.
            logger.error("reschedule_execute: operation %s awaits operator resolution "
                         "(source_changed) on appointment %s",
                         operation_id, claim["appointment_id"])
            _tally("awaiting_operator")
            continue

        new_token = str(uuid.uuid4())
        if not await db_mc.takeover_stale_reschedule(
                claim["appointment_id"], str(operation_id),
                claim["claim_token"], claim["claimed_at"], new_token):
            _tally("takeover_lost")
            continue
        if not await db_ops.adopt_claim_token(
                str(operation_id), operation["claim_token"], new_token):
            # We hold the claim but could not point the operation at it. Both
            # halves must agree before anything touches Square, so we stop; the
            # next scan re-reads the operation's current token and converges.
            logger.warning("reschedule_execute: took the claim on %s but could not adopt "
                           "operation %s", claim["appointment_id"], operation_id)
            _tally("adopt_lost")
            continue

        try:
            outcome = await run_operation(str(operation_id), new_token)
        except Exception as e:
            logger.error("reschedule_execute: recovery of operation %s failed: %s",
                         operation_id, e)
            _tally("error")
            continue
        _tally(outcome)

    return {"scanned": len(claims), "outcomes": outcomes}
