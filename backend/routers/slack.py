import os
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from services import slack as slack_svc
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack"])

_raw_frontend = os.getenv("FRONTEND_URL", "https://openlines.ai")
FRONTEND_URL  = _raw_frontend if _raw_frontend.startswith("http") else f"https://{_raw_frontend}"


@router.get("/connect")
async def slack_connect(tenant_id: str):
    try:
        url = slack_svc.build_auth_url(tenant_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return RedirectResponse(url)


@router.get("/callback")
async def slack_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    tenant_id        = state or ""
    integrations_page = f"{FRONTEND_URL}/dashboard/{tenant_id}/integrations"

    if error or not code or not tenant_id:
        logger.warning("Slack OAuth error for tenant %s: %s", tenant_id, error)
        return RedirectResponse(f"{integrations_page}?slack=error")

    try:
        data = await slack_svc.exchange_code(code)
    except Exception as e:
        logger.error("Slack token exchange failed for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{integrations_page}?slack=error")

    webhook      = data.get("incoming_webhook", {})
    webhook_url  = webhook.get("url", "")
    channel_name = webhook.get("channel", "")
    team_name    = (data.get("team") or {}).get("name", "")

    if not webhook_url:
        logger.error("Slack response missing webhook URL for tenant %s", tenant_id)
        return RedirectResponse(f"{integrations_page}?slack=error")

    try:
        await db.update_tenant(tenant_id, {
            "slack_webhook_url":   webhook_url,
            "slack_team_name":     team_name,
            "slack_channel_name":  channel_name,
            "slack_connected_at":  datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error("Failed to store Slack credentials for tenant %s: %s", tenant_id, e)
        return RedirectResponse(f"{integrations_page}?slack=error")

    logger.info("Slack connected for tenant %s (team=%s channel=%s)", tenant_id, team_name, channel_name)
    return RedirectResponse(f"{integrations_page}?slack=connected")


@router.get("/status/{tenant_id}")
async def slack_status(tenant_id: str):
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "connected":    bool(tenant.get("slack_webhook_url")),
        "team_name":    tenant.get("slack_team_name") or None,
        "channel_name": tenant.get("slack_channel_name") or None,
        "connected_at": tenant.get("slack_connected_at") or None,
    }


@router.post("/disconnect/{tenant_id}")
async def slack_disconnect(tenant_id: str):
    try:
        await db.update_tenant(tenant_id, {
            "slack_webhook_url":   None,
            "slack_team_name":     None,
            "slack_channel_name":  None,
            "slack_connected_at":  None,
        })
    except Exception as e:
        logger.error("Failed to clear Slack credentials for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to disconnect Slack")

    logger.info("Slack disconnected for tenant %s", tenant_id)
    return {"status": "disconnected"}
