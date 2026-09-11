"""
Data-access for durable reschedule operations (migrations 020 + 022).

The row is the frozen truth a replay works from: once it exists, no part of the
booking it describes may be re-derived from a live catalog, a live slot offer or
a live customer lookup. So this module only writes it whole, and reads it back.
"""
from __future__ import annotations

import logging

from db.supabase import get_client

logger = logging.getLogger(__name__)

STATE_IN_PROGRESS = "in_progress"
STATE_CREATE_FAILED = "create_failed"
STATE_REPLACEMENT_CREATED = "replacement_created"
STATE_CANCEL_FAILED = "cancel_failed"
STATE_COMPLETED = "completed"

# Migration 022's partial unique index covers exactly these: the states that
# still own the source or have already mutated the provider.
LIVE_STATES = (STATE_IN_PROGRESS, STATE_REPLACEMENT_CREATED, STATE_CANCEL_FAILED)


def is_unique_violation(e: Exception) -> bool:
    s = str(e).lower()
    return "23505" in s or "duplicate" in s or "unique" in s


async def insert_operation(row: dict) -> dict | None:
    """Persist the frozen operation. None on a live-operation unique conflict."""
    try:
        res = get_client().table("appointment_reschedule_operations").insert(row).execute()
        return (res.data or [None])[0]
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


async def get_operation(operation_id: str) -> dict | None:
    res = (get_client().table("appointment_reschedule_operations").select("*")
           .eq("id", operation_id).limit(1).execute())
    return (res.data or [None])[0]


async def get_live_operation_for_source(source_appointment_id: str) -> dict | None:
    """The one LIVE operation for this source, if any.

    create_failed and completed rows are deliberately excluded: they are history,
    and a later attempt is allowed to start a genuinely new operation.
    """
    res = (get_client().table("appointment_reschedule_operations").select("*")
           .eq("source_appointment_id", source_appointment_id)
           .in_("state", list(LIVE_STATES)).limit(1).execute())
    return (res.data or [None])[0]


async def delete_operation(operation_id: str) -> None:
    """Test/rollback use only. No production path deletes an operation."""
    get_client().table("appointment_reschedule_operations").delete().eq("id", operation_id).execute()


# ---------------------------------------------------------------------------
# W6A2-D2 — fenced state transitions.
#
# Every transition names the state it expects to leave AND the claim token it
# believes it holds. Both are in the predicate for the same reason: a worker
# whose claim was taken over must not be able to move an operation the new owner
# is already advancing, and state alone cannot tell "still mine" from "someone
# else put it back here". `len(res.data) == 1` is the proof we won.
#
# claimed_at is refreshed on every transition so a worker that is visibly making
# progress is not re-scanned as abandoned by the recovery sweep.
# ---------------------------------------------------------------------------

async def _transition(operation_id: str, claim_token: str, from_states: tuple,
                      patch: dict) -> bool:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = (get_client().table("appointment_reschedule_operations")
           .update({**patch, "claimed_at": now, "updated_at": now})
           .eq("id", operation_id)
           .eq("claim_token", claim_token)
           .in_("state", list(from_states)).execute())
    return len(res.data or []) == 1


async def mark_create_failed(operation_id: str, claim_token: str) -> bool:
    """in_progress -> create_failed. Square definitively created nothing.

    Terminal, and deliberately outside migration 022's live-source uniqueness:
    the source was never touched, so the caller may start a genuinely new
    reschedule later.
    """
    return await _transition(operation_id, claim_token, (STATE_IN_PROGRESS,),
                             {"state": STATE_CREATE_FAILED})


async def mark_replacement_created(operation_id: str, claim_token: str,
                                   replacement_appointment_id: str) -> bool:
    """in_progress -> replacement_created. The provider booking and its local row
    both exist. From here CreateBooking must never run again for this operation."""
    return await _transition(operation_id, claim_token, (STATE_IN_PROGRESS,),
                             {"state": STATE_REPLACEMENT_CREATED,
                              "replacement_appointment_id": replacement_appointment_id})


async def mark_cancel_failed(operation_id: str, claim_token: str, reason: str) -> bool:
    """-> cancel_failed with the discriminator migration 022 added.

    cancel_failed is re-enterable: a retryable attempt that fails again, or one
    that discovers the merchant has since edited the booking, must be able to
    change the REASON without leaving the state.
    """
    return await _transition(
        operation_id, claim_token,
        (STATE_REPLACEMENT_CREATED, STATE_CANCEL_FAILED),
        {"state": STATE_CANCEL_FAILED, "cancel_failure_reason": reason})


async def mark_completed(operation_id: str, claim_token: str) -> bool:
    """-> completed. The source is cancelled at the provider and locally."""
    return await _transition(
        operation_id, claim_token,
        (STATE_REPLACEMENT_CREATED, STATE_CANCEL_FAILED),
        {"state": STATE_COMPLETED})


async def adopt_claim_token(operation_id: str, prev_token: str, new_token: str) -> bool:
    """Point the operation at the token of the worker that just took its claim.

    Fenced on the token the operation CURRENTLY carries, not on the token the
    claim carried: those differ whenever a previous recovery worker died between
    taking the claim and adopting the operation, and fencing on the claim's old
    value would strand the row permanently.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = (get_client().table("appointment_reschedule_operations")
           .update({"claim_token": new_token, "claimed_at": now, "updated_at": now})
           .eq("id", operation_id).eq("claim_token", prev_token).execute())
    return len(res.data or []) == 1


async def list_recoverable_operations(stale_before_iso: str, limit: int = 20) -> list:
    """Operations with outstanding provider work whose worker has gone quiet.

    Served by appointment_reschedule_ops_unfinished_idx, whose predicate is
    exactly LIVE_STATES. claimed_at is the liveness signal: it moves on every
    transition, so an operation being actively advanced is never picked up here.
    """
    res = (get_client().table("appointment_reschedule_operations").select("*")
           .in_("state", list(LIVE_STATES))
           .lt("claimed_at", stale_before_iso)
           .order("claimed_at", desc=False).limit(limit).execute())
    return res.data or []


async def list_live_operations_for_target(tenant_id: str, provider_location_id: str,
                                          target_start_at: str) -> list:
    """Live operations whose FROZEN TARGET is exactly this booking.

    W7D asks this before mirroring an unrecognised Square booking. D2 creates the
    replacement at the provider BEFORE it persists the local row, so a
    booking.created webhook can arrive in that gap; mirroring it then would leave
    two local appointments for one provider booking, and migration 018's lineage
    index would not catch it because a mirror carries no rescheduled_from.

    Matched on the frozen target rather than on a provider booking id because the
    operation row does not store the replacement's booking id -- only the payload
    that produced it.
    """
    if not (tenant_id and provider_location_id and target_start_at):
        return []
    res = (get_client().table("appointment_reschedule_operations").select("*")
           .eq("tenant_id", tenant_id)
           .eq("target_provider_location_id", provider_location_id)
           .eq("target_start_at_utc", target_start_at)
           .in_("state", list(LIVE_STATES)).execute())
    return res.data or []
