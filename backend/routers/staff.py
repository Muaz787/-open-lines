"""
Named staff / resources management (Phase 2). Tenant-owner scoped.

A tenant is in "staff mode" whenever it has >= 1 active staff member — then
booking capacity per slot = the active-staff count and each appointment is
attributed to a staff member. Managed from the dashboard Calendar page.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, field_validator

from db import supabase as db
from services.security import require_tenant_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/staff", tags=["staff"], dependencies=[Depends(require_tenant_owner)])


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
        return await db.create_staff(tenant_id, body.name)
    except Exception as e:
        logger.error("staff create failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to add staff")


@router.patch("/{tenant_id}/{staff_id}")
async def edit_staff(tenant_id: str, staff_id: str, body: StaffUpdate):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided")
    try:
        return await db.update_staff(tenant_id, staff_id, data)
    except Exception as e:
        logger.error("staff update failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update staff")


@router.delete("/{tenant_id}/{staff_id}")
async def remove_staff(tenant_id: str, staff_id: str):
    """Soft-delete (deactivate) so existing appointment attribution is preserved."""
    try:
        await db.update_staff(tenant_id, staff_id, {"is_active": False})
        return {"status": "deactivated"}
    except Exception as e:
        logger.error("staff delete failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to remove staff")
