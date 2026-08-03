"""
Owner APIs for AI Overflow Handling & AI Call Routing (Phase 1 configuration).

DARK by default: every route requires the tenant to be entitled — which needs the
ROUTING_ENABLED master flag AND per-tenant routing_enabled (services/entitlements).
Until we turn it on (our own OpenLines tenant first), all routes 403.

Auth: router-level require_tenant_owner (bearer token must own the {tenant_id}).
Server-side enforcement here (never trust the client): entitlement gate, per-plan
destination/rule LIMITS, destination number validation + encryption/masking,
forwarding-loop guard, duplicate guard, and tenant-scoped queries.

Activation (flipping per-tenant routing_enabled) is an ADMIN action, kept separate
so a tenant can't self-enable a feature we haven't rolled out to them.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator

from db import routing as rdb
from db import supabase as db
from services import entitlements
from services import routing_destinations as rd
from services import routing_engine
from services.security import require_tenant_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routing", tags=["routing"], dependencies=[Depends(require_tenant_owner)])
admin_router = APIRouter(prefix="/routing-admin", tags=["routing-admin"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
async def _entitled(tenant_id: str, feature: str = "routing") -> dict:
    """Fetch the tenant and require the capability. 404 if unknown, 403 if the
    plan/flags don't grant it."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        entitlements.require(tenant, feature)
    except entitlements.EntitlementError:
        raise HTTPException(status_code=403, detail="This feature isn't available on your plan yet")
    return tenant


def _public_destination(row: dict | None) -> dict | None:
    """Owner-facing destination view: MASKED only — never the encrypted value or hash."""
    if not row:
        return None
    return {
        "id": row.get("id"), "type": row.get("type"), "label": row.get("label"),
        "number_masked": row.get("e164_masked"), "enabled": row.get("enabled", True),
        "verified_at": row.get("verified_at"), "created_at": row.get("created_at"),
    }


def _check_admin_key(x_admin_key: str | None) -> None:
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key or not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------
class ProfileUpdate(BaseModel):
    phone_number: str | None = None
    mode: str | None = None
    overflow_enabled: bool | None = None
    after_hours_behavior: str | None = None
    default_destination_id: str | None = None
    urgent_destination_id: str | None = None
    default_fallback_action: str | None = None
    low_confidence_action: str | None = None
    confidence_threshold: float | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v):
        if v is not None and v not in ("ai_first", "ai_overflow", "ai_first_routing"):
            raise ValueError("mode must be ai_first | ai_overflow | ai_first_routing")
        return v


class DestinationCreate(BaseModel):
    number: str
    type: str = "phone"
    label: str | None = None


class DestinationUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class RuleCreate(BaseModel):
    profile_id: str
    priority: int = 100
    enabled: bool = True
    match: dict = {}
    destination_id: str | None = None
    fallback_destination_id: str | None = None


class RuleUpdate(BaseModel):
    priority: int | None = None
    enabled: bool | None = None
    match: dict | None = None
    destination_id: str | None = None
    fallback_destination_id: str | None = None


class SimulateRequest(BaseModel):
    intent: str | None = None
    urgency: str | None = None
    requested_person: str | None = None
    is_returning: bool = False
    language: str | None = None
    confidence: float | None = None
    text: str | None = None


# ---------------------------------------------------------------------------
# call-handling profile
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}/profile")
async def get_profile(tenant_id: str):
    await _entitled(tenant_id)
    prof = await rdb.get_profile(tenant_id)
    return prof or {"tenant_id": tenant_id, "mode": "ai_first", "overflow_enabled": False,
                    "default_fallback_action": "callback"}


@router.put("/{tenant_id}/profile")
async def put_profile(tenant_id: str, body: ProfileUpdate):
    await _entitled(tenant_id)
    data = body.model_dump(exclude_unset=True)
    existing = await rdb.get_profile(tenant_id)
    if existing:
        return await rdb.update_profile(tenant_id, existing["id"], data)
    return await rdb.create_profile(tenant_id, data)


# ---------------------------------------------------------------------------
# destinations
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}/destinations")
async def list_destinations(tenant_id: str):
    await _entitled(tenant_id)
    rows = await rdb.list_destinations(tenant_id)
    return {"destinations": [_public_destination(r) for r in rows]}


@router.post("/{tenant_id}/destinations")
async def create_destination(tenant_id: str, body: DestinationCreate):
    tenant = await _entitled(tenant_id)

    # per-plan limit (count active destinations)
    active = [d for d in await rdb.list_destinations(tenant_id) if d.get("enabled", True)]
    if len(active) >= entitlements.limit_for(tenant, "max_destinations"):
        raise HTTPException(status_code=403, detail="Destination limit reached for your plan")

    ok, reason = rd.validate_destination_number(body.number)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Invalid destination number ({reason})")

    # forwarding-loop guard: never transfer to this tenant's own OpenLines line
    own = tenant.get("twilio_phone_number")
    if own and rd.is_same_number(body.number, rd.keyed_hash(own)):
        raise HTTPException(status_code=400, detail="Cannot use this line itself as a destination (loop)")

    secure = rd.secure_fields(body.number)   # encrypt + mask + keyed hash
    if await rdb.find_destination_by_hash(tenant_id, secure["e164_hash"]):
        raise HTTPException(status_code=409, detail="This destination already exists")

    row = await rdb.create_destination(tenant_id, {"type": body.type, "label": body.label, **secure})
    return _public_destination(row)


