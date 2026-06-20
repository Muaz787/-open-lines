import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from db import supabase as db
from services import zapier, telephony, knowledge
from services.security import verify_tenant_owner, validate_public_url, scan_for_injection

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


@router.get("/triggers/{event}/sample")
async def trigger_sample(
    event: str,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Sample payload for Zapier field-mapping. Zapier polls this when a Zap is
    being built and no live data exists yet. Returns a list (Zapier expects an
    array of trigger objects)."""
    tenant = await _tenant_from_api_key(x_api_key)
    if event not in zapier.EVENTS:
        raise HTTPException(status_code=404, detail="Unknown event")
    # Match the live emit() shape: flat fields + _event / _tenant_id.
    return [{**zapier.SAMPLES.get(event, {}), "_event": event, "_tenant_id": tenant["id"]}]


# ---------------------------------------------------------------------------
# Actions (Zapier -> Open Lines)
# ---------------------------------------------------------------------------

class SendSmsRequest(BaseModel):
    to: str
    message: str


@router.post("/actions/send-sms")
async def action_send_sms(
    body: SendSmsRequest,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Send an SMS from the tenant's business number."""
    tenant = await _tenant_from_api_key(x_api_key)
    to = body.to.strip()
    if not to or not body.message.strip():
        raise HTTPException(status_code=400, detail="'to' and 'message' are required")

    sid    = tenant.get("twilio_subaccount_sid", "")
    tok    = tenant.get("twilio_auth_token", "")
    from_n = tenant.get("twilio_phone_number", "")
    if not (sid and tok and from_n):
        raise HTTPException(status_code=400, detail="This account has no provisioned phone number")

    sent = await telephony.send_sms(
        subaccount_sid=sid, subaccount_token=tok,
        from_number=from_n, to_number=to, body=body.message,
    )
    if not sent:
        raise HTTPException(status_code=502, detail="SMS could not be sent")
    return {"status": "sent", "to": to}


class AddKnowledgeRequest(BaseModel):
    text: str


@router.post("/actions/add-knowledge")
async def action_add_knowledge(
    body: AddKnowledgeRequest,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Append text to the tenant's AI knowledge base (e.g. daily specials,
    price changes). Re-prompts the assistant after the change."""
    tenant = await _tenant_from_api_key(x_api_key)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")
    scan_for_injection(text, source="zapier add-knowledge")

    namespace = tenant.get("pinecone_namespace", "")
    if not namespace:
        raise HTTPException(status_code=400, detail="Knowledge base not initialised for this account")

    label = text[:60] + ("…" if len(text) > 60 else "")
    entry = await db.insert_kb_entry(tenant["id"], "text", label, preview=text[:200])
    vectors = await knowledge.embed_and_store(namespace, text, tenant["id"], source_id=entry["id"])

    try:
        from services.provisioning import rebuild_and_push_system_prompt
        await rebuild_and_push_system_prompt(tenant)
    except Exception as e:
        logger.warning("Zapier add-knowledge: reprompt failed for tenant %s (non-fatal): %s", tenant["id"], e)

    return {"status": "ok", "vectors_stored": vectors, "entry_id": entry.get("id")}


class UpsertLeadRequest(BaseModel):
    phone: str
    name: str | None = None
    status: str | None = None
    note: str | None = None


@router.post("/actions/upsert-lead")
async def action_upsert_lead(
    body: UpsertLeadRequest,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Create or update a lead by phone (e.g. from a web form)."""
    tenant = await _tenant_from_api_key(x_api_key)
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")

    existing = await db.get_lead_by_phone(tenant["id"], phone)
    data: dict = {}
    if body.name:
        data["name"] = body.name.strip()
    if body.status:
        data["status"] = body.status.strip()
    if body.note:
        data["metadata"] = {**((existing or {}).get("metadata") or {}), "zapier_note": body.note.strip()}

    if existing:
        lead = await db.update_lead(tenant["id"], existing["id"], data) if data else existing
        return {"status": "updated", "lead_id": existing["id"], "lead": lead}

    lead = await db.insert_lead(tenant["id"], {"phone": phone, "status": body.status or "new", **data})
    return {"status": "created", "lead_id": lead.get("id"), "lead": lead}


# ---------------------------------------------------------------------------
# Search (Zapier -> Open Lines)
# ---------------------------------------------------------------------------

@router.get("/leads")
async def search_lead_by_phone(
    phone: str,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
):
    """Find a lead by phone number. Returns an array (Zapier search shape)."""
    tenant = await _tenant_from_api_key(x_api_key)
    if not phone.strip():
        raise HTTPException(status_code=400, detail="phone is required")
    lead = await db.get_lead_by_phone(tenant["id"], phone.strip())
    return [lead] if lead else []


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
