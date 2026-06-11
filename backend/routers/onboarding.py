import logging
import os
from typing import Annotated, Literal
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from db import supabase as db
from services import analytics, provisioning, vapi
from services.ratelimit import limiter

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
@limiter.limit("3/hour")
async def provision(request: Request, body: ProvisionRequest):
    try:
        provision_data = body.model_dump(exclude={"email", "password"})
        result = await provisioning.provision_tenant(provision_data)
        logger.info("Provisioned tenant %s (%s)", result.get("tenant_id"), body.business_name)

        distinct_id = result.get("tenant_id", "")
        if body.email and body.password:
            try:
                user_id = await db.create_auth_user(body.email, body.password, result["tenant_id"])
                await db.update_tenant(result["tenant_id"], {"user_id": user_id, "email": body.email})
                logger.info("Created auth user for tenant %s", result["tenant_id"])
                distinct_id = user_id
            except Exception as e:
                logger.error("Auth user creation failed for tenant %s: %s", result.get("tenant_id"), e)

        # PRIVACY: business metadata only — no phone numbers, no credentials
        common = {
            "tenant_id": result.get("tenant_id"),
            "business_name": body.business_name,
            "industry": body.industry,
            "country": body.country,
        }
        analytics.capture(distinct_id, "tenant_created", common)
        analytics.capture(distinct_id, "phone_number_provisioned", {"tenant_id": result.get("tenant_id")})
        if body.email:
            analytics.capture(distinct_id, "signup_completed", common)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error provisioning '%s': %s", body.business_name, e)
        raise HTTPException(status_code=500, detail="Provisioning failed unexpectedly")


class SettingsUpdateRequest(BaseModel):
    whatsapp_number:      str | None = None
    notification_email:   str | None = None
    email_notifications:  bool | None = None
    business_hours_start: int | None = None
    business_hours_end:   int | None = None
    business_days:        list[int] | None = None
    break_start:          int | None = None
    break_end:            int | None = None
    booking_instructions: str | None = None


@router.patch("/settings/{tenant_id}")
async def update_settings(tenant_id: str, body: SettingsUpdateRequest):
    # exclude_unset (not exclude_none) so callers can explicitly clear a field by
    # sending null — needed to remove the daily break (break_start/break_end = null).
    update_data = body.model_dump(exclude_unset=True)
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


@router.post("/admin-reprompt/{tenant_id}")
async def admin_reprompt(
    tenant_id: str,
    x_admin_key: Annotated[str | None, Header()] = None,
):
    """Rebuild and push system prompt + patch Vapi assistant config for a tenant.
    Secured with VAPI_API_KEY as admin key (backend-only operation).
    """
    if x_admin_key != os.getenv("VAPI_API_KEY", ""):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    assistant_id = tenant.get("vapi_assistant_id")
    if not assistant_id:
        raise HTTPException(status_code=400, detail="No Vapi assistant on this tenant")

    # 1 — Patch top-level Vapi assistant config (endCallMessage, silence timeout)
    try:
        await vapi.update_assistant(assistant_id, {
            "endCallMessage": "",
            "silenceTimeoutSeconds": 10,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vapi assistant patch failed: {e}")

    # 2 — Rebuild system prompt from template + KB and push to Vapi
    if tenant.get("industry") == "custom":
        return {"status": "config_patched_only", "note": "Custom industry — prompt not rebuilt"}
    try:
        result = await provisioning.rebuild_and_push_system_prompt(tenant)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt rebuild failed: {e}")

    return {"status": "reprompted", **result}


@router.post("/repair-phone-url/{tenant_id}")
async def repair_phone_url(tenant_id: str):
    """Patch the Vapi phone number for this tenant to include the correct serverUrl.

    This enables smart routing (assistant-request webhook) so date injection,
    caller recognition, and personalized greetings work on every call.
    Falls back to searching Vapi's phone list by E.164 number if the Vapi
    phone number ID isn't stored (covers tenants provisioned before this fix).
    """
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    twilio_phone = tenant.get("twilio_phone_number", "")
    vapi_phone_id = tenant.get("vapi_phone_number_id", "")
    server_url = f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended"

    # If we don't have the ID stored, search Vapi's list by E.164 number
    if not vapi_phone_id:
        try:
            numbers = await vapi.list_phone_numbers()
            for pn in numbers:
                if pn.get("number") == twilio_phone:
                    vapi_phone_id = pn.get("id", "")
                    break
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Vapi phone list failed: {e}")

    if not vapi_phone_id:
        raise HTTPException(status_code=404, detail=f"Could not find Vapi phone number for {twilio_phone}")

    try:
        await vapi.update_phone_number(vapi_phone_id, {"serverUrl": server_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vapi PATCH failed: {e}")

    # Persist the ID so future repairs are instant
    await db.update_tenant(tenant_id, {"vapi_phone_number_id": vapi_phone_id})

    logger.info("Repaired serverUrl for tenant %s phone %s (%s)", tenant_id, twilio_phone, vapi_phone_id)
    return {"status": "repaired", "vapi_phone_id": vapi_phone_id, "server_url": server_url}
