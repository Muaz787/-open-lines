"""One operator-authorized Ireland signup, and nothing else (W9I-H.0).

WHAT THIS IS FOR
W9I-H needs its first Irish pilot created through the NORMAL signup path, so the
pilot exercises the flow a future customer will. That path refuses IE while
IRELAND_ONBOARDING_ENABLED is off, and turning that flag on opens Ireland to the
public during a live regulatory filing.

So one signup attempt, named by its onboarding_key, may cross the
country-availability gate. That is the entire scope. It is not regulatory
authorization, not permission to file, not permission to buy a +353, not
permission to start a trial, and not a public launch -- every one of those is a
separate gate and none of them reads this module.

CREATE AUTHORITY AND RESUME AUTHORITY ARE DIFFERENT THINGS
An earlier design said a consumed grant simply keeps opening the gate, because
migration 031's unique index on tenants.onboarding_key makes a second tenant
impossible. That proof holds only while the first tenant EXISTS. Delete it -- a
legitimate purge, a GDPR erasure -- and no row owns the key any more: the index
protects nothing, and a consumed grant would at that moment regain the power to
create a brand new tenant. An immutable audit record would have become durable
authorization.

Hence four states, not two, and the difference between them is whether the bound
tenant is still there:

    UNUSED + unexpired      -> may create ONE tenant
    CONSUMED + tenant bound -> may RESUME that tenant, and nothing else
    CONSUMED + tenant gone  -> DENY. Nothing to resume; history creates nothing.
    CONSUMED + wrong tenant -> FAIL CLOSED. Never repaired automatically.

EXPIRY MEANS "THIS INVITATION LAPSED", NOT "THIS ACCOUNT IS OVER". Before
consumption it decides whether a first tenant may be created. After consumption
it is not consulted -- a customer part-way through onboarding must not be bricked
because a pilot invitation ran out behind them. It can never restore create
authority, because creating requires consumed_at to be NULL and consumption is
one-way.

NOTHING A CUSTOMER SENDS REACHES THIS DECISION. The onboarding_key is the only
input, it is already validated as a uuid4 by the request model, and every other
fact comes from the grant row. There is no header, body field or query parameter
that participates -- a spoofing attempt behaves exactly like an ordinary closed-
country signup, which is also what the customer sees.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.supabase import get_client

logger = logging.getLogger(__name__)

TABLE = "ireland_pilot_onboarding_grants"

# ── the four outcomes ──────────────────────────────────────────────────────
DENY = "deny"
ALLOW_CREATE = "allow_create"
ALLOW_RESUME = "allow_resume"
INTEGRITY = "integrity_error"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def decide(*, onboarding_key: str, iso_country: str) -> dict:
    """May this exact signup attempt cross the closed-country gate?

    Returns {"outcome": DENY|ALLOW_CREATE|ALLOW_RESUME|INTEGRITY, "grant": ...}.
    Reads only the grant row and, when the grant is consumed, the tenant it
    claims to have produced. Never writes.

    Fails closed on ANY unexpected condition, including an unreadable database:
    the safe answer to "should this closed country open" is no.
    """
    key = str(onboarding_key or "").strip().lower()
    country = str(iso_country or "").strip().upper()
    if not key or not country:
        return {"outcome": DENY, "reason": "no_key"}

    try:
        rows = (get_client().table(TABLE).select("*")
                .eq("onboarding_key", key).eq("iso_country", country)
                .limit(1).execute().data) or []
    except Exception as e:
        # Not knowing is not permission.
        logger.error("pilot grant lookup failed: %s", type(e).__name__)
        return {"outcome": DENY, "reason": "grant_lookup_failed"}

    if not rows:
        return {"outcome": DENY, "reason": "no_grant"}
    grant = rows[0]

    if not grant.get("consumed_at"):
        # An invitation. Expiry decides whether it may still be accepted.
        expires = _parse(grant.get("expires_at"))
        if expires is None or expires <= datetime.now(timezone.utc):
            return {"outcome": DENY, "reason": "grant_expired", "grant": grant}
        return {"outcome": ALLOW_CREATE, "grant": grant}

    # Consumed: evidence that ONE tenant crossed this gate. Resolve it, rather
    # than trusting consumed_tenant_id -- there is no foreign key, and the row
    # it names may have been purged.
    try:
        tenants = (get_client().table("tenants").select("id")
                   .eq("onboarding_key", key).limit(2).execute().data) or []
    except Exception as e:
        logger.error("pilot tenant lookup failed: %s", type(e).__name__)
        return {"outcome": DENY, "reason": "tenant_lookup_failed", "grant": grant}

    if not tenants:
        # THE CHECKPOINT CORRECTION. Nothing to resume, and a historical grant
        # creates nothing -- otherwise a purge would silently re-arm it.
        logger.warning("pilot grant for a purged tenant was replayed -- denied")
        return {"outcome": DENY, "reason": "bound_tenant_missing", "grant": grant}
    if len(tenants) > 1:
        # 031's partial unique index makes this impossible; if it ever is not,
        # it is not something to resolve by choosing.
        return {"outcome": INTEGRITY, "reason": "multiple_tenants_for_key",
                "grant": grant}

    tenant_id = str(tenants[0]["id"])
    if tenant_id != str(grant.get("consumed_tenant_id") or ""):
        logger.error("PILOT GRANT INTEGRITY: key resolves to a tenant this grant "
                     "did not produce")
        return {"outcome": INTEGRITY, "reason": "bound_tenant_mismatch",
                "grant": grant}

    # Expiry deliberately NOT re-checked here.
    return {"outcome": ALLOW_RESUME, "grant": grant, "tenant_id": tenant_id}


async def consume(*, onboarding_key: str, tenant_id: str) -> dict:
    """Bind a grant to the tenant its signup produced. Fenced, single-use.

    Called only AFTER durable tenant state exists, so a transient provisioning
    failure cannot brick the signup by burning the invitation.

    Losing the race is not a failure: it means another worker consumed the same
    grant for the same signup. That is accepted only when the outcome is what we
    wanted anyway -- consumed, bound to THIS tenant, and the key still resolves
    to it. Anything else fails closed.
    """
    key = str(onboarding_key or "").strip().lower()
    tid = str(tenant_id or "").strip()
    if not (key and tid):
        return {"ok": False, "reason": "missing_arguments"}

    now = _now()
    try:
        changed = (get_client().table(TABLE)
                   .update({"consumed_at": now, "consumed_tenant_id": tid})
                   .eq("onboarding_key", key)
                   .is_("consumed_at", "null")
                   .gt("expires_at", now)
                   .execute().data) or []
    except Exception as e:
        logger.error("pilot grant consumption failed: %s", type(e).__name__)
        return {"ok": False, "reason": "consume_failed"}

    if changed:
        logger.warning("Ireland pilot grant consumed for tenant %s", tid)
        return {"ok": True, "created": True}

    # Lost the race, or the grant expired between the gate and here. Re-read and
    # accept only the outcome we were trying to produce.
    verdict = await decide(onboarding_key=key, iso_country="IE")
    if verdict["outcome"] == ALLOW_RESUME and verdict.get("tenant_id") == tid:
        return {"ok": True, "created": False}
    logger.error("pilot grant consumption lost and did not converge: %s",
                 verdict.get("reason") or verdict["outcome"])
    return {"ok": False, "reason": verdict.get("reason") or verdict["outcome"]}


def _parse(stamp) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    except Exception:
        return None
