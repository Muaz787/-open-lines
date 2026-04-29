import logging
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from db import supabase as db
from services import provisioning

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

VALID_INDUSTRIES = {"realtor", "clinic", "parliament"}

# Sensitive fields stripped before returning tenant data publicly
_SENSITIVE = {"twilio_auth_token", "twilio_subaccount_sid"}


def _sanitize_tenant(tenant: dict) -> dict:
    return {k: v for k, v in tenant.items() if k not in _SENSITIVE}


class ProvisionRequest(BaseModel):
    business_name: str
    industry: str
    owner_name: str = ""
    whatsapp_number: str = ""
    website_url: str = ""
    agent_name: str = "Alex"

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
        result = await provisioning.provision_tenant(body.model_dump())
        logger.info("Provisioned tenant %s (%s)", result.get("tenant_id"), body.business_name)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error provisioning '%s': %s", body.business_name, e)
        raise HTTPException(status_code=500, detail="Provisioning failed unexpectedly")


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
