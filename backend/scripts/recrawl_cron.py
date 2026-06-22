"""
Railway cron entrypoint — re-crawl stale tenant websites.

Run as a SCHEDULED Railway service (not the always-on web service):
    Start command : python scripts/recrawl_cron.py
    Cron schedule : 0 8 * * *        (daily 08:00 UTC; staleness is checked inside)

It calls the same logic as POST /admin/recrawl-stale-websites directly, so no
HTTP round-trip and no ADMIN_API_KEY is needed. Reuses the backend env vars
(SUPABASE_*, OPENAI_API_KEY, PINECONE_*, FIRECRAWL_API_KEY, VAPI_API_KEY for the
post-crawl reprompt). Exits 0 on completion, non-zero only if it couldn't start.
"""
import os
import sys
import asyncio
import logging

# Make `services` / `db` importable when run from the backend service root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")
logger = logging.getLogger("recrawl_cron")


async def main() -> int:
    from services import recrawl
    from db import supabase as db

    try:
        due = await recrawl.find_stale_tenants(limit=recrawl.MAX_TENANTS_PER_RUN)
    except Exception as e:
        logger.error("recrawl_cron: could not list stale tenants: %s", e)
        return 1

    crawled = failed = 0
    for t in due:
        try:
            full = await db.get_tenant_by_id(t["id"])
            await recrawl.recrawl_tenant(full, source="scheduled")
            crawled += 1
        except Exception:
            # recrawl_tenant already logged + recorded the sanitized error on the tenant.
            failed += 1

    logger.info("recrawl_cron done: considered=%d crawled=%d failed=%d", len(due), crawled, failed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
