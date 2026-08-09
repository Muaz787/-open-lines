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

    # Recover card trials that hit the minute cap but were never converted (Stripe
    # was down at end-of-call). Their line is GATED by the safety net, and calls are
    # exactly what would normally trigger the retry — so this sweep is the only way
    # back. Runs FIRST so a recovered tenant gets the right email below.
    try:
        from services import trial
        stalled = await trial.retry_stalled_conversions()
        logger.info("stalled trial conversions: %s", stalled)
    except Exception as e:
        logger.error("stalled trial conversion sweep failed: %s", e)

    # Daily maintenance also sends due free-trial reminder emails (deduped per
    # tenant) — for BOTH the card trial (day-3 / day-6 charge notices) and the
    # legacy card-free trial. Conversion + payment-failure notices are not here;
    # they are sent from the Stripe invoice webhooks so they arrive immediately.
    try:
        from services import trial
        card_sent = await trial.process_card_trial_reminders()
        logger.info("card_trial_reminders done: %s", card_sent)
    except Exception as e:
        logger.error("card_trial_reminders failed: %s", e)

    try:
        from services import trial
        sent = await trial.process_trial_reminders()
        logger.info("trial_reminders done: %s", sent)
    except Exception as e:
        logger.error("trial_reminders failed: %s", e)

    # ...and reclaims phone numbers from tenants who have gone (lapsed trials,
    # cancelled customers). DARK by default — NUMBER_RECLAIM_ENABLED must be on,
    # AND NUMBER_RECLAIM_DRY_RUN must be explicitly off, before a single number is
    # released. Releasing is irreversible, so it takes two deliberate acts.
    try:
        from services import number_reclaim
        rec = await number_reclaim.run_reclaim()
        logger.info("number reclaim: %s", rec)
    except Exception as e:
        logger.error("number reclaim failed: %s", e)

    # ...and runs the data-retention purge (aged webhook payloads + closed accounts).
    try:
        from services import retention
        result = await retention.run_retention()
        logger.info("retention done: %s", result)
    except Exception as e:
        logger.error("retention failed: %s", e)

    # ...and backfills AI-Insights call enrichment for a small batch of calls that
    # don't have an intent yet (idempotent; only touches intent IS NULL). Non-fatal.
    try:
        from services import call_enrichment
        bf = await call_enrichment.backfill_missing_intents(limit=150)
        logger.info("call-intent backfill done: %s", bf)
    except Exception as e:
        logger.error("call-intent backfill failed: %s", e)

    # ...and checks whether total platform call-minutes crossed the ops threshold
    # (default 30k/mo) — a one-time nudge to revisit self-hosting the voice stack.
    try:
        from services import usage
        alert = await usage.check_platform_minutes_alert()
        logger.info("platform-minutes alert check: %s", alert)
    except Exception as e:
        logger.error("platform-minutes alert check failed: %s", e)

    # ...and reconciles warm-transfer talk-time from the Twilio operator leg into
    # transfer_attempts.duration_secs (VISIBILITY only — never fed into billing).
    # Idempotent: only fills rows still missing a duration; a still-live leg is left
    # for the next run. Uses each tenant's own Twilio subaccount creds from the DB.
    try:
        from services import transfer_reconcile
        rec = await transfer_reconcile.reconcile_pending()
        logger.info("transfer-duration reconcile done: %s", rec)
    except Exception as e:
        logger.error("transfer-duration reconcile failed: %s", e)

    # Heartbeat for the admin health page — proves the daily cron is running.
    try:
        from datetime import datetime, timezone
        await db.set_system_meta("cron_last_run", datetime.now(timezone.utc).isoformat())
    except Exception as e:
        logger.error("cron heartbeat write failed: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