@router.patch("/{tenant_id}/destinations/{destination_id}")
async def update_destination(tenant_id: str, destination_id: str, body: DestinationUpdate):
    await _entitled(tenant_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    row = await rdb.update_destination(tenant_id, destination_id, data)
    return _public_destination(row)


@router.delete("/{tenant_id}/destinations/{destination_id}")
async def delete_destination(tenant_id: str, destination_id: str):
    """Soft-disable (preserves audit + references, which SET NULL on hard delete)."""
    await _entitled(tenant_id)
    await rdb.update_destination(tenant_id, destination_id, {"enabled": False})
    return {"status": "disabled"}


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}/rules")
async def list_rules(tenant_id: str, profile_id: str):
    await _entitled(tenant_id)
    return {"rules": await rdb.list_rules(tenant_id, profile_id)}


@router.post("/{tenant_id}/rules")
async def create_rule(tenant_id: str, body: RuleCreate):
    tenant = await _entitled(tenant_id)
    if await rdb.count_rules(tenant_id, body.profile_id) >= entitlements.limit_for(tenant, "max_routing_rules"):
        raise HTTPException(status_code=403, detail="Routing-rule limit reached for your plan")
    if body.destination_id and not await rdb.get_destination(tenant_id, body.destination_id):
        raise HTTPException(status_code=400, detail="destination_id does not belong to this tenant")
    return await rdb.create_rule(tenant_id, body.model_dump(exclude_unset=True))


@router.patch("/{tenant_id}/rules/{rule_id}")
async def update_rule(tenant_id: str, rule_id: str, body: RuleUpdate):
    await _entitled(tenant_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    return await rdb.update_rule(tenant_id, rule_id, data)


@router.delete("/{tenant_id}/rules/{rule_id}")
async def delete_rule(tenant_id: str, rule_id: str):
    await _entitled(tenant_id)
    await rdb.delete_rule(tenant_id, rule_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# simulate (dry-run a caller intent through the deterministic engine; no call)
# ---------------------------------------------------------------------------
@router.post("/{tenant_id}/simulate")
async def simulate(tenant_id: str, body: SimulateRequest):
    await _entitled(tenant_id)
    prof = await rdb.get_profile(tenant_id) or {}
    rules = await rdb.list_rules(tenant_id, prof["id"]) if prof.get("id") else []
    dests = {d["id"]: {"type": d.get("type"), "enabled": d.get("enabled", True)}
             for d in await rdb.list_destinations(tenant_id)}
    decision = routing_engine.evaluate(prof, rules, dests, body.model_dump()).as_dict()
    if decision.get("destination_id"):
        decision["destination"] = _public_destination(await rdb.get_destination(tenant_id, decision["destination_id"]))
    return decision


# ---------------------------------------------------------------------------
# read: transfer attempts + callbacks
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}/transfers")
async def list_transfers(tenant_id: str, call_id: str | None = None):
    await _entitled(tenant_id)
    return {"transfers": await rdb.list_transfer_attempts(tenant_id, call_id)}


@router.get("/{tenant_id}/callbacks")
async def list_callbacks(tenant_id: str, status: str = "open"):
    await _entitled(tenant_id)
    return {"callbacks": await rdb.list_callbacks(tenant_id, status)}


# ---------------------------------------------------------------------------
# admin: per-tenant activation (dark-launch control) — admin-key gated
# ---------------------------------------------------------------------------
@admin_router.post("/{tenant_id}/enable")
async def admin_enable(tenant_id: str, x_admin_key: Annotated[str | None, Header()] = None):
    _check_admin_key(x_admin_key)
    await rdb.set_routing_enabled(tenant_id, True)
    logger.info("routing enabled for tenant %s", tenant_id)
    return {"tenant_id": tenant_id, "routing_enabled": True}


@admin_router.post("/{tenant_id}/disable")
async def admin_disable(tenant_id: str, x_admin_key: Annotated[str | None, Header()] = None):
    _check_admin_key(x_admin_key)
    await rdb.set_routing_enabled(tenant_id, False)
    logger.info("routing disabled for tenant %s", tenant_id)
    return {"tenant_id": tenant_id, "routing_enabled": False}


@admin_router.post("/{tenant_id}/sync-assistant")
async def admin_sync_assistant(tenant_id: str, x_admin_key: Annotated[str | None, Header()] = None):
    """Re-patch the tenant's Vapi assistant so the routing tools + serverMessages
    (transfer-destination-request / end-of-call-report) are attached. Run after
    enabling routing for a tenant. Admin-key gated."""
    _check_admin_key(x_admin_key)
    tenant = await db.get_tenant_by_id(tenant_id)
    if not tenant or not tenant.get("vapi_assistant_id"):
        raise HTTPException(status_code=404, detail="Tenant or assistant not found")
    from services import vapi as vapi_svc
    await vapi_svc.patch_assistant_tools(tenant)
    return {"tenant_id": tenant_id, "status": "assistant synced"}
