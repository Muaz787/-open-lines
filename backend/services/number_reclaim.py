"""
Reclaim phone numbers from tenants who have gone.

THE PROBLEM: a tenant whose trial lapsed keeps is_active = true and
closed_at = null forever. The retention purge only looks at closed accounts, so
it never sees them, and their Twilio number bills us every month indefinitely.
The card-required trial stopped new tire-kickers; it did nothing about the pile
already provisioned.

THE DANGER: releasing a number is irreversible. Twilio can reassign it, so a
business that loses one loses it permanently and its callers eventually reach a
stranger. Every safeguard in this module exists because the failure mode is
destroying a real business's phone line, not an inconvenience.

  * NUMBER_RECLAIM_ENABLED — master switch, OFF by default. With it unset this
    module does nothing at all.
  * NUMBER_RECLAIM_DRY_RUN — defaults to TRUE even once enabled, so turning the
    feature on logs what it would do without touching anything. Two separate
    deliberate acts are required before a single number is released.
  * A hard per-run cap, so a wrong query can't cascade.
  * Missing data means NEVER release. Every unknown resolves to "leave it alone".
  * Two warning emails before the due date.

GRACE PERIODS reflect what the tenant was to us:
  * never paid (lapsed trial) — 30 days after the trial ended
  * paid at least once         — 60 days after the subscription was cancelled
An explicitly closed account (closed_at) counts from closure, using whichever
grace their payment history earns.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from services.trial import TRIAL_DAYS, is_billing_exempt

logger = logging.getLogger(__name__)

LAPSED_TRIAL_GRACE_DAYS = int(os.getenv("NUMBER_RECLAIM_TRIAL_GRACE_DAYS", "30"))
CANCELED_GRACE_DAYS     = int(os.getenv("NUMBER_RECLAIM_CANCELED_GRACE_DAYS", "60"))
MAX_RELEASES_PER_RUN    = int(os.getenv("NUMBER_RECLAIM_MAX_PER_RUN", "10"))

# Warning schedule, in days before the release date.
WARN1_DAYS_BEFORE = 14
WARN2_DAYS_BEFORE = 3

# A subscription in any of these states is live business — never touch it.
_PROTECTED_STATUSES = {"active", "trialing", "past_due", "canceling"}


def enabled() -> bool:
    """Master switch. Read live so it can be flipped without a deploy."""
    return os.getenv("NUMBER_RECLAIM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def dry_run() -> bool:
    """Defaults to TRUE. Turning the feature on is not enough to release anything
    — you must also explicitly say NUMBER_RECLAIM_DRY_RUN=false. Two deliberate
    acts, because the operation cannot be undone."""
    return os.getenv("NUMBER_RECLAIM_DRY_RUN", "true").strip().lower() not in ("0", "false", "no", "off")


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def _trial_end(tenant: dict) -> datetime | None:
    """When this tenant's trial ended. The Stripe date for a card trial, else the
    derived created_at + 7 days for the legacy card-free one."""
    stripe_end = _parse(tenant.get("stripe_trial_ends_at"))
    if stripe_end:
        return stripe_end
    created = _parse(tenant.get("created_at"))
    return created + timedelta(days=TRIAL_DAYS) if created else None


def release_due_at(tenant: dict) -> datetime | None:
    """The moment this tenant's number becomes eligible for release, or None if
    it never does.

    Pure and total: every branch that can't establish an anchor returns None,
    because "we're not sure" must mean "leave their phone line alone".
    """
    if is_billing_exempt(tenant):
        return None
    if not tenant.get("twilio_phone_number"):
        return None
    if tenant.get("number_released_at"):
        return None      # already done; don't re-release a recycled number

    status = (tenant.get("subscription_status") or "").strip().lower()
    if status in _PROTECTED_STATUSES:
        return None

    ever_paid = bool(tenant.get("first_paid_at"))
    grace = CANCELED_GRACE_DAYS if ever_paid else LAPSED_TRIAL_GRACE_DAYS

    # An admin closing the account is the clearest signal there is, so it wins.
    anchor = _parse(tenant.get("closed_at"))
    if anchor is None:
        anchor = (
            _parse(tenant.get("subscription_canceled_at")) if ever_paid
            else _trial_end(tenant)
        )
    # A tenant who paid but has no recorded cancellation date (a row from before
    # migration 011) gets left alone rather than guessed at.
    if anchor is None:
        return None

    return anchor + timedelta(days=grace)


def classify(tenant: dict, now: datetime | None = None) -> str:
    """What this tenant is due for right now: 'release', 'warn1', 'warn2' or ''."""
    due = release_due_at(tenant)
    if due is None:
        return ""
    now = now or datetime.now(timezone.utc)

    if now >= due:
        return "release"
    if now >= due - timedelta(days=WARN2_DAYS_BEFORE) and not tenant.get("number_release_warn2_sent"):
        return "warn2"
    if now >= due - timedelta(days=WARN1_DAYS_BEFORE) and not tenant.get("number_release_warn1_sent"):
        return "warn1"
    return ""


_SELECT = (
    "id, business_name, email, created_at, closed_at, is_active, billing_exempt, "
    "subscription_status, subscription_plan, subscription_canceled_at, first_paid_at, "
    "stripe_trial_ends_at, twilio_phone_number, twilio_subaccount_sid, twilio_auth_token, "
    "vapi_phone_number_id, vapi_suborg_api_key, number_released_at, "
    "number_release_warn1_sent, number_release_warn2_sent"
)


async def run_reclaim() -> dict:
    """Daily sweep. Returns counts; never raises."""
    from db import supabase as db

    if not enabled():
        return {"enabled": False}

    is_dry = dry_run()

    try:
        res = (
            db.get_client().table("tenants")
            .select(_SELECT)
            .not_.is_("twilio_phone_number", "null")
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        logger.error("number reclaim: tenant fetch failed: %s", e)
        return {"enabled": True, "error": True}

    now = datetime.now(timezone.utc)
    out = {"enabled": True, "dry_run": is_dry, "considered": len(rows),
           "warn1": 0, "warn2": 0, "released": 0, "failed": 0}

    for t in rows:
        action = classify(t, now)
        if not action:
            continue

        if action == "release":
            if out["released"] >= MAX_RELEASES_PER_RUN:
                logger.info("number reclaim: hit the per-run cap of %d, stopping", MAX_RELEASES_PER_RUN)
                break
            if is_dry:
                logger.warning(
                    "[DRY RUN] would release %s for tenant %s (%s) — status=%s, ever_paid=%s, due=%s",
                    t.get("twilio_phone_number"), t.get("id"), t.get("business_name"),
                    t.get("subscription_status"), bool(t.get("first_paid_at")),
                    release_due_at(t),
                )
                out["released"] += 1
                continue
            if await _release(t):
                out["released"] += 1
            else:
                out["failed"] += 1
        else:
            if is_dry:
                logger.info("[DRY RUN] would send %s to tenant %s (%s)",
                            action, t.get("id"), t.get("business_name"))
                out[action] += 1
                continue
            if await _warn(t, action, release_due_at(t)):
                out[action] += 1

    logger.info("number reclaim: %s", out)
    return out


async def _release(tenant: dict) -> bool:
    from db import supabase as db
    from services.provisioning import release_tenant_number

    number = tenant.get("twilio_phone_number")
    try:
        result = await release_tenant_number(tenant)
    except Exception as e:
        logger.error("number reclaim: release raised for tenant %s: %s", tenant.get("id"), e)
        return False

    if not result.get("released"):
        logger.error(
            "number reclaim: could not release %s for tenant %s (%s)",
            number, tenant.get("id"), result.get("reason"),
        )
        return False

    # number_released_at is stamped by release_tenant_number itself, so the manual
    # admin path leaves the same audit trail as this one.
    logger.warning("number reclaim: RELEASED %s for tenant %s (%s)",
                   number, tenant.get("id"), tenant.get("business_name"))
    return True


async def _warn(tenant: dict, kind: str, due: datetime | None) -> bool:
    from db import supabase as db
    from services.email import send_number_release_warning

    if not tenant.get("email") or due is None:
        return False

    try:
        ok = await send_number_release_warning(
            to=tenant["email"],
            business_name=tenant.get("business_name") or "there",
            tenant_id=tenant["id"],
            number=str(tenant.get("twilio_phone_number") or ""),
            release_date=due.strftime("%B %-d, %Y"),
            final=(kind == "warn2"),
        )
    except Exception as e:
        logger.error("number reclaim: %s email failed for tenant %s: %s", kind, tenant.get("id"), e)
        return False

    if not ok:
        return False
    flag = "number_release_warn1_sent" if kind == "warn1" else "number_release_warn2_sent"
    try:
        await db.update_tenant(tenant["id"], {flag: True})
    except Exception as e:
        logger.error("number reclaim: could not set %s for tenant %s: %s", flag, tenant.get("id"), e)
    return True
