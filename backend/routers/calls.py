from fastapi import APIRouter, HTTPException
from db import supabase as db

router = APIRouter(prefix="/calls", tags=["calls"])


@router.get("/{tenant_id}/analytics")
async def get_analytics(tenant_id: str, days: int = 30):
    calls = await db.get_calls_with_leads(tenant_id, days=days, limit=1000)
    total = len(calls)
    total_secs = sum(c.get("duration_secs") or 0 for c in calls)
    avg_duration = round(total_secs / total) if total else 0

    urgency_counts: dict = {"hot": 0, "warm": 0, "cold": 0, "unknown": 0}
    calls_by_day: dict = {}
    for c in calls:
        lead = c.get("leads") or {}
        u = (lead.get("urgency") or "unknown").lower()
        urgency_counts[u if u in urgency_counts else "unknown"] += 1
        day = (c.get("created_at") or "")[:10]
        if day:
            calls_by_day[day] = calls_by_day.get(day, 0) + 1

    return {
        "total_calls": total,
        "avg_duration_secs": avg_duration,
        "urgency_breakdown": urgency_counts,
        "calls_by_day": calls_by_day,
    }


@router.get("/{tenant_id}")
async def list_calls(tenant_id: str, days: int = 30):
    return await db.get_calls_with_leads(tenant_id, days=days)


@router.get("/{tenant_id}/{call_id}")
async def get_call(tenant_id: str, call_id: str):
    data = await db.get_call_detail(tenant_id, call_id)
    if not data:
        raise HTTPException(status_code=404, detail="Call not found")
    return data
