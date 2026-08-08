import os
import hmac
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
    if not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key):
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

    # Track closure time so the retention purge can delete the account's data after
    # the retention window. Clearing it on re-activation cancels any pending purge.
    from datetime import datetime as _dt, timezone as _tz
    updates: dict = {"is_active": new_state, "closed_at": None if new_state else _dt.now(_tz.utc).isoformat()}

    try:
        updated = await db.update_tenant(tenant_id, updates)
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


@router.patch("/tenants/{tenant_id}/comp")
async def set_tenant_comp(tenant_id: str, body: dict, x_admin_key: str | None = Header(None)):
    """Comp a tenant (billing_exempt): line stays live with no trial expiry or
    subscription — without touching subscription_plan, so revenue metrics stay clean."""
    _check_admin_key(x_admin_key)
    exempt = bool(body.get("exempt"))
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        updated = await db.update_tenant(tenant_id, {"billing_exempt": exempt})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to set comp for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update tenant")
    logger.info("Tenant %s billing_exempt → %s", tenant_id, exempt)
    return {"id": updated["id"], "billing_exempt": updated.get("billing_exempt")}


@router.patch("/tenants/{tenant_id}/plan")
async def set_tenant_plan(tenant_id: str, body: dict, x_admin_key: str | None = Header(None)):
    """Manually set a tenant's plan (comp grant of plan-gated features). Refuses when
    the tenant has a real Stripe subscription — manage those in Stripe to avoid desync."""
    _check_admin_key(x_admin_key)
    plan = (body.get("plan") or "").strip().lower() or None
    if plan and plan not in ("starter", "pro", "business"):
        raise HTTPException(status_code=400, detail="Invalid plan (starter|pro|business, or empty to clear)")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if tenant.get("stripe_subscription_id"):
            raise HTTPException(status_code=400, detail="Tenant has a Stripe subscription — change it in Stripe, not here")
        updated = await db.update_tenant(tenant_id, {
            "subscription_plan": plan,
            "subscription_status": "active" if plan else None,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to set plan for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Failed to update tenant")
    logger.info("Tenant %s plan → %s (comp)", tenant_id, plan)
    return {"id": updated["id"], "subscription_plan": updated.get("subscription_plan"),
            "subscription_status": updated.get("subscription_status")}


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


@router.post("/reprompt-all")
async def reprompt_all(x_admin_key: str | None = Header(None), limit: int = 0):
    """Rebuild + push the system prompt for EVERY tenant with a Vapi assistant.

    Use to roll a shared-layer prompt change out to existing tenants immediately
    (they otherwise pick it up on their next KB/staff/settings change). Runs
    sequentially and is non-fatal per tenant. Pass ?limit=N to process only the
    first N (handy for a smoke test before the full run)."""
    _check_admin_key(x_admin_key)
    try:
        tenants = await db.get_all_tenants_for_reprompt()
    except Exception as e:
        logger.error("reprompt-all: tenant fetch failed: %s", e)
        raise HTTPException(status_code=500, detail="Tenant fetch failed")

    if limit and limit > 0:
        tenants = tenants[:limit]

    rebuilt, failed, errors = 0, 0, []
    for t in tenants:
        tid = t.get("id")
        try:
            await rebuild_and_push_system_prompt(t)
            rebuilt += 1
        except Exception as e:
            failed += 1
            errors.append({"tenant_id": tid, "error": str(e)[:200]})
            logger.warning("reprompt-all: rebuild failed for tenant %s: %s", tid, e)

    logger.info("reprompt-all: %d rebuilt, %d failed of %d", rebuilt, failed, len(tenants))
    return {"total": len(tenants), "rebuilt": rebuilt, "failed": failed, "errors": errors}


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


@router.post("/recrawl-stale-websites")
async def recrawl_stale_websites(x_admin_key: str | None = Header(None)):
    """Re-crawl the websites of tenants whose knowledge base is stale (>7 days),
    have auto-recrawl enabled, and are active/trialing. Budget-guarded: at most
    MAX_TENANTS_PER_RUN per call, skips tenants that keep failing. Intended to be
    hit by a daily Railway cron — the 7-day staleness check lives in the endpoint,
    so running it daily only crawls what's actually due."""
    _check_admin_key(x_admin_key)
    from services import recrawl

    try:
        due = await recrawl.find_stale_tenants(limit=recrawl.MAX_TENANTS_PER_RUN)
    except Exception as e:
        logger.error("recrawl-stale-websites: could not list tenants: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list tenants")

    summary = {"considered": len(due), "crawled": 0, "failed": 0, "results": []}
    for t in due:
        try:
            full = await db.get_tenant_by_id(t["id"])
            r = await recrawl.recrawl_tenant(full, source="scheduled")
            summary["crawled"] += 1
            summary["results"].append({
                "tenant_id": t["id"], "status": "success",
                "pages": r.get("pages_scraped"), "vectors": r.get("vectors_stored"),
            })
        except Exception:
            # recrawl_tenant already logged + recorded the sanitized error on the tenant.
            summary["failed"] += 1
            summary["results"].append({"tenant_id": t["id"], "status": "error"})

    logger.info("recrawl-stale-websites done: considered=%d crawled=%d failed=%d",
                summary["considered"], summary["crawled"], summary["failed"])
    return summary


@router.post("/send-trial-reminders")
async def send_trial_reminders(x_admin_key: str | None = Header(None)):
    """Send any due free-trial reminder emails (active / ending / ended), once each.
    Idempotent — deduped per tenant. Intended for a daily cron."""
    _check_admin_key(x_admin_key)
    from services import trial
    sent = await trial.process_trial_reminders()
    return {"sent": sent}


@router.get("/voice-config")
async def voice_config(
    tenant_id: str | None = None,
    phone: str | None = None,
    x_admin_key: str | None = Header(None),
):
    """Diagnose the Fish-Audio TTS canary. Pass ?tenant_id=<uuid> (or ?phone=<the
    number you called>) and read `voice_provider`: 'custom-voice' means the call
    WILL route through Fish; '11labs' means it falls back to ElevenLabs (tenant not
    in the canary list, or Fish env missing). If this endpoint 404s, the new code
    isn't deployed yet."""
    _check_admin_key(x_admin_key)
    from services import vapi as vapi_svc
    from routers import voice as voice_mod

    canary = [x.strip() for x in os.getenv("FISH_TTS_CANARY_TENANT_IDS", "").split(",") if x.strip()]
    out: dict = {
        "fish_api_key_set": bool(os.getenv("FISH_API_KEY")),
        "fish_reference_id_set": bool(os.getenv("FISH_VOICE_REFERENCE_ID")),
        "fish_model": os.getenv("FISH_TTS_MODEL", "") or "(default)",
        "vapi_server_secret_set": bool(os.getenv("VAPI_SERVER_SECRET")),
        "canary_tenant_ids": canary,
        # Last time Vapi actually called /voice/fish-tts (empty {} = never hit).
        "voice_endpoint_last_hit": voice_mod.LAST_HIT or None,
    }
    tid = tenant_id
    if not tid and phone:
        t = await db.get_tenant_by_phone(phone)
        tid = t and t.get("id")
        out["matched_tenant_id_for_phone"] = tid
    if tid:
        block = vapi_svc.build_voice_block({"id": tid})
        out["resolved_tenant_id"] = tid
        out["tenant_in_canary"] = tid in canary
        out["voice_provider"] = block.get("provider")  # 'custom-voice' => Fish active
    return out


@router.post("/patch-fish-voice")
async def patch_fish_voice(x_admin_key: str | None = Header(None)):
    """Persistently set the Fish custom-voice on each canaried tenant's Vapi
    assistant. Vapi ignores a custom-voice provider in per-call overrides, so it
    must live on the assistant itself. Run once after setting the canary env var;
    the per-call override deliberately skips voice for canaried tenants so this
    assistant-level voice is the one that applies."""
    _check_admin_key(x_admin_key)
    from services import vapi as vapi_svc

    ids = [x.strip() for x in os.getenv("FISH_TTS_CANARY_TENANT_IDS", "").split(",") if x.strip()]
    if not ids:
        return {"patched": [], "note": "FISH_TTS_CANARY_TENANT_IDS is empty"}
    results = []
    for tid in ids:
        try:
            t = await db.get_tenant_by_id(tid)
            if not t:
                results.append({"tenant_id": tid, "status": "tenant_not_found"})
                continue
            aid = t.get("vapi_assistant_id")
            if not aid:
                results.append({"tenant_id": tid, "status": "no_assistant_id",
                                "tenant_keys": sorted(t.keys())})
                continue
            block = vapi_svc.build_voice_block(t)
            key = vapi_svc.get_tenant_vapi_key(t)
            ok = await vapi_svc.update_assistant(aid, {"voice": block}, api_key=key)
            results.append({"tenant_id": tid, "assistant_id": aid,
                            "patched": ok, "voice_provider": block.get("provider")})
        except Exception as e:
            logger.exception("patch-fish-voice failed for %s", tid)
            results.append({"tenant_id": tid, "status": "error",
                            "error": f"{type(e).__name__}: {str(e)[:200]}"})
    return {"patched": results}


@router.post("/test-fish-tts")
async def test_fish_tts(x_admin_key: str | None = Header(None)):
    """Call Fish Audio /v1/tts directly with a sample line and report exactly what it
    says — the fastest way to see if the model/reference_id/format are accepted. If
    this returns ok=true with audio_bytes>0 but real calls still fall back, the issue
    is Vapi not honoring the custom-voice override (not Fish)."""
    _check_admin_key(x_admin_key)
    import httpx
    api_key = os.getenv("FISH_API_KEY", "")
    ref = os.getenv("FISH_VOICE_REFERENCE_ID", "")
    model = os.getenv("FISH_TTS_MODEL", "").strip()
    if not api_key or not ref:
        return {"ok": False, "error": "FISH_API_KEY or FISH_VOICE_REFERENCE_ID not set"}
    headers = {"Authorization": f"Bearer {api_key}"}
    if model:
        headers["model"] = model
    payload = {
        "text": "Thursday at 2:30 is open. I'll text you a confirmation.",
        "reference_id": ref,
        "format": "pcm",
        "sample_rate": 8000,
        "latency": "balanced",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post("https://api.fish.audio/v1/tts", headers=headers, json=payload)
    except Exception as e:
        return {"ok": False, "error": f"connect: {str(e)[:300]}"}
    ok = r.status_code == 200
    return {
        "ok": ok,
        "status": r.status_code,
        "model_sent": model or "(default)",
        "reference_id_len": len(ref),
        "audio_bytes": len(r.content) if ok else 0,
        "error": "" if ok else r.text[:500],
    }


@router.post("/check-minutes-alert")
async def check_minutes_alert(x_admin_key: str | None = Header(None)):
    """Run the platform call-minutes threshold check now — the Vapi-migration nudge.
    Emails the founder at most once per threshold (deduped via system_meta); returns
    the current total, threshold, and whether it fired. Also runs daily via the cron."""
    _check_admin_key(x_admin_key)
    from services import usage
    return await usage.check_platform_minutes_alert()


@router.post("/purge-retention")
async def purge_retention(x_admin_key: str | None = Header(None)):
    """Run the data-retention purge: delete aged raw webhook payloads and fully
    delete tenants closed past the retention window. Intended for the daily cron;
    safe to run repeatedly."""
    _check_admin_key(x_admin_key)
    from services import retention
    return await retention.run_retention()


@router.post("/reconcile-transfer-durations")
async def reconcile_transfer_durations(x_admin_key: str | None = Header(None)):
    """Backfill transfer_attempts.duration_secs from the Twilio operator-leg
    (post-hand-off talk-time, which isn't in Vapi's meter). VISIBILITY only — this is
    never fed into usage/billing. Idempotent: only fills rows still missing a
    duration, and re-runs safely (a still-live leg is left for the next run).
    Intended for the daily cron."""
    _check_admin_key(x_admin_key)
    from services import transfer_reconcile
    return await transfer_reconcile.reconcile_pending()


@router.post("/tenants/{tenant_id}/delete-data")
async def delete_tenant_data_endpoint(
    tenant_id: str,
    drop_tenant: bool = True,
    x_admin_key: str | None = Header(None),
):
    """Permanently delete ALL of a tenant's data (offboarding / data-deletion
    request). Irreversible. Set drop_tenant=false to wipe data but keep the row."""
    _check_admin_key(x_admin_key)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found (check the tenant_id is a valid UUID)")
    from services import retention
    result = await retention.delete_tenant_data(tenant_id, drop_tenant=drop_tenant)
    logger.info("ADMIN: deleted tenant data for %s (drop_tenant=%s)", tenant_id, drop_tenant)
    status = "partial_error" if result.get("errors") else "deleted"
    return {"status": status, "tenant_id": tenant_id, **result}


@router.post("/delete-caller")
async def delete_caller_endpoint(body: dict, x_admin_key: str | None = Header(None)):
    """Delete one caller's records for a tenant (individual deletion request).
    Body: {"tenant_id": "...", "phone": "+1..."}. Irreversible."""
    _check_admin_key(x_admin_key)
    tenant_id = (body or {}).get("tenant_id", "")
    phone     = (body or {}).get("phone", "")
    if not tenant_id or not phone:
        raise HTTPException(status_code=400, detail="tenant_id and phone are required")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found (check the tenant_id is a valid UUID)")
    from services import retention
    result = await retention.delete_caller_data(tenant_id, phone)
    status = "partial_error" if result.get("errors") else "deleted"
    return {"status": status, **result}


@router.post("/backfill-call-intents")
async def backfill_call_intents(body: dict | None = None, x_admin_key: str | None = Header(None)):
    """One-time/repeatable enrichment of existing calls for AI Insights v2.
    Classifies intent + signals for calls that don't have them yet. Batched —
    re-run until `considered` < `limit`. Body: {"tenant_id"?: str, "limit"?: int}."""
    _check_admin_key(x_admin_key)
    body = body or {}
    from services import call_enrichment
    result = await call_enrichment.backfill_missing_intents(
        limit=int(body.get("limit", 200)),
        tenant_id=body.get("tenant_id"),
    )
    return {**result, "note": "re-run while considered == limit to finish the backlog"}


# ---------------------------------------------------------------------------
# GET /admin/health — service health for the admin System Health page
# ---------------------------------------------------------------------------
@router.get("/health")
async def system_health(x_admin_key: str | None = Header(None)):
    """Live health of backend dependencies (env + lightweight pings). Each check
    is isolated so one slow/failing service can't break the page."""
    _check_admin_key(x_admin_key)
    import httpx
    import asyncio
    from datetime import datetime, timezone

    def _env(name: str, keys: list[str]) -> tuple:
        missing = [k for k in keys if not os.getenv(k)]
        return (name, "error" if missing else "ok",
                ("Not configured: " + ", ".join(missing)) if missing else "Configured")

    async def _ping(name: str, url: str, *, headers=None, auth=None, ok_codes=(200,)) -> tuple:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(url, headers=headers, auth=auth)
            if r.status_code in ok_codes:
                return (name, "ok", "Connected")
            if r.status_code in (401, 403):
                return (name, "error", f"Auth failed (HTTP {r.status_code}) — check key")
            return (name, "warning", f"HTTP {r.status_code}")
        except Exception as e:
            return (name, "error", f"Unreachable: {str(e)[:60]}")

    async def _chk_supabase() -> tuple:
        try:
            db.get_client().table("tenants").select("id").limit(1).execute()
            return ("Supabase", "ok", "Connected")
        except Exception as e:
            return ("Supabase", "error", str(e)[:80])

    async def _chk_twilio() -> tuple:
        sid, tok = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
        if not (sid and tok):
            return ("Twilio", "error", "Not configured")
        return await _ping("Twilio", f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", auth=(sid, tok))

    async def _chk_stripe() -> tuple:
        key = os.getenv("STRIPE_SECRET_KEY")
        if not key:
            return ("Stripe", "error", "Not configured")
        return await _ping("Stripe", "https://api.stripe.com/v1/balance", headers={"Authorization": f"Bearer {key}"})

    async def _chk_resend() -> tuple:
        key = os.getenv("RESEND_API_KEY")
        if not key:
            return ("Resend", "error", "Not configured")
        return await _ping("Resend", "https://api.resend.com/domains", headers={"Authorization": f"Bearer {key}"})

    async def _chk_pinecone() -> tuple:
        key = os.getenv("PINECONE_API_KEY")
        if not key:
            return ("Pinecone", "error", "Not configured")
        return await _ping("Pinecone", "https://api.pinecone.io/indexes",
                           headers={"Api-Key": key, "X-Pinecone-API-Version": "2024-07"})

    async def _chk_crawl() -> tuple:
        try:
            res = (db.get_client().table("tenants")
                   .select("last_crawl_at").not_.is_("last_crawl_at", "null")
                   .order("last_crawl_at", desc=True).limit(1).execute())
            rows = res.data or []
            if not rows:
                return ("Website crawl", "warning", "No crawls recorded yet")
            last = datetime.fromisoformat(str(rows[0]["last_crawl_at"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_d = (datetime.now(timezone.utc) - last).total_seconds() / 86400
            status = "ok" if age_d <= 8 else "warning"
            return ("Website crawl", status, f"Last successful crawl {int(age_d * 24)}h ago")
        except Exception as e:
            return ("Website crawl", "warning", str(e)[:60])

    async def _chk_cron() -> tuple:
        try:
            meta = await db.get_system_meta("cron_last_run")
            if not meta or not meta.get("value"):
                return ("Daily cron", "error", "No heartbeat — cron may not be scheduled")
            last = datetime.fromisoformat(str(meta["value"]).replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if age_h <= 26:
                return ("Daily cron", "ok", f"Ran {int(age_h)}h ago")
            return ("Daily cron", "error", f"Stale — last ran {int(age_h)}h ago")
        except Exception as e:
            return ("Daily cron", "warning", str(e)[:60])

    def _chk_whatsapp() -> tuple:
        frm = os.getenv("TWILIO_WHATSAPP_FROM")
        tmpls = {
            "summary": os.getenv("TWILIO_WHATSAPP_SUMMARY_TEMPLATE_SID"),
            "deposit": os.getenv("TWILIO_WHATSAPP_DEPOSIT_TEMPLATE_SID"),
            "cancel":  os.getenv("TWILIO_WHATSAPP_CANCEL_TEMPLATE_SID"),
        }
        if not frm:
            return ("WhatsApp", "warning", "Sender not configured (notifications off)")
        have = [k for k, v in tmpls.items() if v]
        if len(have) == 3:
            return ("WhatsApp", "ok", "Sender + 3 templates configured")
        return ("WhatsApp", "warning", f"Sender set; templates ready: {', '.join(have) or 'none'} (pending approval)")

    async def _chk_mistral() -> tuple:
        # OCR is optional (scanned-doc KB parsing) — unset is a warning, not an error.
        key = os.getenv("MISTRAL_API_KEY")
        if not key:
            return ("Mistral OCR", "warning", "Not configured — scanned-doc OCR disabled")
        return await _ping("Mistral OCR", "https://api.mistral.ai/v1/models",
                           headers={"Authorization": f"Bearer {key}"})

    pinged = await asyncio.gather(
        _chk_supabase(), _chk_twilio(), _chk_stripe(), _chk_resend(),
        _chk_pinecone(), _chk_crawl(), _chk_cron(), _chk_mistral(),
    )
    checks = [{"name": n, "status": s, "message": m} for (n, s, m) in pinged]
    for n, s, m in [
        _env("OpenAI", ["OPENAI_API_KEY"]),
        _env("Vapi", ["VAPI_API_KEY"]),
        _env("Square", ["SQUARE_APP_ID", "SQUARE_APP_SECRET"]),
        _env("Firecrawl", ["FIRECRAWL_API_KEY"]),
        _chk_whatsapp(),
    ]:
        checks.append({"name": n, "status": s, "message": m})

    return {"checks": checks, "generated_at": datetime.now(timezone.utc).isoformat()}
