from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime

from db import supabase as db
from services import date_ranges
from services.security import require_tenant_owner

# Every route here exposes tenant call data / transcripts — require ownership.
router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[Depends(require_tenant_owner)])


async def _zone_and_since(tenant_id: str, days: int):
    """The tenant's timezone and the start of a `days` period. days <= 0 means all
    calls. Uses the same window as the overview's stats."""
    tz = date_ranges.tenant_zone(await db.get_tenant_by_id(tenant_id))
    return tz, (date_ranges.period_start(days, tz) if days > 0 else None)


@router.get("/{tenant_id}/analytics")
async def get_analytics(tenant_id: str, days: int = 30):
    tz, since = await _zone_and_since(tenant_id, days)
    calls = await db.get_calls_with_leads(tenant_id, since=since, limit=1000)
    total = len(calls)
    total_secs = sum(c.get("duration_secs") or 0 for c in calls)
    avg_duration = round(total_secs / total) if total else 0

    urgency_counts: dict = {"hot": 0, "warm": 0, "cold": 0, "unknown": 0}
    calls_by_day: dict = {}
    for c in calls:
        lead = c.get("leads") or {}
        u = (lead.get("urgency") or "unknown").lower()
        urgency_counts[u if u in urgency_counts else "unknown"] += 1
        created = c.get("created_at")
        if created:
            day = date_ranges.local_day(datetime.fromisoformat(str(created).replace("Z", "+00:00")), tz)
            calls_by_day[day] = calls_by_day.get(day, 0) + 1

    return {
        "total_calls": total,
        "avg_duration_secs": avg_duration,
        "urgency_breakdown": urgency_counts,
        "calls_by_day": calls_by_day,
    }


@router.get("/{tenant_id}")
async def list_calls(tenant_id: str, days: int = 30):
    _, since = await _zone_and_since(tenant_id, days)
    return await db.get_calls_with_leads(tenant_id, since=since)


@router.get("/{tenant_id}/{call_id}")
async def get_call(tenant_id: str, call_id: str):
    data = await db.get_call_detail(tenant_id, call_id)
    if not data:
        raise HTTPException(status_code=404, detail="Call not found")
    return data
