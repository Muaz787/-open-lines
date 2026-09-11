"""
Data-access for global appointment mutation ownership (migration 021).

Every mutator is a compare-and-swap fenced on appointment_id AND claim_token AND
claimed_at. That is not defensive habit: a stale worker whose claim was taken
over must not be able to release, transition, or otherwise disturb the new
owner's row, and token alone cannot distinguish "still mine" from a coincidence.

There is deliberately no unconditional release and no cross-type transition. A
cancellation may never take a reschedule's claim and vice versa — a caller that
meets a held claim refuses, and only a type-matched recovery worker may take over
an abandoned one.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)

OP_CANCEL = "cancel"
OP_RESCHEDULE = "reschedule"
OP_CANCEL_RECONCILE = "cancel_reconcile"

REASON_PROVIDER_UNKNOWN = "provider_outcome_unknown"
REASON_LOCAL_WRITE_FAILED = "local_write_failed"

# How long a cancel_reconcile claim may sit before recovery may take it over.
# Long enough that a live worker is never stolen from, short enough that a
# crashed one does not strand an appointment for a whole conversation.
RECONCILE_STALE_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def stale_cutoff_iso(seconds: int = RECONCILE_STALE_SECONDS) -> str:
    return (_now() - timedelta(seconds=seconds)).isoformat()


def is_unique_violation(e: Exception) -> bool:
    s = str(e).lower()
    return "23505" in s or "duplicate" in s or "unique" in s


async def get_claim(appointment_id: str) -> dict | None:
    res = (get_client().table("appointment_mutation_claims").select("*")
           .eq("appointment_id", appointment_id).limit(1).execute())
    return (res.data or [None])[0]


async def acquire_cancel_claim(appointment_id: str, tenant_id: str,
                               claim_token: str) -> dict | None:
    """Take global ownership for a cancellation. None means somebody else owns it.

    The insert IS the election — appointment_id is the primary key, so exactly one
    workflow can hold an appointment at a time regardless of which call, which
    ref, or which caller phone it came from.
    """
    try:
        res = get_client().table("appointment_mutation_claims").insert({
            "appointment_id": appointment_id,
            "tenant_id": tenant_id,
            "operation_type": OP_CANCEL,
            "claim_token": claim_token,
            "claimed_at": _now_iso(),
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


async def acquire_reschedule_claim(appointment_id: str, tenant_id: str,
                                   operation_id: str, claim_token: str) -> dict | None:
    """Take global ownership for a reschedule. None means somebody else owns it.

    operation_id is supplied by the caller and written at acquisition, never
    patched in afterwards. That removes the ambiguous window in which a claim says
    "a reschedule owns this" without saying which one — and it is what makes the
    orphan rule decidable: a claim naming an operation row that does not exist
    proves no provider mutation occurred, because nothing may call Square until
    that row is persisted.
    """
    try:
        res = get_client().table("appointment_mutation_claims").insert({
            "appointment_id": appointment_id,
            "tenant_id": tenant_id,
            "operation_type": OP_RESCHEDULE,
            "operation_id": operation_id,
            "claim_token": claim_token,
            "claimed_at": _now_iso(),
        }).execute()
        return (res.data or [None])[0]
    except Exception as e:
        if is_unique_violation(e):
            return None
        raise


async def list_stale_reschedule_claims(limit: int = 20) -> list:
    """Reschedule claims old enough to be inspected for orphanhood."""
    res = (get_client().table("appointment_mutation_claims").select("*")
           .eq("operation_type", OP_RESCHEDULE)
           .lt("claimed_at", stale_cutoff_iso())
           .order("claimed_at", desc=False).limit(limit).execute())
    return res.data or []


async def release_orphan_reschedule_claim(
    appointment_id: str, operation_id: str, claim_token: str, claimed_at: str,
) -> bool:
    """Delete a reschedule claim whose operation row never landed.

    Fenced on operation_id as well as token and timestamp, so a claim that has
    since been re-acquired for a DIFFERENT operation cannot be removed by a
    worker still holding the old one's identifiers.
    """
    res = (get_client().table("appointment_mutation_claims").delete()
           .eq("appointment_id", appointment_id)
           .eq("operation_type", OP_RESCHEDULE)
           .eq("operation_id", operation_id)
           .eq("claim_token", claim_token).eq("claimed_at", claimed_at)
           .lt("claimed_at", stale_cutoff_iso()).execute())
    return len(res.data or []) == 1


async def transition_cancel_to_reconcile(
    appointment_id: str, claim_token: str, claimed_at: str, reason: str,
) -> bool:
    """cancel -> cancel_reconcile, owner only. True if we made the transition.

    Ownership is deliberately RETAINED across this transition: provider truth is
    unresolved, and releasing here would let another workflow mutate an
    appointment whose real state nobody knows.
    """
    res = (get_client().table("appointment_mutation_claims")
           .update({"operation_type": OP_CANCEL_RECONCILE,
                    "reconcile_reason": reason,
                    "updated_at": _now_iso()})
           .eq("appointment_id", appointment_id)
           .eq("operation_type", OP_CANCEL)
           .eq("claim_token", claim_token).eq("claimed_at", claimed_at).execute())
    return len(res.data or []) == 1


async def transition_reconcile_to_cancel(
    appointment_id: str, claim_token: str, claimed_at: str, new_token: str,
) -> bool:
    """cancel_reconcile -> cancel, for a recovery worker that has proven the
    booking is still ACTIVE and may legitimately retry the cancellation.

    Same row, same appointment, same operation family — this is a type-matched
    transition by the current owner, not a cross-type steal.
    """
    res = (get_client().table("appointment_mutation_claims")
           .update({"operation_type": OP_CANCEL, "reconcile_reason": None,
                    "claim_token": new_token, "claimed_at": _now_iso(),
                    "updated_at": _now_iso()})
           .eq("appointment_id", appointment_id)
           .eq("operation_type", OP_CANCEL_RECONCILE)
           .eq("claim_token", claim_token).eq("claimed_at", claimed_at).execute())
    return len(res.data or []) == 1


async def takeover_stale_reconcile(
    appointment_id: str, prev_token: str, prev_claimed_at: str, new_token: str,
) -> bool:
    """Take over an abandoned cancel_reconcile claim — reconciliation only.

    operation_type is in the predicate and is NOT changed, so this cannot become
    a route by which one operation type acquires another's appointment. Both the
    previous token and timestamp are required, so a row that moved since we read
    it is not ours to take.
    """
    res = (get_client().table("appointment_mutation_claims")
           .update({"claim_token": new_token, "claimed_at": _now_iso(),
                    "updated_at": _now_iso()})
           .eq("appointment_id", appointment_id)
           .eq("operation_type", OP_CANCEL_RECONCILE)
           .eq("claim_token", prev_token).eq("claimed_at", prev_claimed_at)
           .lt("claimed_at", stale_cutoff_iso()).execute())
    return len(res.data or []) == 1


async def release_claim(appointment_id: str, claim_token: str, claimed_at: str) -> bool:
    """Give up ownership. Never by appointment_id alone."""
    res = (get_client().table("appointment_mutation_claims").delete()
           .eq("appointment_id", appointment_id)
           .eq("claim_token", claim_token).eq("claimed_at", claimed_at).execute())
    return len(res.data or []) == 1


async def list_stale_reconcile_claims(limit: int = 20) -> list:
    """cancel_reconcile claims old enough to be recovered."""
    res = (get_client().table("appointment_mutation_claims").select("*")
           .eq("operation_type", OP_CANCEL_RECONCILE)
           .lt("claimed_at", stale_cutoff_iso())
           .order("claimed_at", desc=False).limit(limit).execute())
    return res.data or []
