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
