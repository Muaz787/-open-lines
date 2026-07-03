import logging
from typing import Annotated
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import RedirectResponse

from services.security import verify_tenant_owner
from services import stripe_service as svc, vapi
from db import supabase as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe-connect", tags=["stripe-connect"])

_FRONTEND = svc.FRONTEND_URL


def _payments_page(tenant_id: str) -> str:
    return f"{_FRONTEND}/dashboard/{tenant_id}/payments"


# ---------------------------------------------------------------------------
# POST /stripe-connect/onboard/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/onboard/{tenant_id}")
async def onboard(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    """Create (or reuse) a Stripe Connect Express account and return the onboarding URL."""
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
        raise HTTPException(status_code=403, detail="Stripe payments require a Pro or Business plan")

    account_id = tenant.get("stripe_account_id")

    # A stored account id from test mode 404s under the live key ("account not
    # connected to your platform or does not exist"). Drop it and recreate.
    if account_id and not await svc.account_exists(account_id):
        logger.warning(
            "Stored Connect account %s missing in current Stripe mode for tenant %s — recreating",
            account_id, tenant_id,
        )
        account_id = None
        await db.update_tenant(tenant_id, {"stripe_account_id": None, "stripe_deposits_enabled": False})

    try:
        if not account_id:
            account_id = await svc.create_connect_account(tenant["business_name"])
            await db.update_tenant(tenant_id, {"stripe_account_id": account_id})
            logger.info("Created Stripe Connect account %s for tenant %s", account_id, tenant_id)

        link_url = await svc.create_account_link(account_id, tenant_id)
    except svc.stripe.StripeError as e:
        msg = e.user_message or str(e)
        logger.error("Stripe Connect onboarding failed for tenant %s: %s", tenant_id, msg)
        # Brand-new live Connect platforms sit in review; account creation 400s until cleared.
        if "review" in msg.lower() or "not been enabled" in msg.lower() or "sign up for connect" in msg.lower():
            raise HTTPException(status_code=409, detail="Stripe is still reviewing your account for live payments. Please try again once Stripe has approved your platform (usually within a day).")
        raise HTTPException(status_code=502, detail=f"Stripe onboarding error: {msg}")

    return {"url": link_url}


# ---------------------------------------------------------------------------
# POST /stripe-connect/verify/{tenant_id}
# Called by the frontend after Stripe returns from onboarding.
# ---------------------------------------------------------------------------

@router.post("/verify/{tenant_id}")
async def connect_verify(tenant_id: str, body: dict, authorization: Annotated[str | None, Header()] = None):
    """Check account status, update DB, patch assistant. Called client-side after onboarding."""
    await verify_tenant_owner(tenant_id, authorization)
    account_id = body.get("account_id") or ""
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id required")

    try:
        account = await svc.get_account(account_id)
    except Exception as e:
        logger.error("Stripe verify: account fetch failed for %s: %s", account_id, e)
        raise HTTPException(status_code=500, detail="Could not verify Stripe account")

    try:
        await db.update_tenant(tenant_id, {"stripe_account_id": account["id"]})
    except Exception as e:
        logger.error("Stripe verify: DB update failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="DB update failed")

    if account["charges_enabled"]:
        try:
            tenant = await db.get_tenant_by_id(tenant_id)
            if tenant:
                await vapi.patch_assistant_tools(tenant)
        except Exception as e:
            logger.warning("Stripe verify: assistant patch failed for tenant %s: %s", tenant_id, e)

    logger.info("Stripe Connect verified for tenant %s account %s charges_enabled=%s",
                tenant_id, account_id, account["charges_enabled"])
    return {
        "charges_enabled":   account["charges_enabled"],
        "payouts_enabled":   account["payouts_enabled"],
        "details_submitted": account["details_submitted"],
    }


# ---------------------------------------------------------------------------
# GET /stripe-connect/status/{tenant_id}
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

    account_id = tenant.get("stripe_account_id")
    if not account_id:
        return {"connected": False, "charges_enabled": False}

    try:
        account = await svc.get_account(account_id)
    except Exception as e:
        logger.error("Stripe account fetch failed for %s: %s", account_id, e)
        return {"connected": True, "charges_enabled": False, "error": str(e)}

    return {
        "connected":        True,
        "account_id":       account["id"],
        "charges_enabled":  account["charges_enabled"],
        "payouts_enabled":  account["payouts_enabled"],
        "details_submitted": account["details_submitted"],
    }


# ---------------------------------------------------------------------------
# POST /stripe-connect/disconnect/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/disconnect/{tenant_id}")
async def connect_disconnect(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        await db.update_tenant(tenant_id, {
            "stripe_account_id":       None,
            "stripe_deposits_enabled": False,
        })
        if tenant:
            await vapi.patch_assistant_tools({**tenant, "stripe_account_id": None, "stripe_deposits_enabled": False})
    except Exception as e:
        logger.error("Stripe disconnect failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Disconnect failed")

    logger.info("Stripe Connect disconnected for tenant %s", tenant_id)
    return {"status": "disconnected"}
