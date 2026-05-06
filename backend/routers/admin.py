import os
import logging
from fastapi import APIRouter, HTTPException

from db import supabase as db
from services import vapi
from services.vapi import _CALLER_LOOKUP_NOTE
from services.provisioning import QUALIFICATION_FIELDS, _load_template
from routers.calendar import _CALENDAR_NOTE

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


@router.post("/tenants/{tenant_id}/reprompt")
async def reprompt_tenant(tenant_id: str):
    """Rebuild the system prompt from the current template and push it to the Vapi assistant."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    industry      = tenant.get("industry", "")
    business_name = tenant["business_name"]
    agent_name    = tenant.get("agent_name", "Alex")
    assistant_id  = tenant.get("vapi_assistant_id")

    if not assistant_id:
        raise HTTPException(status_code=400, detail="Tenant has no Vapi assistant")
    if industry == "custom":
        raise HTTPException(status_code=400, detail="Custom industry tenants must be re-provisioned manually")

    try:
        template = _load_template(industry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    qualification_fields = QUALIFICATION_FIELDS.get(industry, {})
    qualification_questions = "\n".join(f"- {q}" for q in qualification_fields.values())

    knowledge_context = "No website content available."
    try:
        from services import knowledge as kb_svc
        pinecone_namespace = tenant.get("pinecone_namespace", "")
        if pinecone_namespace:
            result = await kb_svc.query_knowledge_base(pinecone_namespace, "overview", top_k=20)
            if result:
                knowledge_context = result
    except Exception as e:
        logger.warning("KB fetch failed during reprompt for tenant %s (continuing): %s", tenant_id, e)

    try:
        system_prompt = template.format(
            business_name=business_name,
            agent_name=agent_name,
            qualification_questions=qualification_questions,
            knowledge_context=knowledge_context,
        )
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Template placeholder missing: {e}")

    extra = (tenant.get("extra_instructions") or "").strip()
    if extra:
        system_prompt += f"\n\nADDITIONAL INSTRUCTIONS FROM {business_name.upper()}\n{extra}"

    # Store the base prompt (without dynamic notes) for use in assistant-request smart routing
    base_system_prompt = system_prompt

    # Append dynamic notes for the persistent Vapi assistant (fallback path)
    system_prompt += _CALLER_LOOKUP_NOTE
    if tenant.get("google_refresh_token"):
        system_prompt += _CALENDAR_NOTE

    try:
        tools = (
            vapi.build_calendar_tools(tenant_id)
            if tenant.get("google_refresh_token")
            else [vapi.build_caller_lookup_tool(tenant_id)]
        )
        model_payload: dict = {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.7,
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": tools,
        }
        await vapi.update_assistant(assistant_id, {"model": model_payload})
        logger.info("Reprompted assistant %s for tenant %s", assistant_id, tenant_id)
    except Exception as e:
        logger.error("Failed to update Vapi assistant %s: %s", assistant_id, e)
        raise HTTPException(status_code=500, detail="Vapi assistant update failed")

    try:
        await db.update_tenant(tenant_id, {"last_system_prompt": base_system_prompt})
    except Exception as e:
        logger.warning("Could not store last_system_prompt for tenant %s (run DB migration): %s", tenant_id, e)

    return {"status": "updated", "assistant_id": assistant_id}


@router.post("/tenants/{tenant_id}/enable-smart-routing")
async def enable_smart_routing(tenant_id: str):
    """Switch the tenant's Vapi phone number from assistantId to serverUrl so that
    assistant-request fires on every inbound call (enables instant caller recognition)."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    twilio_number = tenant.get("twilio_phone_number", "")
    if not twilio_number:
        raise HTTPException(status_code=400, detail="Tenant has no twilio_phone_number")
    if not tenant.get("last_system_prompt"):
        raise HTTPException(status_code=400, detail="Run /reprompt first to populate last_system_prompt")

    # Find the Vapi phone number ID
    stored_phone_id = tenant.get("vapi_phone_number_id")
    if not stored_phone_id:
        try:
            numbers = await vapi.list_phone_numbers()
            match = next(
                (n for n in numbers if n.get("number") == twilio_number or n.get("twilioPhoneNumber") == twilio_number),
                None,
            )
            if not match:
                raise HTTPException(status_code=404, detail=f"No Vapi phone number found for {twilio_number}")
            stored_phone_id = match["id"]
            await db.update_tenant(tenant_id, {"vapi_phone_number_id": stored_phone_id})
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Failed to list Vapi phone numbers: %s", e)
            raise HTTPException(status_code=500, detail="Failed to look up Vapi phone number")

    # Switch from assistantId → serverUrl
    app_backend_url = os.getenv("APP_BACKEND_URL", "")
    if not app_backend_url:
        raise HTTPException(status_code=500, detail="APP_BACKEND_URL not set")

    try:
        await vapi.update_phone_number(stored_phone_id, {
            "assistantId": None,
            "serverUrl": f"{app_backend_url}/webhooks/vapi-call-ended",
        })
    except Exception as e:
        logger.error("Failed to update Vapi phone number %s: %s", stored_phone_id, e)
        raise HTTPException(status_code=500, detail="Failed to update Vapi phone number")

    logger.info("Smart routing enabled for tenant %s (phone number %s)", tenant_id, stored_phone_id)
    return {"status": "enabled", "vapi_phone_number_id": stored_phone_id}
