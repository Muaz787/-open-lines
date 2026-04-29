import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["leads"])


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
