import os
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from services import hubspot as hs
from services.hubspot import HubSpotTokenError
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hubspot", tags=["hubspot"])

_raw_frontend = os.getenv("FRONTEND_URL", "https://openlines.ai")
FRONTEND_URL  = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"


# ---------------------------------------------------------------------------
# GET /hubspot/connect?tenant_id=...  — kick off OAuth flow
# ---------------------------------------------------------------------------

@router.get("/connect")
async def hubspot_connect(tenant_id: str):
    try:
        url = hs.build_auth_url(tenant_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# GET /hubspot/callback  — HubSpot redirects here with code + state
# ---------------------------------------------------------------------------

@router.get("/callback")
async def hubspot_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    tenant_id = state or ""
    integrations_page = f"{FRONTEND_URL}/dashboard/{tenant_id}/integrations"

    if error or not code or not tenant_id:
        logger.warning("HubSpot OAuth error for tenant %s: %s", tenant_id, error)
        return RedirectResponse(f"{integrations_page}?hubspot=error")

    try:
        tokens = await hs.exchange_code_for_tokens(code)
    except Exception as e:
        logger.error("HubSpot token exchange failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{integrations_page}?hubspot=error")

    access_token  = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    expires_in    = int(tokens.get("expires_in", 1800))

    if not access_token or not refresh_token:
        logger.error("HubSpot response missing tokens for tenant %s", tenant_id)
        return RedirectResponse(f"{integrations_page}?hubspot=error")

    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Fetch portal/account info
    portal_id    = ""
    account_name = ""
    try:
        info = await hs.get_account_info(access_token)
        portal_id    = str(info.get("hub_id", ""))
        account_name = info.get("hub_domain") or info.get("user") or ""
    except Exception as e:
        logger.warning("HubSpot get_account_info failed for tenant %s (non-fatal): %s", tenant_id, e)

    try:
        await db.update_tenant(tenant_id, {
            "hubspot_access_token":    access_token,
            "hubspot_refresh_token":   refresh_token,
            "hubspot_token_expires_at": expires_at,
            "hubspot_portal_id":       portal_id,
            "hubspot_account_name":    account_name,
            "hubspot_connected_at":    datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error("Failed to store HubSpot tokens for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{integrations_page}?hubspot=error")

    logger.info("HubSpot connected for tenant %s (portal %s)", tenant_id, portal_id)
    return RedirectResponse(f"{integrations_page}?hubspot=connected")


# ---------------------------------------------------------------------------
# GET /hubspot/status/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/status/{tenant_id}")
async def hubspot_status(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    connected = bool(tenant.get("hubspot_refresh_token"))
    return {
        "connected":      connected,
        "portal_id":      tenant.get("hubspot_portal_id") or None,
        "account_name":   tenant.get("hubspot_account_name") or None,
        "connected_at":   tenant.get("hubspot_connected_at") or None,
    }


# ---------------------------------------------------------------------------
# POST /hubspot/disconnect/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/disconnect/{tenant_id}")
async def hubspot_disconnect(tenant_id: str):
    try:
        await db.update_tenant(tenant_id, {
            "hubspot_access_token":     None,
            "hubspot_refresh_token":    None,
            "hubspot_token_expires_at": None,
            "hubspot_portal_id":        None,
            "hubspot_account_name":     None,
            "hubspot_connected_at":     None,
        })
    except Exception as e:
        logger.error("Failed to clear HubSpot tokens for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to disconnect HubSpot")

    logger.info("HubSpot disconnected for tenant %s", tenant_id)
    return {"status": "disconnected"}
