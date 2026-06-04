import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from openai import AsyncOpenAI
from pydantic import BaseModel

from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])

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


@router.get("/{tenant_id}/stats")
async def get_stats(tenant_id: str):
    try:
        client = db.get_client()

        # Accurate counts — never capped by a row limit
        calls_res = client.table("calls").select("id", count="exact").eq("tenant_id", tenant_id).execute()
        leads_res = client.table("leads").select("id", count="exact").eq("tenant_id", tenant_id).execute()

        # Appointments booked = confirmed + completed (excludes cancelled)
        appts_res = (
            client.table("appointments")
            .select("id", count="exact")
            .eq("tenant_id", tenant_id)
            .neq("status", "cancelled")
            .execute()
        )

        # Total call time — fetch only duration_secs column, high limit
        dur_res = (
            client.table("calls")
            .select("duration_secs")
            .eq("tenant_id", tenant_id)
            .limit(100_000)
            .execute()
        )
    except Exception as e:
        logger.error("Failed to fetch stats for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

    total_secs = sum(r.get("duration_secs") or 0 for r in (dur_res.data or []))
    return {
        "total_calls":         calls_res.count or 0,
        "total_leads":         leads_res.count or 0,
        "minutes_handled":     round(total_secs / 60),
        "appointments_booked": appts_res.count or 0,
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
