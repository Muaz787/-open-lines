import logging
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from db import supabase as db
from services import provisioning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

VALID_INDUSTRIES = {
    "realtor", "clinic", "parliament",
    "plumber", "restaurant", "builder", "dental", "legal", "beauty",
    "custom",
}

# Sensitive fields stripped before returning tenant data publicly
_SENSITIVE = {"twilio_auth_token", "twilio_subaccount_sid"}


def _sanitize_tenant(tenant: dict) -> dict:
    return {k: v for k, v in tenant.items() if k not in _SENSITIVE}


class ProvisionRequest(BaseModel):
    business_name: str
    industry: str
    owner_name: str = ""
    country: str = "CA"
    whatsapp_number: str = ""
    website_url: str = ""
    agent_name: str = "Alex"
    extra_instructions: str = ""
    business_description: str = ""
    email: str = ""
    password: str = ""

    @field_validator("industry")
    @classmethod
    def industry_must_be_valid(cls, v: str) -> str:
        if v not in VALID_INDUSTRIES:
            raise ValueError(f"industry must be one of {sorted(VALID_INDUSTRIES)}")
        return v

    @field_validator("business_name")
    @classmethod
    def business_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("business_name cannot be empty")
        return v.strip()


@router.post("/provision")
async def provision(body: ProvisionRequest):
    try:
        provision_data = body.model_dump(exclude={"email", "password"})
        result = await provisioning.provision_tenant(provision_data)
        logger.info("Provisioned tenant %s (%s)", result.get("tenant_id"), body.business_name)

        if body.email and body.password:
            try:
                user_id = await db.create_auth_user(body.email, body.password, result["tenant_id"])
                await db.update_tenant(result["tenant_id"], {"user_id": user_id, "email": body.email})
                logger.info("Created auth user for tenant %s", result["tenant_id"])
            except Exception as e:
                logger.error("Auth user creation failed for tenant %s: %s", result.get("tenant_id"), e)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error provisioning '%s': %s", body.business_name, e)
        raise HTTPException(status_code=500, detail="Provisioning failed unexpectedly")


class SettingsUpdateRequest(BaseModel):
    whatsapp_number: str | None = None


@router.patch("/settings/{tenant_id}")
async def update_settings(tenant_id: str, body: SettingsUpdateRequest):
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided")
    try:
        updated = await db.update_tenant(tenant_id, update_data)
        return _sanitize_tenant(updated)
    except Exception as e:
        logger.error("Settings update failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Settings update failed")


@router.get("/status/{tenant_id}")
async def onboarding_status(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return _sanitize_tenant(tenant)
