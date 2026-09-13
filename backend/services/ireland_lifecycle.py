"""The one driver that moves an Irish onboarding forward (W9I-H.AUTO.1).

WHY THIS EXISTS
W9I-H.AUTO found three complete, well-tested orchestration units with no
production caller: temporary acquisition, permanent acquisition and permanent
activation. The limbs were built; the spine was not. Everything after "your
filing was submitted" waited for an employee to notice.

WHAT IT IS
One deterministic advancement function. It inspects durable authoritative state,
performs at most the next safe piece of work, and returns what it did. It
COORDINATES the existing units and reimplements none of them -- routing, health,
promotion, billing and the activation email all stay where they are.

    advance(tenant_id)

Callers never decide which step comes next, and repeated calls converge. It is
safe from the regulatory callback, from the scheduled reconciliation pass, and
from a customer action that completes a filing.

THE WAKE-UP IS NEVER THE AUTHORITY
A callback says "look again", not "it is approved". Wherever provider state
decides whether to spend money or hand out free service, this reads the Bundle
directly with the tenant's own sub-account credentials. An outage is UNKNOWN --
never rejection, never approval, and never grounds to act.

THE COMMERCIAL BOUNDARY IS ABSOLUTE
Nothing here starts a trial. The trial begins inside permanent_activation, only
after a permanent +353 is health-checked and ACTIVE, and no amount of temporary
testing moves it earlier.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db import ireland_temp_access as ita
from db import phone_numbers as db_phones
from db import regulatory as db_reg
from db.supabase import get_client
from services import onboarding_lifecycle as lifecycle_ob
from services import permanent_activation
from services import permanent_numbers
from services import phone_lifecycle as lifecycle
from services import phone_registry
from services import regulatory_state as st
from services import telephony
from services import temporary_numbers
from services import tenant_subaccount

logger = logging.getLogger(__name__)

# ── outcomes ───────────────────────────────────────────────────────────────
NOT_APPLICABLE = "not_applicable"
NOTHING_TO_DO = "nothing_to_do"
PROVIDER_UNKNOWN = "provider_state_unknown"
TEMP_PROVISIONED = "temporary_number_provisioned"
TEMP_BLOCKED = "temporary_number_blocked"
TEMP_SUSPENDED = "temporary_access_suspended"
PERMANENT_ACQUIRED = "permanent_number_acquired"
PERMANENT_ACTIVATED = "permanent_number_activated"
TEMP_RETIRED = "temporary_number_retired"
AWAITING_CUSTOMER = "awaiting_customer_action"
NOT_FOUND = "tenant_not_found"

# ── APPROVED POLICY (W9I-H.AUTO.1). Durations live HERE, in one place, ─────
# because they are product decisions rather than schema. Migration 036 records
# the instants each clock starts from; these say how long each one runs.

#: Free test allowance for the whole onboarding lifecycle. Not per day, not per
#: number, and not reset by replacement, retry, restart, correction or retirement
#: -- which is exactly why it is stored against the tenant and not the phone row.
FREE_SECONDS = 60 * 60

#: Maximum free access while a genuine review is pending.
PENDING_DAYS = 30

#: Correction window once the provider asks for more information. The existing
#: line stays usable inside it; no new one is ever issued.
ACTION_REQUIRED_DAYS = 14

#: Grace after a definitive rejection.
REJECTED_DAYS = 7

#: Transition window after the permanent line goes live. Service continuity only
#: -- it does NOT extend the 60-minute allowance.
CUTOVER_HOURS = 24

#: Why access stopped. Recorded durably so a customer surface can explain it
#: without inventing a reason from a provider error.
SUSPEND_ALLOWANCE = "test_allowance_exhausted"
SUSPEND_PENDING_EXPIRED = "pending_review_period_expired"
SUSPEND_ACTION_EXPIRED = "correction_window_expired"
SUSPEND_REJECTED = "registration_rejected"

#: Provider statuses that mean a regulator is genuinely holding the filing. The
#: ONLY family that entitles a customer to a new temporary number. Everything
#: else -- draft, unsubmitted, rejected, action-required, expired -- does not,
#: and neither does any local record of any of them.
PROVIDER_REVIEW_STATES = ("pending-review", "in-review", "provisionally-approved")
PROVIDER_APPROVED = "twilio-approved"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _elapsed_past(started, delta: timedelta) -> bool:
    """Has `delta` passed since `started`? False when we do not know when."""
    when = _parse(started)
    return bool(when and _now() - when >= delta)


async def _tenant(tenant_id: str) -> dict | None:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data) or []
    return rows[0] if rows else None


# ── the provider is the authority ──────────────────────────────────────────

async def provider_filing_state(tenant: dict) -> dict:
    """Read this tenant's Bundle from Twilio, right now. No cached state.

    W9I-H.AUTO's finding was that temporary eligibility trusted
    tenant_regulatory_profiles.state -- a local memory of a delivery. A stale or
    forged `pending_review` there would have bought someone a free phone line.

    Returns {"known": bool, "status": str, "profile": dict|None}. `known` is
    False for every outcome that is not a successful read: a timeout, 401, 403,
    429, 5xx or a missing bundle. An outage is not a rejection and not an
    approval, and it never authorises spending or free service.
    """
    tenant_id = str(tenant.get("id") or "")
    country = str(tenant.get("business_country_code") or "").strip().upper()
    profiles = [p for p in await db_reg.list_profiles(tenant_id)
                if str(p.get("iso_country") or "").upper() == country]
    filed = [p for p in profiles if p.get("bundle_sid")]
    if not filed:
        return {"known": True, "status": "", "profile": None, "reason": "no_filing"}

    sub_sid = str(tenant.get("twilio_subaccount_sid") or "")
    sub_tok = str(tenant.get("twilio_auth_token") or "")
    if not (sub_sid and sub_tok):
        return {"known": False, "status": "", "profile": None,
                "reason": "missing_credentials"}

    # The furthest-along filing decides, but every read is scoped to the
    # tenant's OWN sub-account, and a bundle held elsewhere is never believed.
    owned = [p for p in filed
             if str(p.get("provider_account_sid") or "") == sub_sid]
    if not owned:
        logger.error("lifecycle: no filing for tenant %s is on its own sub-account",
                     tenant_id)
        return {"known": True, "status": "", "profile": None,
                "reason": "no_owned_filing"}

    last: dict | None = None
    for profile in owned:
        try:
            client = telephony.regulatory_client(sub_sid, sub_tok)
            live = client.numbers.v2.regulatory_compliance.bundles(
                str(profile["bundle_sid"])).fetch()
        except Exception as e:
            # A read we could not complete. NOT a rejection and NOT an approval.
            logger.error("lifecycle: bundle read failed for tenant %s: %s",
                         tenant_id, type(e).__name__)
            return {"known": False, "status": "", "profile": profile,
                    "reason": type(e).__name__}
        holder = str(getattr(live, "account_sid", "") or "")
        if holder and holder != sub_sid:
            return {"known": False, "status": "", "profile": profile,
                    "reason": "bundle_account_mismatch"}
        status = str(getattr(live, "status", "") or "").strip().lower()
        last = {"known": True, "status": status, "profile": profile}
        if status == PROVIDER_APPROVED or status in PROVIDER_REVIEW_STATES:
            return last
    return last or {"known": True, "status": "", "profile": None,
                    "reason": "no_owned_filing"}


# ── the driver ─────────────────────────────────────────────────────────────

async def advance(tenant_id: str) -> dict:
    """Move this Irish onboarding to its next safe state. Converges on repeat.

    Ordered by consequence, not by chronology: the most advanced state is
    handled first, so a wake-up that arrives late never undoes newer work.
    """
    tenant = await _tenant(tenant_id)
    if not tenant:
        return {"outcome": NOT_FOUND}

    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not lifecycle_ob.needs_regulatory_clearance(country):
        # CA/US get their number at signup. There is no regulated lifecycle here.
        return {"outcome": NOT_APPLICABLE, "reason": "country_is_not_regulated"}

    rows = await db_phones.list_for_tenant(tenant_id)
    perm_active = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                   and r.get("status") == lifecycle.STATUS_ACTIVE]
    perm_pending = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                    and r.get("status") == lifecycle.STATUS_PROVISIONING]

    # ── 1. THE PERMANENT LINE IS LIVE: cutover, then retirement ───────────
    if perm_active:
        return await _after_permanent(tenant, rows)

    # ── 2. A PERMANENT NUMBER EXISTS BUT IS NOT LIVE: finish activating ───
    # Health, promotion, trial and the activation email all belong to
    # permanent_activation. This only decides that it is time to call it.
    if perm_pending:
        result = await permanent_activation.activate_permanent_irish_number(tenant_id)
        if result.get("status") == permanent_activation.OK:
            await ita.start_cutover(tenant_id)
            return {"outcome": PERMANENT_ACTIVATED, "detail": result}
        return {"outcome": NOTHING_TO_DO, "step": "permanent_activation",
                "detail": result.get("status")}

    # ── 3. ASK THE PROVIDER WHAT IS ACTUALLY TRUE ─────────────────────────
    state = await provider_filing_state(tenant)
    if not state["known"]:
        # We do not know. Nothing is issued, nothing is suspended, nothing is
        # bought, and the next pass asks again.
        return {"outcome": PROVIDER_UNKNOWN, "reason": state.get("reason")}

    status = state["status"]
    access = await ita.get(tenant_id)

    # ── 4. APPROVED: acquire the permanent number, then activate it ───────
    if status == PROVIDER_APPROVED:
        acquired = await permanent_numbers.ensure_permanent_irish_number(tenant_id)
        if acquired.get("status") in (permanent_numbers.OK,
                                      permanent_numbers.ALREADY_HELD):
            # Do NOT activate in the same pass. The row has just been written;
            # the next advance() reads it back and takes the activation path above, which
            # keeps "acquire" and "activate" independently restartable.
            return {"outcome": PERMANENT_ACQUIRED, "detail": acquired.get("status")}
        return {"outcome": NOTHING_TO_DO, "step": "permanent_acquisition",
                "detail": acquired.get("status"), "reason": acquired.get("reason")}

    # ── 5. THE PROVIDER ASKED FOR CORRECTIONS ────────────────────────────
    if status in ("twilio-rejected", "rejected"):
        await ita.start_rejected(tenant_id)
        return await _enforce(tenant, access, status)
    if status in ("action-required", "twilio-action-required"):
        await ita.start_action_required(tenant_id)
        return await _enforce(tenant, access, status)

    # ── 6. GENUINE REVIEW: the customer is entitled to test ──────────────
    if status in PROVIDER_REVIEW_STATES:
        # A correction was accepted and review resumed. The window closes; the
        # 30-day lifetime deliberately does NOT restart.
        if access and access.get("action_required_at"):
            await ita.clear_action_required(tenant_id)
            access = await ita.get(tenant_id)
        enforced = await _enforce(tenant, access, status)
        if enforced["outcome"] == TEMP_SUSPENDED:
            return enforced
        return await _ensure_temporary(tenant, verified_status=status)

    # Filed, but in a state nobody is reviewing and nobody has decided.
    return {"outcome": AWAITING_CUSTOMER, "provider_status": status}


# ── enforcement: the approved limits ──────────────────────────────────────

async def _enforce(tenant: dict, access: dict | None, provider_status: str) -> dict:
    """Apply the approved allowance and deadlines. Suspends; never releases.

    Suspension stops inbound testing and nothing else: the filing continues, the
    number stays where it is, and retirement remains a separate fenced step with
    its own triggers.
    """
    tenant_id = str(tenant["id"])
    if not access:
        return {"outcome": NOTHING_TO_DO, "reason": "no_temporary_access_record"}
    if access.get("suspended_at"):
        return {"outcome": TEMP_SUSPENDED, "reason": access.get("suspend_reason"),
                "already": True}

    reason = ""
    if int(access.get("seconds_used") or 0) >= FREE_SECONDS:
        reason = SUSPEND_ALLOWANCE
    elif _elapsed_past(access.get("rejected_at"), timedelta(days=REJECTED_DAYS)):
        reason = SUSPEND_REJECTED
    elif _elapsed_past(access.get("action_required_at"),
                       timedelta(days=ACTION_REQUIRED_DAYS)):
        reason = SUSPEND_ACTION_EXPIRED
    elif _elapsed_past(access.get("access_started_at"), timedelta(days=PENDING_DAYS)):
        reason = SUSPEND_PENDING_EXPIRED
    if not reason:
        return {"outcome": NOTHING_TO_DO, "provider_status": provider_status}

    await ita.suspend(tenant_id=tenant_id, reason=reason)
    logger.warning("temporary test access suspended for tenant %s (%s)",
                   tenant_id, reason)
    return {"outcome": TEMP_SUSPENDED, "reason": reason}


# ── the temporary line ────────────────────────────────────────────────────

async def _ensure_temporary(tenant: dict, *, verified_status: str) -> dict:
    """Give a genuinely-reviewed tenant a test line, at most once, ever.

    The provider state was verified by the caller -- this is never reached from
    local state alone. A tenant whose allowance or clock already ran out is not
    handed a fresh line: suspension is checked before we get here, and a
    lifecycle that already recorded a provider attempt never buys again.
    """
    tenant_id = str(tenant["id"])
    await ita.claim(tenant_id)
    access = await ita.get(tenant_id) or {}

    if access.get("suspended_at"):
        return {"outcome": TEMP_SUSPENDED, "reason": access.get("suspend_reason")}

    # A number is already recorded for this lifecycle: nothing to buy.
    if access.get("e164"):
        await ita.start_access(tenant_id)
        return {"outcome": NOTHING_TO_DO, "reason": "temporary_number_already_held",
                "e164": access.get("e164")}

    # AN ATTEMPT WAS RECORDED AND WE NEVER SAW THE ANSWER. Twilio may hold a
    # number we have never seen. Reconcile positively or stop -- elapsed time is
    # not evidence and never restores the authority to buy.
    if access.get("provider_attempt_at"):
        return await _reconcile_temporary(tenant)

    if not await ita.mark_attempt(tenant_id):
        # Another worker owns the attempt. It may already have finished.
        fresh = await ita.get(tenant_id) or {}
        if fresh.get("e164"):
            return {"outcome": NOTHING_TO_DO, "reason": "temporary_number_already_held",
                    "e164": fresh.get("e164")}
        return {"outcome": TEMP_BLOCKED, "reason": "acquisition_in_progress"}

    # We own the attempt, and it is durably recorded. Everything from here is
    # recoverable BECAUSE that write committed first.
    result = await temporary_numbers.ensure_temporary_number(
        tenant_id, verified_provider_status=verified_status)
    status = result.get("status")
    if status in (temporary_numbers.OK, temporary_numbers.ALREADY_ACTIVE):
        e164 = str(result.get("e164") or "")
        sid = str((result.get("row") or {}).get("provider_sid") or "")
        if e164 and sid:
            await ita.attach_number(tenant_id=tenant_id, e164=e164, provider_sid=sid)
        await ita.start_access(tenant_id)
        return {"outcome": TEMP_PROVISIONED, "e164": e164,
                "verified_provider_status": verified_status}
    return {"outcome": TEMP_BLOCKED, "reason": result.get("reason"),
            "status": status}


async def _reconcile_temporary(tenant: dict) -> dict:
    """Find the number an unconfirmed purchase may have produced. Never buys.

    Twilio's per-sub-account listing is authoritative and immediately consistent
    -- unlike a search index -- so it IS a usable oracle here. What it is not is
    a licence to guess: more than one candidate means an operator looks, exactly
    as the permanent path already does.
    """
    tenant_id = str(tenant["id"])
    sub = await tenant_subaccount.ensure(tenant)
    if sub["status"] != tenant_subaccount.OK:
        return {"outcome": TEMP_BLOCKED, "reason": "subaccount_unavailable"}

    held = await temporary_numbers.held_numbers(sub["sid"], sub["auth_token"])
    if held["status"] != temporary_numbers.OK:
        return {"outcome": TEMP_BLOCKED, "reason": "inventory_unreadable"}

    chosen = temporary_numbers.pick_unambiguous(held["numbers"])
    if chosen is None:
        if held["numbers"]:
            logger.error("tenant %s holds %d unassigned numbers after an "
                         "unconfirmed temporary purchase -- operator review",
                         tenant_id, len(held["numbers"]))
            return {"outcome": TEMP_BLOCKED, "reason": "ambiguous_provider_inventory"}
        # Nothing held. That may mean the purchase failed, or that the listing
        # is momentarily wrong. Neither is proof, so nothing is bought.
        return {"outcome": TEMP_BLOCKED, "reason": "purchase_outcome_unresolved"}

    await ita.attach_number(tenant_id=tenant_id, e164=chosen["e164"],
                            provider_sid=chosen["sid"])
    logger.warning("adopted temporary number for tenant %s after an unconfirmed "
                   "purchase", tenant_id)
    return {"outcome": TEMP_PROVISIONED, "e164": chosen["e164"], "adopted": True}


# ── after the permanent line is live ──────────────────────────────────────

async def _after_permanent(tenant: dict, rows: list[dict]) -> dict:
    """Cutover, then retire the temporary line. In that order, always.

    The temporary number stays usable for the transition window so a customer
    who published it is not cut off the instant the real number appears.
    """
    tenant_id = str(tenant["id"])
    await ita.start_cutover(tenant_id)

    live_temp = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
                 and r.get("status") in lifecycle.LIVE_TEMPORARY_STATUSES]
    if not live_temp:
        return {"outcome": NOTHING_TO_DO, "reason": "no_live_temporary_number"}

    access = await ita.get(tenant_id) or {}
    if not _elapsed_past(access.get("cutover_at"), timedelta(hours=CUTOVER_HOURS)):
        return {"outcome": NOTHING_TO_DO, "reason": "within_cutover_grace",
                "e164": live_temp[0].get("e164")}

    return await retire_temporary(tenant_id)


async def retire_temporary(tenant_id: str) -> dict:
    """Release the temporary number. Idempotent, fenced, and narrow.

    THE EXECUTOR W9I-H.AUTO FOUND MISSING. It can only ever release a row whose
    purpose is temporary_test and which belongs to this tenant: a permanent
    number is unreachable from here by construction, not by care.
    """
    tenant = await _tenant(tenant_id)
    if not tenant:
        return {"outcome": NOT_FOUND}

    rows = await db_phones.list_for_tenant(tenant_id)
    live_temp = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
                 and r.get("status") in lifecycle.LIVE_TEMPORARY_STATUSES]
    if not live_temp:
        return {"outcome": NOTHING_TO_DO, "reason": "no_live_temporary_number"}
    row = live_temp[0]

    # Belt and braces: the row we are about to release must be a temporary one
    # owned by this tenant. Asserted rather than assumed, because the cost of
    # being wrong is releasing a customer's live business number.
    if row.get("purpose") != lifecycle.PURPOSE_TEMPORARY:
        logger.error("retirement refused: row %s is not temporary", row.get("id"))
        return {"outcome": NOTHING_TO_DO, "reason": "not_a_temporary_number"}
    if str(row.get("tenant_id")) != tenant_id:
        logger.error("retirement refused: row %s belongs to another tenant",
                     row.get("id"))
        return {"outcome": NOTHING_TO_DO, "reason": "cross_tenant_refused"}

    if not await ita.claim_retirement(tenant_id):
        return {"outcome": NOTHING_TO_DO, "reason": "retirement_already_claimed"}

    sub_sid = str(row.get("provider_account_sid") or "")
    sub_tok = str(tenant.get("twilio_auth_token") or "")
    if not (sub_sid and sub_tok):
        return {"outcome": NOTHING_TO_DO, "reason": "missing_twilio_credentials"}

    try:
        released = await telephony.release_number(sub_sid, sub_tok,
                                                  str(row.get("e164") or ""))
    except Exception as e:
        # UNKNOWN. The release may have happened. The claim is already recorded
        # so no later pass releases blind; the next run reads the provider.
        logger.error("temporary release outcome unknown for tenant %s: %s",
                     tenant_id, type(e).__name__)
        return {"outcome": NOTHING_TO_DO, "reason": "release_outcome_unknown"}
    if not released:
        # "We asked and something went wrong" is not proof the number is gone.
        # The canonical row stays exactly as it is so the next pass can retry.
        return {"outcome": NOTHING_TO_DO, "reason": "release_not_confirmed"}

    # Canonical bookkeeping, fenced on the exact identity we just released.
    book = await phone_registry.mark_released(
        tenant_id=tenant_id, number_row_id=str(row["id"]),
        expected_e164=str(row.get("e164") or ""),
        expected_provider_sid=str(row.get("provider_sid") or ""),
        expected_provider_account_sid=sub_sid)
    await ita.mark_released(tenant_id)
    logger.warning("temporary test number retired for tenant %s", tenant_id)
    return {"outcome": TEMP_RETIRED, "e164": row.get("e164"),
            "released": True, "bookkeeping": book.get("status")}


# ── usage: the free allowance, and the fraud boundary ─────────────────────

async def is_temporary_line(tenant_id: str, e164: str) -> bool:
    """Did this call arrive on a temporary test number? Canonical rows only.

    Never the legacy scalar: that points at whichever number is "the" number and
    says nothing about which line rang.
    """
    if not e164:
        return False
    rows = await db_phones.list_for_tenant(tenant_id)
    return any(r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
               and str(r.get("e164") or "") == str(e164)
               for r in rows)


async def record_temporary_usage(*, tenant_id: str, called_number: str,
                                 duration_secs: int) -> bool:
    """Account a finished call against the free allowance. True if it was free.

    Returns True when the call arrived on the temporary test line, which means
    the caller must NOT put it through billing. The increment happens in the
    database so two calls ending together cannot both read the same total -- the
    way a 59-minute tenant would otherwise obtain unbounded minutes.

    Crossing the allowance suspends further testing. It does not end the call in
    progress: the telephony layer has no graceful mid-call cutoff, and dropping a
    customer mid-sentence to save seconds of a free trial is the worse trade. The
    bounded overrun is therefore one call's remaining duration per concurrent
    call, and it is accepted deliberately rather than by omission.
    """
    if not await is_temporary_line(tenant_id, called_number):
        return False

    row = await ita.consume_seconds(tenant_id=tenant_id,
                                    seconds=max(0, int(duration_secs)))
    used = int((row or {}).get("seconds_used") or 0)
    if used >= FREE_SECONDS and not (row or {}).get("suspended_at"):
        await ita.suspend(tenant_id=tenant_id, reason=SUSPEND_ALLOWANCE)
        logger.warning("tenant %s exhausted its free temporary test allowance "
                       "(%ds) -- testing suspended", tenant_id, used)
    return True


async def temporary_testing_allowed(tenant_id: str) -> bool:
    """May this tenant still receive temporary test calls?"""
    access = await ita.get(tenant_id)
    if not access:
        return True
    return not access.get("suspended_at")


async def transfer_allowed(tenant_id: str) -> bool:
    """May a call on this tenant be transferred to the PSTN right now?

    NO while the tenant is on a temporary test line. The free line exists so a
    customer can ring their own receptionist and hear it work -- it is not a
    telephony product, and a transfer turns an inbound test into billable
    outbound minutes to any destination the caller can talk the assistant into.

    Server-side and independent of the assistant's prompt: an LLM that decides
    to transfer, or is talked into deciding, still cannot make one happen.
    """
    rows = await db_phones.list_for_tenant(tenant_id)
    live_temp = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
                 and r.get("status") in lifecycle.LIVE_TEMPORARY_STATUSES]
    if not live_temp:
        return True
    perm_active = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                   and r.get("status") == lifecycle.STATUS_ACTIVE]
    # During the 24-hour cutover both lines exist. The permanent one is a real
    # paid line, so the tenant is no longer in test mode.
    return bool(perm_active)


# ── the wake-ups ──────────────────────────────────────────────────────────
#
# Three callers, one behaviour. None of them is the authority: each one only
# says "look again", and advance() then reads the provider for itself.

#: Tenants inspected per scheduled run. A cap rather than the whole backlog: the
#: run that tries to sweep everything after an outage is exactly when the
#: provider can least serve it, and tomorrow's run continues from where this
#: one stopped.
SCHEDULED_BATCH = 50


async def wake(tenant_id: str, *, source: str) -> dict:
    """Advance one tenant because something suggested it might be time.

    Never raises: a wake-up is best-effort by nature, and a callback handler or a
    cron pass must not fail because one tenant's provider read timed out.
    """
    try:
        result = await advance(tenant_id)
        if result.get("outcome") not in (NOTHING_TO_DO, NOT_APPLICABLE):
            logger.info("ireland lifecycle (%s): tenant %s -> %s",
                        source, tenant_id, result.get("outcome"))
        return result
    except Exception as e:
        logger.error("ireland lifecycle (%s) raised for tenant %s: %s",
                     source, tenant_id, type(e).__name__)
        return {"outcome": NOTHING_TO_DO, "error": type(e).__name__}


async def run_scheduled() -> dict:
    """Sweep every Irish onboarding that is not finished. The recovery path.

    Bounded, and deliberately not clever about ordering: advance() is
    idempotent, so a tenant swept twice in a row costs one provider read.
    """
    rows = (get_client().table("tenants")
            .select("id, onboarding_state, business_country_code")
            .eq("business_country_code", "IE")
            .neq("onboarding_state", lifecycle_ob.ACTIVE)
            .limit(SCHEDULED_BATCH).execute().data) or []
    counts: dict[str, int] = {}
    for row in rows:
        out = await wake(str(row["id"]), source="scheduled")
        key = str(out.get("outcome") or "unknown")
        counts[key] = counts.get(key, 0) + 1

    # Tenants whose permanent line is already live still need the cutover and
    # retirement steps, and they are ACTIVE, so the filter above skips them.
    live = (get_client().table("tenants")
            .select("id")
            .eq("business_country_code", "IE")
            .eq("onboarding_state", lifecycle_ob.ACTIVE)
            .limit(SCHEDULED_BATCH).execute().data) or []
    for row in live:
        out = await wake(str(row["id"]), source="scheduled_cutover")
        key = str(out.get("outcome") or "unknown")
        counts[key] = counts.get(key, 0) + 1

    return {"inspected": len(rows) + len(live), "counts": counts}
