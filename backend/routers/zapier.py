import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from db import supabase as db
from services import zapier
from services.security import verify_tenant_owner, validate_public_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/zapier", tags=["zapier"])


# ---------------------------------------------------------------------------
# API-key auth (Zapier connection)
# ---------------------------------------------------------------------------

async def _tenant_from_api_key(x_api_key: str | None) -> dict:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    tenant = await db.get_tenant_by_api_key_hash(zapier.hash_api_key(x_api_key.strip()))
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")
    return tenant


@router.get("/me")
async def me(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None):
    """Zapier connection test + label. Authenticated by API key."""
    tenant = await _tenant_from_api_key(x_api_key)
    return {"tenant_id": tenant["id"], "business_name": tenant.get("business_name", "")}


class SubscribeRequest(BaseModel):
    event: str
    target_url: str


@router.post("/subscribe")
async def subscribe(
    body: SubscribeRequest,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Zapier registers a REST Hook target URL for an event."""
    tenant = await _tenant_from_api_key(x_api_key)
    if body.event not in zapier.EVENTS:
        raise HTTPException(status_code=400, detail=f"Unknown event. Supported: {', '.join(zapier.EVENTS)}")
    validate_public_url(body.target_url)
    sub = await db.insert_zapier_subscription(tenant["id"], body.event, body.target_url.strip())
    return {"id": sub.get("id")}


@router.delete("/subscribe/{subscription_id}")
async def unsubscribe(
    subscription_id: str,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    tenant = await _tenant_from_api_key(x_api_key)
    await db.delete_zapier_subscription(tenant["id"], subscription_id)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# API-key management (owner-authenticated via Supabase JWT)
# ---------------------------------------------------------------------------

class CreateKeyRequest(BaseModel):
    label: str | None = None


@router.post("/keys/{tenant_id}")
async def create_key(
    tenant_id: str,
    body: CreateKeyRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    raw, key_hash, prefix = zapier.generate_api_key()
    row = await db.insert_api_key(tenant_id, key_hash, prefix, body.label)
    # Raw key returned exactly once — never retrievable again.
    return {"id": row.get("id"), "api_key": raw, "key_prefix": prefix, "label": body.label}


@router.get("/keys/{tenant_id}")
async def list_keys(
    tenant_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    return {"keys": await db.get_api_keys(tenant_id)}


@router.delete("/keys/{tenant_id}/{key_id}")
async def revoke_key(
    tenant_id: str,
    key_id: str,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    ok = await db.revoke_api_key(tenant_id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked"}
