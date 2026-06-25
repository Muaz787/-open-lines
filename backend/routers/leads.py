import json
import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Depends
from openai import AsyncOpenAI
from pydantic import BaseModel

from db import supabase as db
from services.security import require_tenant_owner

logger = logging.getLogger(__name__)

# Every route here exposes/edits tenant lead PII — require ownership.
router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(require_tenant_owner)])

_openai: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        _openai = AsyncOpenAI(api_key=key)
    return _openai


class LeadUpdateRequest(BaseModel):
    status: str | None = None
    notes: str | None = None


@router.get("/{tenant_id}")
async def list_leads(
    tenant_id: str,
    limit: int = Query(default=50, ge=1, le=500),
):
    try:
        leads = await db.get_leads(tenant_id, limit=limit)
        return leads
    except Exception as e:
        logger.error("Failed to fetch leads for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch leads")


def _period_window(period: str):
    """Return (start_dt, bucket_count, index_fn) for the requested period.
    'today' buckets by hour since midnight UTC; 7d/30d bucket by day."""
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        n = now.hour + 1
        return start, n, (lambda dt: min(max(dt.hour, 0), n - 1))
    days = 30 if period == "30d" else 7
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, days, (lambda dt: min(max((dt - start).days, 0), days - 1))


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/{tenant_id}/stats")
async def get_stats(
    tenant_id: str,
    period: str = Query(default="7d", pattern="^(today|7d|30d)$"),
):
    """Period-scoped performance totals plus a per-bucket time series for each
    metric, used to draw the dashboard trend charts."""
    start, n_buckets, bucket_idx = _period_window(period)
    start_iso = start.isoformat()
    try:
        client = db.get_client()
        calls = (client.table("calls").select("created_at,duration_secs")
                 .eq("tenant_id", tenant_id).gte("created_at", start_iso).limit(100_000).execute().data or [])
        leads = (client.table("leads").select("created_at")
                 .eq("tenant_id", tenant_id).gte("created_at", start_iso).limit(100_000).execute().data or [])
        appts = (client.table("appointments").select("created_at")
                 .eq("tenant_id", tenant_id).neq("status", "cancelled")
                 .gte("created_at", start_iso).limit(100_000).execute().data or [])
    except Exception as e:
        logger.error("Failed to fetch stats for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

    calls_s = [0] * n_buckets
    leads_s = [0] * n_buckets
    appts_s = [0] * n_buckets
    secs_s  = [0.0] * n_buckets

    for r in calls:
        try:
            i = bucket_idx(_parse_ts(r["created_at"]))
        except Exception:
            continue
        calls_s[i] += 1
        secs_s[i]  += (r.get("duration_secs") or 0)
    for r in leads:
        try:
            leads_s[bucket_idx(_parse_ts(r["created_at"]))] += 1
        except Exception:
            continue
    for r in appts:
        try:
            appts_s[bucket_idx(_parse_ts(r["created_at"]))] += 1
        except Exception:
            continue

    minutes_s   = [round(s / 60) for s in secs_s]
    total_secs  = sum(secs_s)

    return {
        "period":              period,
        "total_calls":         sum(calls_s),
        "total_leads":         sum(leads_s),
        "minutes_handled":     round(total_secs / 60),
        "appointments_booked": sum(appts_s),
        "series": {
            "calls":        calls_s,
            "leads":        leads_s,
            "minutes":      minutes_s,
            "appointments": appts_s,
        },
    }


@router.get("/{tenant_id}/insights")
async def get_insights(tenant_id: str):
    try:
        leads = await db.get_leads(tenant_id, limit=500)
        calls = await db.get_calls(tenant_id, limit=500)
    except Exception as e:
        logger.error("Failed to fetch data for insights tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch data")

    if len(calls) < 3:
        return {"insights": [], "generated_at": None}

    hot  = sum(1 for l in leads if l.get("urgency") == "hot")
    warm = sum(1 for l in leads if l.get("urgency") == "warm")
    cold = sum(1 for l in leads if l.get("urgency") == "cold")

    recent_summaries = [
        {
            "urgency": l.get("urgency", ""),
            "summary": l.get("summary", ""),
            "status": l.get("status", ""),
        }
        for l in leads[:60]
        if l.get("summary")
    ]

    prompt = (
        f"Total calls: {len(calls)}\n"
        f"Total leads: {len(leads)}\n"
        f"Urgency breakdown: hot={hot}, warm={warm}, cold={cold}\n\n"
        f"Recent lead summaries:\n{json.dumps(recent_summaries, indent=2)}\n\n"
        "Generate 3-4 concise, actionable business insights from this call and lead data.\n"
        "Focus on patterns, missed opportunities, and specific follow-up recommendations.\n"
        "Return JSON: {\"insights\": [{\"title\": str, \"body\": str, \"type\": \"opportunity|warning|trend|success\"}]}"
    )

    try:
        resp = await _get_openai().chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a concise business intelligence analyst for an AI voice receptionist. Be specific and actionable."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.6,
        )
        result = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.error("GPT-4o insights failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Insights generation failed")

    return {
        "insights": result.get("insights", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{tenant_id}/{lead_id}")
async def get_lead(tenant_id: str, lead_id: str):
    try:
        leads_res = (
            db.get_client()
            .table("leads")
            .select("*")
            .eq("id", lead_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        lead = leads_res.data
    except Exception as e:
        logger.error("Lead %s not found for tenant %s: %s", lead_id, tenant_id, e)
        raise HTTPException(status_code=404, detail="Lead not found")

    try:
        calls = await db.get_calls(tenant_id, limit=200)
        lead_calls = [c for c in calls if c.get("lead_id") == lead_id]
    except Exception as e:
        logger.error("Failed to fetch calls for lead %s: %s", lead_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch calls")

    return {**lead, "calls": lead_calls}


@router.patch("/{tenant_id}/{lead_id}")
async def update_lead(tenant_id: str, lead_id: str, body: LeadUpdateRequest):
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    try:
        updated = await db.update_lead(tenant_id, lead_id, update_data)
        return updated
    except Exception as e:
        logger.error("Failed to update lead %s for tenant %s: %s", lead_id, tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update lead")
