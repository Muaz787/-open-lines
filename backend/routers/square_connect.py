import asyncio
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Header
from fastapi.responses import RedirectResponse

from services import square_service as sq_svc, square_booking, vapi
from services.security import encrypt, verify_tenant_owner
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/square-connect", tags=["square-connect"])

_FRONTEND = sq_svc.FRONTEND_URL


def _payments_page(tenant_id: str) -> str:
    return f"{_FRONTEND}/dashboard/{tenant_id}/payments"


# ---------------------------------------------------------------------------
# POST /square-connect/onboard/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/onboard/{tenant_id}")
async def onboard(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """Generate Square OAuth authorize URL and return it for redirect."""
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plan   = (tenant.get("subscription_plan") or "").lower()
    status = tenant.get("subscription_status") or ""
    if plan not in ("pro", "business") or status not in ("active", "trialing", "canceling"):
        raise HTTPException(status_code=403, detail="Square payments require a Pro or Business plan")

    state = secrets.token_urlsafe(24)
    try:
        await db.update_tenant(tenant_id, {"square_oauth_state": state})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    url = sq_svc.build_oauth_url(tenant_id, state=f"{tenant_id}:{state}")
    return {"url": url}


# ---------------------------------------------------------------------------
# GET /square-connect/callback
# ---------------------------------------------------------------------------

@router.get("/callback")
async def callback(request: Request, code: str = "", error: str = "", state: str = ""):
    """Square OAuth callback — exchanges code for tokens and stores them."""
    tenant_id = state.split(":")[0] if ":" in state else ""
    fallback  = _payments_page(tenant_id) if tenant_id else f"{_FRONTEND}/"

    if error:
        logger.warning("Square OAuth error: %s", error)
        return RedirectResponse(url=f"{fallback}?square=error")

    if not code or not state:
        return RedirectResponse(url=f"{_FRONTEND}/?square=error")

    parts = state.split(":", 1)
    if len(parts) != 2:
        return RedirectResponse(url=f"{_FRONTEND}/?square=error")
    tenant_id, received_state = parts

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        return RedirectResponse(url=f"{_FRONTEND}/?square=error")

    if not tenant:
        return RedirectResponse(url=f"{_FRONTEND}/?square=error")

    stored_state = tenant.get("square_oauth_state", "")
    if not stored_state or not secrets.compare_digest(stored_state, received_state):
        logger.warning("Square OAuth: state mismatch for tenant %s", tenant_id)
        return RedirectResponse(url=f"{_payments_page(tenant_id)}?square=error")

    try:
        token_data = await sq_svc.exchange_code(code)
    except Exception as e:
        logger.error("Square OAuth token exchange failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(url=f"{_payments_page(tenant_id)}?square=error")

    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_at    = token_data.get("expires_at")
    merchant_id   = token_data.get("merchant_id", "")

    if not access_token:
        logger.error("Square OAuth: no access_token in response for tenant %s", tenant_id)
        return RedirectResponse(url=f"{_payments_page(tenant_id)}?square=error")

    location_id = ""
    currency    = ""
    try:
        merchant_info = await sq_svc.get_merchant_info(access_token)
        currency = merchant_info.get("currency", "USD").lower()
        if not merchant_id:
            merchant_id = merchant_info.get("merchant_id", "")
    except Exception as e:
        logger.warning("Square OAuth: could not fetch merchant info for tenant %s: %s", tenant_id, e)
    try:
        locations = await sq_svc.list_locations(access_token)
        if locations:
            location_id = locations[0].get("id", "")
    except Exception as e:
        logger.warning("Square OAuth: could not fetch locations for tenant %s: %s", tenant_id, e)

    try:
        update = {
            "square_access_token":    encrypt(access_token),
            "square_refresh_token":   encrypt(refresh_token) if refresh_token else None,
            "square_token_expires_at": expires_at or None,
            "square_merchant_id":     merchant_id or None,
            "square_location_id":     location_id or None,
            "square_currency":        currency or None,
            "square_oauth_state":     None,
        }
        await db.update_tenant(tenant_id, update)
    except Exception as e:
        logger.error("Square OAuth: DB update failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(url=f"{_payments_page(tenant_id)}?square=error")

    # Re-patch Vapi assistant so the deposit tool appears
    try:
        updated_tenant = await db.get_tenant_by_id(tenant_id)
        if updated_tenant:
            await vapi.patch_assistant_tools(updated_tenant)
    except Exception as e:
        logger.warning("Square OAuth: assistant patch failed for tenant %s: %s", tenant_id, e)

    # Best-effort Appointments sync (no-op if the merchant hasn't granted the
    # appointments scopes / doesn't use Square Appointments).
    try:
        asyncio.create_task(square_booking.sync(tenant_id))
    except Exception as e:
        logger.warning("Square OAuth: appointments sync kickoff failed for %s: %s", tenant_id, e)

    logger.info("Square Connect completed for tenant %s merchant %s", tenant_id, merchant_id)
    return RedirectResponse(url=f"{_payments_page(tenant_id)}?square=connected")


# ---------------------------------------------------------------------------
# GET /square-connect/status/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/status/{tenant_id}")
async def connect_status(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.get("square_access_token"):
        return {"connected": False}

    return {
        "connected":   True,
        "merchant_id": tenant.get("square_merchant_id"),
        "location_id": tenant.get("square_location_id"),
        "currency":    (tenant.get("square_currency") or "usd").upper(),
    }


# ---------------------------------------------------------------------------
# POST /square-connect/disconnect/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/disconnect/{tenant_id}")
async def connect_disconnect(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        await db.update_tenant(tenant_id, {
            "square_access_token":    None,
            "square_refresh_token":   None,
            "square_token_expires_at": None,
            "square_merchant_id":     None,
            "square_location_id":     None,
            "square_currency":        None,
            "square_deposits_enabled": False,
        })
        if tenant:
            patched = {**tenant, "square_access_token": None, "square_deposits_enabled": False}
            await vapi.patch_assistant_tools(patched)
    except Exception as e:
        logger.error("Square disconnect failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Disconnect failed")

    logger.info("Square Connect disconnected for tenant %s", tenant_id)
    return {"status": "disconnected"}


# ---------------------------------------------------------------------------
# Square Appointments — sync catalog/team and read the mapping (frontend review)
# ---------------------------------------------------------------------------

@router.post("/appointments/sync/{tenant_id}")
async def appointments_sync(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    result = await square_booking.sync(tenant_id)
    if not result.get("ok"):
        detail = {"not_connected": "Connect Square first",
                  "tenant_not_found": "Tenant not found"}.get(result.get("error"), "Sync failed")
        raise HTTPException(status_code=400, detail=detail)
    return result


@router.get("/appointments/{tenant_id}")
async def appointments_status(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "connected":   bool(tenant.get("square_access_token")),
        "enabled":     bool(tenant.get("square_appointments_enabled")),
        "bookable":    bool(tenant.get("square_appointments_bookable")),
        "synced_at":   tenant.get("square_booking_synced_at"),
        "location_timezone": tenant.get("square_location_timezone"),
        "services":    await db.get_square_services(tenant_id, bookable_only=False),
        "staff":       await db.get_square_staff(tenant_id),
    }
