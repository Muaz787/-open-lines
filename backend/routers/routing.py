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

import httpx
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
async def _entitled(tenant_id: str) -> dict:
    """Fetch the tenant and require CONFIG access — PLAN-gated (Pro/Business + master
    switch), independent of whether routing is switched on. 404 if unknown, 403 if the
    plan doesn't grant it (Starter/free -> dashboard shows the locked card).

    NOTE: this gates the config surface only. It does NOT mean routing is active on the
    tenant's calls — that requires the tenant to opt in via /activate (which sets
    tenants.routing_enabled). The runtime (assistant tools, transfer webhook, mid-call
    tools) stays gated on that opt-in via entitlements.has_feature()."""
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not entitlements.can_configure(tenant):
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
        # Nothing to change (e.g. an "ensure a profile exists" call): return the
        # existing profile as-is. An empty UPDATE returns no row, which previously
        # blanked the client's state and left rules without a profile_id.
        if not data:
            return existing
        return await rdb.update_profile(tenant_id, existing["id"], data)
    return await rdb.create_profile(tenant_id, data)


# ---------------------------------------------------------------------------
# activation status + self-serve on/off (plan-gated config surface; opt-in changes calls)
# ---------------------------------------------------------------------------
@router.get("/{tenant_id}/status")
async def get_status(tenant_id: str):
    """Config-surface status for the owner UI: whether routing is ACTIVE on this
    tenant's calls (opt-in), the plan tier + limits, and whether the tenant has enough
    config to switch on. Plan-gated like the rest of the config surface."""
    tenant = await _entitled(tenant_id)
    caps = entitlements.config_caps(tenant)
    active_dests = [d for d in await rdb.list_destinations(tenant_id) if d.get("enabled", True)]
    return {
        "routing_active": entitlements.has_feature(tenant, "routing"),
        "transfers_available": entitlements.transfer_execution_enabled(),
        "tier": caps.get("tier"),
        "max_destinations": caps.get("max_destinations", 0),
        "max_routing_rules": caps.get("max_routing_rules", 0),
        "active_destination_count": len(active_dests),
        "can_activate": len(active_dests) >= 1,
    }


async def _sync_assistant_soft(tenant_id: str) -> bool:
    """Re-patch the tenant's assistant after an activation change. Best-effort: the
    per-call override also attaches tools + serverMessages, so a provider hiccup here
    doesn't lose the activation. Returns True if the sync succeeded."""
    fresh = await db.get_tenant_by_id(tenant_id)
    from services import vapi as vapi_svc
    try:
        await vapi_svc.patch_assistant_tools(fresh)
        return True
    except httpx.HTTPStatusError as e:
        logger.error("routing activation sync failed for tenant %s: %s %s",
                     tenant_id, e.response.status_code, vapi_svc.redact_provider_error(e.response.text))
    except httpx.RequestError as e:
        logger.error("routing activation sync network error for tenant %s: %s", tenant_id, e)
    return False


@router.post("/{tenant_id}/activate")
async def activate_routing(tenant_id: str):
    """Owner self-serve: turn routing ON for this tenant's calls. Requires at least one
    ENABLED destination (otherwise routing has nowhere to send callers). Sets
    routing_enabled and re-syncs the assistant so the routing tools + serverMessages
    attach. Idempotent."""
    await _entitled(tenant_id)
    active_dests = [d for d in await rdb.list_destinations(tenant_id) if d.get("enabled", True)]
    if not active_dests:
        raise HTTPException(status_code=400,
                            detail="Add at least one destination before turning routing on")
    await rdb.set_routing_enabled(tenant_id, True)
    synced = await _sync_assistant_soft(tenant_id)
    logger.info("routing ACTIVATED (self-serve) for tenant %s (assistant_synced=%s)", tenant_id, synced)
    return {"routing_active": True, "assistant_synced": synced}


@router.post("/{tenant_id}/deactivate")
async def deactivate_routing(tenant_id: str):
    """Owner self-serve: turn routing OFF for this tenant's calls. Clears
    routing_enabled and re-syncs the assistant so the routing tools drop. Destinations
    and rules are preserved for when they turn it back on. Idempotent."""
    await _entitled(tenant_id)
    await rdb.set_routing_enabled(tenant_id, False)
    synced = await _sync_assistant_soft(tenant_id)
    logger.info("routing DEACTIVATED (self-serve) for tenant %s (assistant_synced=%s)", tenant_id, synced)
    return {"routing_active": False, "assistant_synced": synced}


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

    # Validate the INPUT first so a bad number returns a specific error (invalid /
    # loop / duplicate) even when the tenant is already at their plan limit — the
    # per-plan cap is checked LAST and only blocks otherwise-valid new additions.
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

    # per-plan limit (count active destinations) — last, for valid & unique numbers
    active = [d for d in await rdb.list_destinations(tenant_id) if d.get("enabled", True)]
    if len(active) >= entitlements.config_limit_for(tenant, "max_destinations"):
        raise HTTPException(status_code=403, detail="Destination limit reached for your plan")

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
    if await rdb.count_rules(tenant_id, body.profile_id) >= entitlements.config_limit_for(tenant, "max_routing_rules"):
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
    try:
        await vapi_svc.patch_assistant_tools(tenant)
    except httpx.HTTPStatusError as e:
        # The voice provider rejected the assistant update (e.g. a schema-invalid
        # field -> 400). Log the provider status + a SANITIZED, length-limited body
        # (credentials/auth tokens and phone numbers scrubbed, payload capped) and
        # surface a controlled 502 — never leak the raw upstream response, an auth
        # header, a caller number, or fall through to an opaque 500.
        logger.error(
            "sync-assistant: Vapi rejected assistant update for tenant %s: %s %s",
            tenant_id, e.response.status_code, vapi_svc.redact_provider_error(e.response.text),
        )
        raise HTTPException(
            status_code=502,
            detail="Voice provider rejected the assistant update",
        ) from e
    except httpx.RequestError as e:
        logger.error("sync-assistant: network error reaching Vapi for tenant %s: %s", tenant_id, e)
        raise HTTPException(
            status_code=502,
            detail="Could not reach the voice provider",
        ) from e
    return {"tenant_id": tenant_id, "status": "assistant synced"}
