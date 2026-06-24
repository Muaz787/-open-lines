"""
Data retention + deletion (PIPEDA: limit retention; access/deletion requests).

Three mechanisms:
  1. purge_old_webhook_events — delete raw Vapi payloads (transcripts/numbers) once
     they're past WEBHOOK_EVENT_RETENTION_DAYS. They're only needed transiently for
     processing/diagnostics. Lowest-risk minimization win; runs daily.
  2. purge_closed_accounts — fully delete a tenant's data CLOSED_ACCOUNT_RETENTION_DAYS
     after the account was closed (is_active=false + closed_at). Inert until an account
     has actually been closed that long.
  3. delete_tenant_data / delete_caller_data — on-demand deletion for offboarding and
     individual access/deletion requests, exposed via admin endpoints.

Note: this deletes Open Lines' own copies. Recordings/transcripts also held by Vapi
(our processor) age out under their retention / contract; per-call deletion from Vapi
is a documented follow-up.
"""
import os
import logging
from datetime import datetime, timezone, timedelta

from db import supabase as db

logger = logging.getLogger(__name__)

WEBHOOK_EVENT_RETENTION_DAYS  = int(os.getenv("WEBHOOK_EVENT_RETENTION_DAYS", "90"))
CLOSED_ACCOUNT_RETENTION_DAYS = int(os.getenv("CLOSED_ACCOUNT_RETENTION_DAYS", "365"))

# Tenant-scoped tables holding personal information, cleared on full deletion.
# Each delete is best-effort so a table that doesn't exist in a given deployment
# (or a renamed column) logs a warning instead of aborting the whole purge.
_TENANT_PII_TABLES = [
    "calls", "appointments", "payments", "payment_short_links",
    "kb_entries", "zapier_subscriptions", "stripe_webhook_events", "leads",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def delete_tenant_data(tenant_id: str, drop_tenant: bool = True) -> dict:
    """Delete all of a tenant's personal information: every tenant-scoped table,
    the Pinecone namespace, and (optionally) the tenant row itself."""
    client = db.get_client()
    deleted: dict[str, int] = {}

    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception:
        tenant = None
    namespace = (tenant or {}).get("pinecone_namespace")

    if namespace:
        try:
            from services import knowledge
            knowledge.clear_namespace(namespace)
            deleted["pinecone_namespace"] = 1
        except Exception as e:
            logger.warning("retention: pinecone clear failed for %s: %s", tenant_id, e)

    for table in _TENANT_PII_TABLES:
        try:
            res = client.table(table).delete().eq("tenant_id", tenant_id).execute()
            deleted[table] = len(res.data or [])
        except Exception as e:
            logger.warning("retention: delete from %s failed for tenant %s: %s", table, tenant_id, e)

    if drop_tenant:
        try:
            client.table("tenants").delete().eq("id", tenant_id).execute()
            deleted["tenant"] = 1
        except Exception as e:
            logger.error("retention: tenant row delete failed for %s: %s", tenant_id, e)

    logger.info("retention: deleted tenant data for %s: %s", tenant_id, deleted)
    return deleted


async def delete_caller_data(tenant_id: str, phone: str) -> dict:
    """Delete a single caller's records for a tenant (individual deletion request).
    Deleting the caller's leads cascades to their calls; appointments/payments are
    matched by caller_phone."""
    if not phone:
        raise ValueError("phone is required")
    client = db.get_client()
    counts: dict[str, int] = {}

    for table, col in (("appointments", "caller_phone"), ("payments", "caller_phone"), ("leads", "phone")):
        try:
            res = client.table(table).delete().eq("tenant_id", tenant_id).eq(col, phone).execute()
            counts[table] = len(res.data or [])
        except Exception as e:
            logger.warning("retention: delete caller from %s failed (%s): %s", table, tenant_id, e)

    logger.info("retention: deleted caller %s for tenant %s: %s", phone[-4:].rjust(len(phone), "*"), tenant_id, counts)
    return counts


async def purge_old_webhook_events() -> int:
    cutoff = (_now() - timedelta(days=WEBHOOK_EVENT_RETENTION_DAYS)).isoformat()
    try:
        res = db.get_client().table("webhook_events").delete().lt("created_at", cutoff).execute()
        n = len(res.data or [])
        logger.info("retention: purged %d webhook_events older than %dd", n, WEBHOOK_EVENT_RETENTION_DAYS)
        return n
    except Exception as e:
        logger.error("retention: webhook_events purge failed: %s", e)
        return 0


async def purge_closed_accounts() -> list[str]:
    """Fully delete tenants closed longer than CLOSED_ACCOUNT_RETENTION_DAYS ago.
    Only touches accounts with a recorded closed_at, so it never deletes active ones."""
    cutoff = (_now() - timedelta(days=CLOSED_ACCOUNT_RETENTION_DAYS)).isoformat()
    try:
        res = (
            db.get_client().table("tenants")
            .select("id, business_name, closed_at")
            .eq("is_active", False)
            .lt("closed_at", cutoff)
            .execute()
        )
        due = res.data or []
    except Exception as e:
        logger.error("retention: closed-account lookup failed: %s", e)
        return []

    purged: list[str] = []
    for t in due:
        try:
            await delete_tenant_data(t["id"], drop_tenant=True)
            purged.append(t["id"])
        except Exception as e:
            logger.error("retention: purge of closed tenant %s failed: %s", t.get("id"), e)
    if purged:
        logger.info("retention: purged %d closed accounts (>%dd)", len(purged), CLOSED_ACCOUNT_RETENTION_DAYS)
    return purged


async def run_retention() -> dict:
    """Daily maintenance entry point."""
    return {
        "webhook_events_purged": await purge_old_webhook_events(),
        "closed_accounts_purged": await purge_closed_accounts(),
    }
