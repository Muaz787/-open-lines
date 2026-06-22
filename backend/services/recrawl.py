"""
Website knowledge-base re-crawl orchestration (manual + scheduled).

Shared by the manual Sync button and the scheduled admin endpoint so both use the
same safe, two-phase, clear-before-embed refresh and write the same crawl metadata.
"""
import logging
from datetime import datetime, timezone, timedelta

from db import supabase as db
from services import knowledge

logger = logging.getLogger(__name__)

STALE_DAYS = 7                    # re-crawl websites not refreshed within this many days
RECRAWL_INTERVAL_DAYS = 7        # used to compute next_crawl_at
MAX_TENANTS_PER_RUN = 20         # budget guard: tenants processed per scheduled run
MAX_CONSECUTIVE_FAILURES = 3     # skip tenants whose recent crawls keep failing
_ACTIVE_STATUSES = {"active", "trialing"}


def _sanitize_error(e: Exception) -> str:
    """Keep a short, non-sensitive error string for the dashboard."""
    return str(e).replace("\n", " ")[:300]


async def recrawl_tenant(tenant: dict, source: str) -> dict:
    """Re-scrape a tenant's website and refresh its website KB vectors.

    Two-phase + clear-before-embed (in knowledge.refresh_tenant_knowledge): on
    failure the existing KB is kept and the error is recorded; uploaded documents
    are never touched. `source` is 'manual' | 'scheduled' | 'onboarding'.
    """
    tenant_id   = tenant["id"]
    website_url = tenant.get("website_url") or ""
    namespace   = tenant.get("pinecone_namespace") or ""

    if not website_url:
        raise ValueError("Tenant has no website configured to sync")
    if not namespace:
        raise ValueError("Tenant has no knowledge-base namespace")

    from services.security import validate_public_url
    validate_public_url(website_url)  # SSRF guard

    now = datetime.now(timezone.utc)
    try:
        result = await knowledge.refresh_tenant_knowledge(tenant_id, website_url, namespace)
    except Exception as e:
        failures = int(tenant.get("last_crawl_failures") or 0) + 1
        try:
            await db.update_tenant(tenant_id, {
                "last_crawl_status":   "error",
                "last_crawl_error":    _sanitize_error(e),
                "last_crawl_source":   source,
                "last_crawl_failures": failures,
                "next_crawl_at":       (now + timedelta(days=RECRAWL_INTERVAL_DAYS)).isoformat(),
            })
        except Exception:
            pass
        logger.error("recrawl: failed for tenant %s (source=%s, failures=%d): %s",
                     tenant_id, source, failures, _sanitize_error(e))
        raise

    await db.update_tenant(tenant_id, {
        "last_crawl_at":       result["refreshed_at"].isoformat(),
        "last_crawl_status":   "success",
        "last_crawl_error":    None,
        "last_crawl_pages":    result["pages_scraped"],
        "last_crawl_source":   source,
        "last_crawl_failures": 0,
        "next_crawl_at":       (now + timedelta(days=RECRAWL_INTERVAL_DAYS)).isoformat(),
    })

    try:
        await db.upsert_kb_website_entry(tenant_id, website_url)
    except Exception as e:
        logger.warning("recrawl: kb entry upsert failed for tenant %s: %s", tenant_id, e)

    # Re-push the assistant prompt so the fresh KB reaches the AI (best-effort).
    try:
        fresh = await db.get_tenant_by_id(tenant_id)
        from services.provisioning import rebuild_and_push_system_prompt
        await rebuild_and_push_system_prompt(fresh)
    except Exception as e:
        logger.warning("recrawl: reprompt failed for tenant %s (non-fatal): %s", tenant_id, e)

    return {"status": "success", **result}


async def find_stale_tenants(limit: int = MAX_TENANTS_PER_RUN) -> list[dict]:
    """Tenants due for a scheduled re-crawl: website set, auto-recrawl on, active or
    trialing, not crawled within STALE_DAYS, and not repeatedly failing."""
    res = (
        db.get_client()
        .table("tenants")
        .select(
            "id, website_url, pinecone_namespace, last_crawl_at, "
            "last_crawl_failures, auto_recrawl_enabled, subscription_status"
        )
        .execute()
    )
    rows = res.data or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    due: list[dict] = []
    for t in rows:
        if not t.get("website_url"):
            continue
        if t.get("auto_recrawl_enabled") is False:           # default true (null/absent → eligible)
            continue
        if (t.get("subscription_status") or "").lower() not in _ACTIVE_STATUSES:
            continue
        if int(t.get("last_crawl_failures") or 0) >= MAX_CONSECUTIVE_FAILURES:
            continue
        last = t.get("last_crawl_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if last_dt > cutoff:
                    continue  # crawled recently enough
            except Exception:
                pass  # unparseable timestamp → treat as stale
        due.append(t)
        if len(due) >= limit:
            break
    return due
