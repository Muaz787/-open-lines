import logging
from fastapi import APIRouter, HTTPException

from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Fields surfaced in admin list — no credentials exposed
_TENANT_SUMMARY_FIELDS = "id, business_name, industry, twilio_phone_number, is_active, created_at"


@router.get("/tenants")
async def list_tenants():
    try:
        res = (
            db.get_client()
            .table("tenants")
            .select(_TENANT_SUMMARY_FIELDS)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data
    except Exception as e:
        logger.error("Failed to fetch tenant list: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch tenants")


@router.patch("/tenants/{tenant_id}/toggle")
async def toggle_tenant(tenant_id: str):
    # Fetch current state first so the toggle is always accurate
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    new_state: bool = not tenant["is_active"]

    try:
        updated = await db.update_tenant(tenant_id, {"is_active": new_state})
        logger.info(
            "Tenant %s (%s) toggled is_active → %s",
            tenant_id, tenant.get("business_name"), new_state,
        )
        return {
            "id": updated["id"],
            "business_name": updated["business_name"],
            "is_active": updated["is_active"],
        }
    except Exception as e:
        logger.error("Failed to toggle tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update tenant")
