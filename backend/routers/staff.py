"""
Named staff / resources management (Phase 2). Tenant-owner scoped.

A tenant is in "staff mode" whenever it has >= 1 active staff member — then
booking capacity per slot = the active-staff count and each appointment is
attributed to a staff member. Managed from the dashboard Calendar page.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator

from db import supabase as db
from services.security import require_tenant_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/staff", tags=["staff"], dependencies=[Depends(require_tenant_owner)])


async def _repatch_assistant(tenant_id: str) -> None:
    """Rebuild the assistant prompt + tools so the staff roster the AI sees stays
    in sync after a staff change. Non-fatal, runs in the background."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if not tenant or not tenant.get("vapi_assistant_id") or tenant.get("industry") == "custom":
            return
        from services.provisioning import rebuild_and_push_system_prompt
        await rebuild_and_push_system_prompt(tenant)
        logger.info("Re-patched assistant after staff change for tenant %s", tenant_id)
    except Exception as e:
        logger.error("Staff re-patch failed for tenant %s: %s", tenant_id, e)


class StaffCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v[:60]


class StaffUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        return v[:60]


@router.get("/{tenant_id}")
async def list_staff(tenant_id: str):
    try:
        return {"staff": await db.list_staff(tenant_id, active_only=True)}
    except Exception as e:
        logger.error("staff list failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to load staff")


@router.post("/{tenant_id}")
async def add_staff(tenant_id: str, body: StaffCreate):
    try:
        created = await db.create_staff(tenant_id, body.name)
        asyncio.create_task(_repatch_assistant(tenant_id))
        return created
    except Exception as e:
        logger.error("staff create failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to add staff")


@router.patch("/{tenant_id}/{staff_id}")
async def edit_staff(tenant_id: str, staff_id: str, body: StaffUpdate):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided")
    try:
        updated = await db.update_staff(tenant_id, staff_id, data)
        asyncio.create_task(_repatch_assistant(tenant_id))
        return updated
    except Exception as e:
        logger.error("staff update failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update staff")


@router.delete("/{tenant_id}/{staff_id}")
async def remove_staff(tenant_id: str, staff_id: str):
    """Soft-delete (deactivate) so existing appointment attribution is preserved."""
    try:
        await db.update_staff(tenant_id, staff_id, {"is_active": False})
        asyncio.create_task(_repatch_assistant(tenant_id))
        return {"status": "deactivated"}
    except Exception as e:
        logger.error("staff delete failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to remove staff")
