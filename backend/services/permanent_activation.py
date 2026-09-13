"""Making a purchased +353 live, and everything that follows from it (W9I-G).

THE ORDER IS THE DESIGN. Each step is only safe because the one before it
committed, and each has a different consequence if it fails:

    health PASS          -> nothing is live yet; failing costs nothing
    canonical ACTIVE     -> calls now route; the customer has a working line
    scalar + onboarding  -> the rest of the product agrees the line is theirs
    Stripe trial         -> billing starts, and only now is that honest
    activation email     -> the customer is told, and only now is that true

Read backwards, the rule is: never tell a customer something, or charge them for
it, before it is true. Read forwards: once the phone works, NOTHING later may
undo it. A Stripe outage does not roll back a working line, and an email failure
does not deactivate a number -- both are retried against a phone that keeps
ringing throughout.

WHY THE TRIAL STARTS HERE AND NOWHERE ELSE
The authoritative Ireland policy is that the 7-day trial begins only when all
five of approval, purchase, routing, health and ACTIVE are true. Four of those
were settled in earlier gates; this is the first moment all five hold. W9I-G.0
removed the signup-time trial that violated it.

WHAT THIS DOES NOT DO
It does not buy numbers (W9I-F), file anything (W9I-D), or decide how long a
temporary line survives promotion -- that grace duration is an unresolved
product question, and this marks eligibility rather than starting a hidden timer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from db import phone_numbers as db_phones
from db import supabase as db
from db.supabase import get_client
from services import activation_notification as notify
from services import onboarding_lifecycle as lifecycle_ob
from services import phone_lifecycle as lifecycle
from services import telephony

logger = logging.getLogger(__name__)

# ── outcomes ───────────────────────────────────────────────────────────────
OK = "ok"
NOT_FOUND = "tenant_not_found"
NOTHING_TO_ACTIVATE = "no_permanent_number_awaiting_activation"
NOT_ELIGIBLE = "activation_not_eligible"
HEALTH_FAILED = "permanent_number_health_failed"
HEALTH_UNKNOWN = "permanent_number_health_unknown"
PROMOTION_LOST = "activation_lost_to_another_worker"
SCALAR_CONFLICT = "legacy_number_pointer_conflict"
BILLING_SETUP_REQUIRED = "billing_setup_required"
BILLING_PENDING = "billing_completion_pending"
EMAIL_PENDING = "activation_email_pending"

#: Stripe could not be asked what already exists. Distinct from "nothing exists",
#: because only one of the two makes it safe to create.
RECONCILE_UNKNOWN = "reconcile_unknown"

#: Health outcomes, kept separate because they need different things:
#: a mismatch an operator must look at, a gap we may repair, or a provider we
#: simply could not reach.
HEALTHY = "healthy"
REPAIRABLE = "repairable"
UNKNOWN = "unknown"
BROKEN = "broken"


async def _tenant(tenant_id: str) -> dict | None:
    rows = (get_client().table("tenants").select("*")
            .eq("id", tenant_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Stage G: the final health contract ─────────────────────────────────────

async def health_check(*, tenant: dict, row: dict, sub_sid: str,
                       sub_tok: str) -> dict:
    """Would an inbound call to this number reach this tenant's receptionist?

    Every answer is read FROM THE PROVIDERS, now. W9I-F configured this routing
    and recorded that it did; that record is what is being checked, not what is
    being trusted. Between then and now a number can be released, moved, or
    re-pointed by anything with the credentials.

    Returns {"state": HEALTHY|REPAIRABLE|UNKNOWN|BROKEN, "reason": ...}.
    UNKNOWN is never treated as healthy, and BROKEN never releases the number:
    a +353 took a regulator's approval to obtain and is not thrown away because
    a webhook is pointing at the wrong place.
    """
    from services import vapi

    e164 = str(row.get("e164") or "")
    provider_sid = str(row.get("provider_sid") or "")

    # ── 1..4: Twilio still holds this exact object, on this account ───────
    try:
        listing = await telephony.fetch_subaccount_numbers(sub_sid, sub_tok)
    except Exception as e:
        return {"state": UNKNOWN, "reason": f"provider_unreadable:{type(e).__name__}"}
    if not listing.ok:
        return {"state": UNKNOWN, "reason": "provider_unreadable"}

    held = {str(n.sid): n for n in listing.numbers}
    number = held.get(provider_sid)
    if number is None:
        # The SID we recorded is not on this account. That is an ownership
        # question, not a routing one, and it needs a human.
        return {"state": BROKEN, "reason": "provider_sid_not_on_subaccount"}
    if str(number.phone_number) != e164:
        return {"state": BROKEN, "reason": "provider_e164_mismatch"}
    caps = getattr(number, "capabilities", None) or {}
    voice = caps.get("voice") if isinstance(caps, dict) else getattr(caps, "voice", None)
    if voice is False:
        return {"state": BROKEN, "reason": "no_voice_capability"}

    # ── 5: the voice route points at us ───────────────────────────────────
    voice_url = str(getattr(number, "voice_url", "") or "")
    voice_app = str(getattr(number, "voice_application_sid", "") or "")
    if not (voice_url or voice_app):
        # Nothing is configured. Repairable: re-importing is idempotent.
        return {"state": REPAIRABLE, "reason": "no_voice_route_configured"}

    # ── 6..9: Vapi holds this number, on THIS tenant's assistant ──────────
    assistant_id = str(tenant.get("vapi_assistant_id") or "")
    if not assistant_id:
        return {"state": BROKEN, "reason": "no_assistant_on_tenant"}
    try:
        records = await vapi.list_phone_numbers(api_key=vapi.get_tenant_vapi_key(tenant))
    except Exception as e:
        return {"state": UNKNOWN, "reason": f"vapi_unreadable:{type(e).__name__}"}

    mine = [r for r in (records or []) if str(r.get("number") or "") == e164]
    if not mine:
        return {"state": REPAIRABLE, "reason": "no_vapi_record_for_number"}
    if len(mine) > 1:
        # Two records for one number is an ambiguity we must not resolve by
        # picking: calls could land on either.
        return {"state": BROKEN, "reason": "multiple_vapi_records_for_number"}
    record = mine[0]
    if str(record.get("assistantId") or "") != assistant_id:
        # Pointing at SOME assistant, but not this tenant's. Repairing this
        # blindly could steal a number another tenant is routing, so it is a
        # cross-tenant question and stops here.
        return {"state": BROKEN, "reason": "vapi_record_maps_to_another_assistant"}

    # ── 10: our own record agrees with theirs ─────────────────────────────
    recorded = str(row.get("vapi_phone_number_id") or "")
    if recorded and recorded != str(record.get("id") or ""):
        return {"state": BROKEN, "reason": "canonical_vapi_id_mismatch"}

    return {"state": HEALTHY, "reason": "", "vapi_phone_number_id": str(record.get("id") or "")}


async def _repair(*, tenant: dict, row: dict, sub_sid: str, sub_tok: str) -> bool:
    """One bounded, idempotent attempt to fix what health said was repairable.

    Only ever re-imports the number onto the tenant's OWN assistant. It does not
    create assistants, move records between tenants, or touch anything it did not
    find missing -- a repair that can do more than restore the intended state is
    a second way to reach the wrong one.
    """
    from services import vapi
    try:
        await vapi.import_twilio_number(
            phone_number=str(row["e164"]), twilio_account_sid=sub_sid,
            twilio_auth_token=sub_tok,
            label=str(tenant.get("business_name") or "Open Lines"),
            server_url=f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended",
            api_key=vapi.get_tenant_vapi_key(tenant),
            assistant_id=str(tenant.get("vapi_assistant_id") or ""))
        return True
    except Exception as e:
        logger.error("activation repair failed for tenant %s: %s",
                     tenant.get("id"), type(e).__name__)
        return False


# ── Stage O: the one activation operation ─────────────────────────────────

async def activate_permanent_irish_number(tenant_id: str) -> dict:
    """Take this tenant's purchased +353 live, and everything that follows.

    Server-owned end to end. The caller names a tenant; it does not name a phone
    row, a provider SID, a subscription or a message. Safe to call again at any
    point: every step is either fenced or idempotent, and a second run after a
    partial one completes what is missing rather than repeating what is done.
    """
    tenant = await _tenant(tenant_id)
    if not tenant:
        return {"status": NOT_FOUND}

    country = str(tenant.get("business_country_code") or "").strip().upper()
    if not lifecycle_ob.needs_regulatory_clearance(country):
        # This path exists for regulated numbers. A CA/US row must never be
        # promoted through it -- its billing and messaging are different.
        return {"status": NOT_ELIGIBLE, "reason": "country_is_not_regulated"}

    rows = await db_phones.list_for_tenant(tenant_id)
    awaiting = [r for r in rows
                if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                and r.get("status") == lifecycle.STATUS_PROVISIONING]
    already = [r for r in rows
               if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
               and r.get("status") == lifecycle.STATUS_ACTIVE]

    if not awaiting:
        if already:
            # Already live. Finish whatever is still outstanding -- a previous run
            # may have promoted and then failed at billing or the email.
            return await _finish(tenant=tenant, row=already[0])
        return {"status": NOTHING_TO_ACTIVATE}

    row = awaiting[0]
    if not str(row.get("e164") or "").startswith("+353"):
        return {"status": NOT_ELIGIBLE, "reason": "not_an_irish_number"}
    if not (row.get("provider_sid") and row.get("provider_account_sid")):
        return {"status": NOT_ELIGIBLE, "reason": "missing_provider_identity"}

    sub_sid = str(tenant.get("twilio_subaccount_sid") or "")
    sub_tok = str(tenant.get("twilio_auth_token") or "")
    if not (sub_sid and sub_tok):
        return {"status": NOT_ELIGIBLE, "reason": "missing_twilio_credentials"}
    if str(row.get("provider_account_sid")) != sub_sid:
        return {"status": NOT_ELIGIBLE, "reason": "number_is_on_another_account"}

    # ── health, then one bounded repair, then health again ────────────────
    health = await health_check(tenant=tenant, row=row, sub_sid=sub_sid, sub_tok=sub_tok)
    if health["state"] == REPAIRABLE:
        if await _repair(tenant=tenant, row=row, sub_sid=sub_sid, sub_tok=sub_tok):
            health = await health_check(tenant=tenant, row=row,
                                        sub_sid=sub_sid, sub_tok=sub_tok)
    if health["state"] == UNKNOWN:
        # Not a failure and not a pass. Nothing changes.
        return {"status": HEALTH_UNKNOWN, "reason": health["reason"], "row": row}
    if health["state"] != HEALTHY:
        logger.error("permanent number for tenant %s failed its health check: %s",
                     tenant_id, health["reason"])
        return {"status": HEALTH_FAILED, "reason": health["reason"], "row": row}

    # ── PROMOTION: fenced on the exact identity health just verified ──────
    promoted = await db_phones.promote_permanent_cas(
        number_id=str(row["id"]), tenant_id=tenant_id, e164=str(row["e164"]),
        provider_sid=str(row["provider_sid"]),
        provider_account_sid=str(row["provider_account_sid"]))
    if not promoted:
        # Either another worker promoted it, or the row moved under us. Re-read
        # rather than assume which.
        fresh = await db_phones.get_by_id(str(row["id"]))
        if fresh and fresh.get("status") == lifecycle.STATUS_ACTIVE:
            return await _finish(tenant=tenant, row=fresh)
        logger.error("promotion fence matched nothing for tenant %s row %s",
                     tenant_id, row.get("id"))
        return {"status": PROMOTION_LOST, "row": fresh or row}

    logger.warning("PERMANENT NUMBER LIVE for tenant %s", tenant_id)
    return await _finish(tenant=tenant, row=promoted[0])


async def _finish(*, tenant: dict, row: dict) -> dict:
    """Everything that follows a live number: pointer, billing, notification.

    Separated so a second run reaches it without re-promoting. Each step reports
    its own outcome; NONE of them may undo the activation, because the phone is
    already ringing and taking it away to satisfy a bookkeeping failure would be
    the worst outcome available.
    """
    tenant_id = str(tenant["id"])
    e164 = str(row["e164"])
    steps: dict = {}

    # ── the legacy pointer, with onboarding, in one row write ─────────────
    mirrored = await db.mirror_permanent_number_fenced(tenant_id, e164)
    steps["scalar_mirrored"] = bool(mirrored)
    if not mirrored:
        current = (await _tenant(tenant_id) or {}).get("twilio_phone_number")
        if current != e164:
            # The tenant points at a DIFFERENT number. Not something to overwrite:
            # that line may be ringing. The canonical row stays active -- it is
            # the authority -- and this needs reconciliation.
            logger.error("tenant %s scalar points at another number after "
                         "promotion -- reconcile", tenant_id)
            return {"status": SCALAR_CONFLICT, "row": row, "steps": steps}
    tenant = await _tenant(tenant_id) or tenant

    # ── billing: only now, and never rolling the phone back ───────────────
    billing = await _ensure_trial(tenant)
    steps["billing"] = billing["status"]
    if billing["status"] not in (OK,):
        # The line works. Billing is retried; the number is not touched.
        return {"status": billing["status"], "row": row, "steps": steps,
                "reason": billing.get("reason")}
    tenant = await _tenant(tenant_id) or tenant

    # ── the customer is told, exactly once ────────────────────────────────
    notified = await ensure_activation_email(tenant=tenant, row=row)
    steps["notification"] = notified["status"]

    return {"status": OK, "row": row, "e164": e164, "steps": steps,
            "activated": True}


# ── Stage I/J: billing, after activation, exactly once ────────────────────

async def _ensure_trial(tenant: dict) -> dict:
    """The Ireland 7-day trial, created once and never before the line works.

    Reuses the Stripe Customer that /setup-card already created. This path
    NEVER creates a Customer: the duplicate-Customer defect in /setup-card is
    carried debt, and a second creation site would make it worse and harder to
    find. No customer means the billing prerequisite was never completed, which
    is a controlled state, not something to paper over by inventing one.
    """
    from services import subscriptions

    tenant_id = str(tenant["id"])
    if tenant.get("stripe_subscription_id"):
        # Local authority. Already done; a second run must not ask Stripe again.
        return {"status": OK, "reason": "already_subscribed"}

    customer_id = str(tenant.get("stripe_customer_id") or "")
    if not customer_id:
        logger.error("tenant %s reached activation with no Stripe customer -- "
                     "billing setup was never completed", tenant_id)
        return {"status": BILLING_SETUP_REQUIRED, "reason": "no_stripe_customer"}

    plan = str(tenant.get("subscription_plan") or "").strip()
    payment_method = await _default_payment_method(customer_id)
    if not (plan and payment_method):
        return {"status": BILLING_SETUP_REQUIRED,
                "reason": "no_plan" if not plan else "no_payment_method"}

    # RECONCILE BEFORE CREATE. Stripe's idempotency key is only remembered for
    # 24 hours, so it cannot be the sole durable proof: an activation retried a
    # day later would create a second subscription. Asking Stripe what this
    # customer already has is the check that does not expire.
    existing = await _existing_subscription(customer_id, tenant_id)
    if existing and existing["status"] == RECONCILE_UNKNOWN:
        # We could not find out what this customer already has. Creating now
        # risks a second trial; the phone stays live and this is retried.
        return {"status": BILLING_PENDING, "reason": "reconcile_unavailable"}
    if existing:
        await db.update_tenant(tenant_id, {"stripe_subscription_id": existing["id"],
                                           "subscription_status": existing["status"]})
        return {"status": OK, "reason": "adopted_existing_subscription"}

    created = await subscriptions.create_trial_subscription(
        tenant_id=tenant_id, plan=plan, customer_id=customer_id,
        payment_method_id=payment_method,
        email=str(tenant.get("email") or ""),
        business_name=str(tenant.get("business_name") or ""))
    if not created.get("ok"):
        # Ambiguous or failed. The phone stays live and this is retried; a blind
        # second create is how a customer ends up with two trials.
        return {"status": BILLING_PENDING, "reason": created.get("error")}
    return {"status": OK, "reason": "created"}


async def _default_payment_method(customer_id: str) -> str:
    """The card /setup-card attached, read from Stripe rather than stored."""
    try:
        import os, stripe
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if key:
            stripe.api_key = key
        cust = stripe.Customer.retrieve(customer_id)
        pm = ((getattr(cust, "invoice_settings", None) or {}) or {}).get(
            "default_payment_method")
        if pm:
            return str(pm)
        methods = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
        data = getattr(methods, "data", None) or []
        return str(data[0].id) if data else ""
    except Exception as e:
        logger.error("could not read a payment method for customer: %s", type(e).__name__)
        return ""


async def _existing_subscription(customer_id: str, tenant_id: str) -> dict | None:
    """A subscription this customer already has for this tenant, or None."""
    try:
        import os, stripe
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if key:
            stripe.api_key = key
        subs = stripe.Subscription.list(customer=customer_id, status="all", limit=20)
        for s in (getattr(subs, "data", None) or []):
            if str(getattr(s, "status", "")) in ("canceled", "incomplete_expired"):
                continue
            meta = getattr(s, "metadata", None) or {}
            if str(meta.get("tenant_id") or "") == tenant_id:
                return {"id": str(s.id), "status": str(getattr(s, "status", ""))}
    except Exception as e:
        logger.error("could not reconcile subscriptions before create: %s",
                     type(e).__name__)
        # UNKNOWN, which is not the same as "none". Returning None here would
        # have let the caller create a subscription on the strength of a failed
        # lookup -- the exact way a customer ends up with two trials.
        return {"id": "", "status": RECONCILE_UNKNOWN}
    return None


# ── Stage K: the activation email, exactly one logical event ──────────────

async def ensure_activation_email(*, tenant: dict, row: dict) -> dict:
    """Tell the customer their number is live. One logical event per phone row.

    The DB claim decides which worker sends; the provider's idempotency key
    ensures that even a second attempt at the same event delivers once. Failure
    here NEVER touches the phone -- it is already live, and the customer having
    to be told twice is better than a working line being taken away.
    """
    from services import email as mail

    row_id = str(row["id"])
    if row.get("activation_email_sent_at"):
        return {"status": OK, "reason": "already_sent", "sent": False}

    claimed_at = row.get("activation_email_claimed_at")
    if claimed_at:
        age = _age_seconds(claimed_at)
        if notify.stale_claim_outcome(age) != notify.TAKEOVER_SAFE:
            # Beyond the provider's memory. It may have been delivered and the
            # acknowledgement lost; resending would be a second customer email on
            # a guess.
            logger.error("activation notification for row %s is unresolved beyond "
                         "the safe window -- review required", row_id)
            return {"status": notify.NEEDS_REVIEW, "sent": False}
        # Inside the window: the same key and body make a retry safe.
    else:
        if not await db_phones.claim_activation_email(row_id):
            # Another worker holds it. One event, one sender.
            return {"status": OK, "reason": "claimed_by_another_worker", "sent": False}

    recipient = str(tenant.get("notification_email") or tenant.get("email") or "").strip()
    if not recipient:
        return {"status": notify.NEEDS_REVIEW, "reason": "no_recipient", "sent": False}

    try:
        body = notify.payload(recipient=recipient, e164=str(row["e164"]))
    except ValueError as e:
        return {"status": notify.NEEDS_REVIEW, "reason": str(e), "sent": False}

    key = notify.idempotency_key(tenant_id=str(tenant["id"]), phone_row_id=row_id)
    html = _activation_html(body["e164"])
    outcome = mail.send_with_outcome(
        to=body["to"], subject=body["subject"], html_body=html,
        idempotency_key=key)

    verdict = notify.classify(outcome.get("error"))
    if outcome["ok"] or verdict == notify.SENT:
        await db_phones.confirm_activation_email(row_id, outcome.get("provider_id") or "")
        logger.info("activation email accepted for row %s", row_id)
        return {"status": OK, "sent": True}

    if verdict == notify.INVALID:
        # Same key, different body. Retrying cannot deliver it.
        logger.error("activation email for row %s is wedged: the payload changed "
                     "under a used idempotency key", row_id)
        return {"status": notify.NEEDS_REVIEW, "reason": "payload_changed", "sent": False}
    if verdict == notify.FATAL:
        # Nothing went out and nothing will until configuration changes. Release
        # the claim so a later run can try cleanly.
        await db_phones.release_activation_email_claim(row_id)
        return {"status": notify.NEEDS_REVIEW, "reason": "provider_refused", "sent": False}

    # CONCURRENT or RETRYABLE. The claim is KEPT: a timeout may have delivered,
    # and releasing it would let another worker send outside the provider's
    # deduplication window.
    return {"status": EMAIL_PENDING, "sent": False}


def _age_seconds(stamp) -> float:
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds()
    except Exception:
        # An unparseable timestamp is not evidence the claim is fresh.
        return float("inf")


def _activation_html(e164: str) -> str:
    """The message body. Depends on the number and nothing else that can move."""
    return (
        f"<p>Your Irish OpenLines number is ready 🇮🇪</p>"
        f"<p>Your number <strong>{e164}</strong> has been approved and activated.</p>"
        f"<p>Your AI receptionist is now answering calls on this number.</p>")


# ── Stage M: the temporary line after promotion ───────────────────────────

def temporary_retirement_state(rows: list[dict]) -> dict:
    """Whether the temporary line may be retired yet, and whether to act.

    DELIBERATELY NOT A TIMER. The grace duration is an unresolved product
    question, and defaulting it -- to the trial's seven days, say, which is an
    unrelated number that happens to be nearby -- would quietly make that the
    policy. Eligibility is reported; retirement waits for a decision.
    """
    temp = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_TEMPORARY
            and r.get("status") in lifecycle.LIVE_TEMPORARY_STATUSES]
    perm_active = [r for r in rows if r.get("purpose") == lifecycle.PURPOSE_PERMANENT
                   and r.get("status") == lifecycle.STATUS_ACTIVE]
    if not temp:
        return {"has_temporary": False, "eligible": False,
                "reason": "no_live_temporary_number"}
    if not perm_active:
        return {"has_temporary": True, "eligible": False,
                "reason": "permanent_number_not_active_yet", "row": temp[0]}
    return {"has_temporary": True, "eligible": True,
            "reason": "awaiting_grace_policy", "row": temp[0]}


# ── Stage Q: what the customer sees ───────────────────────────────────────

HEALTH_CHECKING = "PERMANENT_NUMBER_HEALTH_CHECK"
NEEDS_REVIEW_STATE = "PERMANENT_NUMBER_NEEDS_REVIEW"
ACTIVE_STATE = "PERMANENT_NUMBER_ACTIVE"
BILLING_SETUP = "BILLING_SETUP_REQUIRED"
TRIAL_STARTING = "TRIAL_STARTING"
ACTIVATED = "ACTIVATED"
TEMP_RETIRING = "TEMPORARY_NUMBER_RETIRING"

_MESSAGE = {
    HEALTH_CHECKING: "We are running the final checks on your number.",
    NEEDS_REVIEW_STATE: "Your number needs a manual check. Our team is on it.",
    ACTIVE_STATE: "Your number is live.",
    BILLING_SETUP: "We need your payment details before your trial can start.",
    TRIAL_STARTING: "Your number is live and we are starting your trial.",
    ACTIVATED: "Your Irish number is live and your receptionist is answering it.",
    TEMP_RETIRING: "Your temporary test number will be switched off shortly.",
}

_STATUS_VIEW = {
    OK: ACTIVATED,
    HEALTH_UNKNOWN: HEALTH_CHECKING,
    HEALTH_FAILED: NEEDS_REVIEW_STATE,
    PROMOTION_LOST: HEALTH_CHECKING,
    SCALAR_CONFLICT: NEEDS_REVIEW_STATE,
    BILLING_SETUP_REQUIRED: BILLING_SETUP,
    BILLING_PENDING: TRIAL_STARTING,
    NOTHING_TO_ACTIVATE: HEALTH_CHECKING,
    NOT_ELIGIBLE: HEALTH_CHECKING,
    NOT_FOUND: NEEDS_REVIEW_STATE,
    notify.NEEDS_REVIEW: ACTIVE_STATE,
    EMAIL_PENDING: ACTIVE_STATE,
}


def customer_status(result_status: str, row: dict | None = None) -> dict:
    """One activation outcome, as a person sees it.

    Carries no Twilio SID, Stripe customer or subscription id, Vapi id or
    provider error. A notification that needs review does NOT read as a failure:
    the customer's number is live, which is the thing they care about, and the
    email is our problem to fix.
    """
    status = _STATUS_VIEW.get(str(result_status or ""), HEALTH_CHECKING)
    out = {"status": status, "message": _MESSAGE[status],
           "active": status in (ACTIVE_STATE, ACTIVATED)}
    if out["active"] and row and row.get("e164"):
        out["number"] = row["e164"]
    return out
