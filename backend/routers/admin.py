import os
import logging
from fastapi import APIRouter, HTTPException, Header

from db import supabase as db
from services import vapi
from services.provisioning import rebuild_and_push_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Fields surfaced in admin list — no credentials exposed
_TENANT_SUMMARY_FIELDS = "id, business_name, industry, twilio_phone_number, is_active, created_at"


def _check_admin_key(x_admin_key: str | None) -> None:
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.get("/tenants")
async def list_tenants(x_admin_key: str | None = Header(None)):
    _check_admin_key(x_admin_key)
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
async def toggle_tenant(tenant_id: str, x_admin_key: str | None = Header(None)):
    _check_admin_key(x_admin_key)
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
async def reprompt_tenant(tenant_id: str, x_admin_key: str | None = Header(None)):
    """Rebuild the system prompt from the current template and push it to the Vapi assistant."""
    _check_admin_key(x_admin_key)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        return await rebuild_and_push_system_prompt(tenant)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("Reprompt failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tenants/{tenant_id}/enable-smart-routing")
async def enable_smart_routing(tenant_id: str, x_admin_key: str | None = Header(None)):
    """Switch the tenant's Vapi phone number from assistantId to serverUrl so that
    assistant-request fires on every inbound call (enables instant caller recognition)."""
    _check_admin_key(x_admin_key)
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
    app_backend_url = os.getenv("APP_BACKEND_URL", "").strip().rstrip("/")
    if not app_backend_url:
        raise HTTPException(status_code=500, detail="APP_BACKEND_URL not set")

    try:
        await vapi.update_phone_number(stored_phone_id, {
            "assistantId": None,
            "squadId": None,
            **vapi.server_block(f"{app_backend_url}/webhooks/vapi-call-ended"),
        })
    except Exception as e:
        detail = str(e)
        import httpx as _httpx
        if isinstance(e, _httpx.HTTPStatusError):
            detail = f"Vapi {e.response.status_code}: {e.response.text[:300]}"
        logger.error("Failed to update Vapi phone number %s: %s", stored_phone_id, detail)
        raise HTTPException(status_code=500, detail=detail)

    logger.info("Smart routing enabled for tenant %s (phone number %s)", tenant_id, stored_phone_id)
    return {"status": "enabled", "vapi_phone_number_id": stored_phone_id}


@router.post("/repatch-vapi-secret")
async def repatch_vapi_secret(x_admin_key: str | None = Header(None)):
    """Re-patch every tenant's Vapi phone-number server config so the inbound
    `assistant-request` webhook carries the current X-Vapi-Secret.

    Run this ONCE right after setting VAPI_SERVER_SECRET in the environment.
    Per-call `assistant-request` originates from the phone-number server config
    (before our override exists), so existing tenants need this; everything after
    that (end-of-call-report, tool calls) inherits the secret from the per-call
    override automatically. Idempotent and safe to re-run. When VAPI_SERVER_SECRET
    is unset this simply rewrites the flat serverUrl (no-op in practice)."""
    _check_admin_key(x_admin_key)

    app_backend_url = os.getenv("APP_BACKEND_URL", "").strip().rstrip("/")
    if not app_backend_url:
        raise HTTPException(status_code=500, detail="APP_BACKEND_URL not set")
    server_url = f"{app_backend_url}/webhooks/vapi-call-ended"

    try:
        res = (
            db.get_client()
            .table("tenants")
            .select("id, vapi_phone_number_id, vapi_suborg_api_key")
            .execute()
        )
        tenants = [t for t in (res.data or []) if t.get("vapi_phone_number_id")]
    except Exception as e:
        logger.error("repatch-vapi-secret: tenant fetch failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list tenants")

    enforced = bool(os.getenv("VAPI_SERVER_SECRET", ""))
    results = {"ok": 0, "errors": 0, "skipped": 0}
    for t in tenants:
        phone_id = t.get("vapi_phone_number_id")
        if not phone_id:
            results["skipped"] += 1
            continue
        try:
            key = vapi.get_tenant_vapi_key(t)
            await vapi.update_phone_number(phone_id, vapi.server_block(server_url), api_key=key)
            results["ok"] += 1
        except Exception as e:
            logger.error("repatch-vapi-secret: failed for tenant %s: %s", t.get("id"), e)
            results["errors"] += 1

    logger.info("repatch-vapi-secret done (enforced=%s): %s", enforced, results)
    return {"secret_enforced": enforced, "phone_numbers": results, "total": len(tenants)}
