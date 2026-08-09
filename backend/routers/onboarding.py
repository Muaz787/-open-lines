import logging
import os
import re
from typing import Annotated, Literal
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, field_validator

from db import supabase as db
from services import analytics, provisioning, subscriptions, telephony, vapi, website_analysis
from services.ratelimit import limiter
from services.security import validate_public_url, validate_business_instructions, verify_tenant_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def card_required() -> bool:
    """Whether a signup must supply a card before we provision anything.

    Read live so it can be flipped without a deploy, and OFF by default so the
    backend can ship ahead of the onboarding UI that collects the card: until the
    frontend sends these fields, signups behave exactly as they do today. Turning
    it on is the switch that makes the trial card-required.
    """
    return os.getenv("TRIAL_REQUIRE_CARD", "false").strip().lower() in ("1", "true", "yes", "on")


VALID_INDUSTRIES = {
    "realtor", "clinic", "parliament",
    "plumber", "restaurant", "builder", "dental", "legal", "beauty",
    "automotive", "insurance", "public_office", "courier",
    "custom",
}

# Secret/credential fields stripped before returning tenant data over the API.
# Service-role queries return the full row, so this is the last line of defence
# against leaking tokens, refresh tokens, and the raw system prompt.
_SENSITIVE = {
    "twilio_auth_token", "twilio_subaccount_sid",
    "google_refresh_token", "microsoft_refresh_token",
    "hubspot_access_token", "hubspot_refresh_token",
    "square_access_token", "square_refresh_token",
    "vapi_suborg_api_key", "vapi_suborg_id",
    "slack_webhook_url", "last_system_prompt", "custom_prompt_base",
}


def _sanitize_tenant(tenant: dict) -> dict:
    return {k: v for k, v in (tenant or {}).items() if k not in _SENSITIVE}


class ProvisionRequest(BaseModel):
    business_name: str
    industry: str
    owner_name: str = ""
    country: str = "CA"
    website_url: str = ""
    agent_name: str = "Alex"
    voice_gender: str = "female"   # used when agent_name is a custom name
    extra_instructions: str = ""
    business_description: str = ""
    business_subtype: str = ""
    receptionist_tone: str = ""
    operating_priorities: list[str] = []
    email: str = ""
    password: str = ""
    business_phone: str = ""
    analysis_token: str = ""
    # Card-required trial. card_setup_token comes from /onboarding/setup-card and
    # carries the Stripe customer id in authenticated encryption — the raw id is
    # never accepted from the client, because this endpoint is unauthenticated.
    plan: str = ""
    card_setup_token: str = ""
    payment_method_id: str = ""
    address: dict | None = None
    billing_name: str = ""

    @field_validator("plan")
    @classmethod
    def plan_must_be_valid(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v and v not in subscriptions.PRICE_IDS:
            raise ValueError(f"plan must be one of {sorted(subscriptions.PRICE_IDS)}")
        return v

    @field_validator("industry")
    @classmethod
    def industry_must_be_valid(cls, v: str) -> str:
        if v not in VALID_INDUSTRIES:
            raise ValueError(f"industry must be one of {sorted(VALID_INDUSTRIES)}")
        return v

    @field_validator("business_name")
    @classmethod
    def business_name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("business_name cannot be empty")
        return v.strip()


class AnalyzeWebsiteRequest(BaseModel):
    website_url: str
    email: str = ""


@router.post("/analyze-website")
@limiter.limit("10/hour")
async def analyze_website(request: Request, body: AnalyzeWebsiteRequest):
    """Scrape + classify a business website so the UI can demonstrate value
    before provisioning. Returns detected fields + an analysis_token that the
    /provision call reuses to avoid scraping twice."""
    url = body.website_url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        validate_public_url(url)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Please enter a valid website URL")

    try:
        result = await website_analysis.analyze_website(url)
    except Exception as e:
        logger.error("analyze-website failed for %s: %s", url, e)
        raise HTTPException(status_code=502, detail="We couldn't analyse that website. You can continue and fill in the details manually.")

    result["website_url"] = url

    analytics.capture(
        body.email or url,
        "website_analysis_succeeded" if result.get("scrape_ok") else "website_analysis_failed",
        {
            "industry_detected": result.get("industry"),
            "services_count": len(result.get("services") or []),
            "faq_count": result.get("faq_count", 0),
            "scrape_ok": result.get("scrape_ok"),
        },
    )
    return result


class SetupCardRequest(BaseModel):
    plan: str
    email: str = ""
    business_name: str = ""

    @field_validator("plan")
    @classmethod
    def plan_must_be_valid(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in subscriptions.PRICE_IDS:
            raise ValueError(f"plan must be one of {sorted(subscriptions.PRICE_IDS)}")
        return v


@router.post("/setup-card")
@limiter.limit("10/hour")
async def setup_card(request: Request, body: SetupCardRequest):
    """Create a Stripe Customer + SetupIntent so the signup can enter a card
    BEFORE we provision anything. No charge is made here — the card is validated
    and stored, then billed only when the 7-day trial ends.

    ABUSE: this is a public endpoint that mints SetupIntents, which is a known
    card-testing vector — an attacker can drive confirmations against it to check
    stolen card numbers. Three things hold it down:
      * the IP rate limit above,
      * a valid plan + a plausible email, so it is not a bare oracle,
      * Stripe Radar's card-testing rules, which must be enabled in the Dashboard
        (see docs/stripe-go-live.md) — they are what actually blocks a distributed
        attempt, since rate limiting alone only slows a single source.
    """
    import stripe

    email = (body.email or "").strip()
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address")

    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key:
        logger.error("setup-card: STRIPE_SECRET_KEY not configured")
        raise HTTPException(status_code=503, detail="Payments are not available right now")
    stripe.api_key = key

    try:
        params: dict = {"metadata": {"signup_plan": body.plan, "source": "onboarding"}}
        if email:
            params["email"] = email
        if body.business_name.strip():
            params["name"] = body.business_name.strip()[:200]
        customer = stripe.Customer.create(**params)

        si = stripe.SetupIntent.create(
            customer=customer.id,
            payment_method_types=["card"],
            # The card is charged later, with nobody at the keyboard, so the
            # mandate has to be set up for off-session use now.
            usage="off_session",
            metadata={"signup_plan": body.plan, "source": "onboarding"},
        )
    except Exception as e:
        logger.error("setup-card: Stripe failed (plan=%s): %s", body.plan, e)
        raise HTTPException(status_code=502, detail="We couldn't start the payment step. Please try again.")

    analytics.capture(email or customer.id, "card_setup_started", {"plan": body.plan})

    return {
        "client_secret":    si.client_secret,
        "card_setup_token": subscriptions.issue_card_setup_token(customer.id),
    }


@router.post("/provision")
@limiter.limit("3/hour")
async def provision(request: Request, body: ProvisionRequest):
    import time
    # Reject prompt-injection / unsafe-use directives in tenant free-text before they
    # ever reach the assistant's system prompt.
    validate_business_instructions(body.extra_instructions, field="extra instructions")
    validate_business_instructions(body.business_description, field="business description")

    # Resolve the card BEFORE provisioning. Everything below buys a real phone
    # number and creates a Vapi assistant, so a bad payment session must fail here
    # rather than after we have spent money on the tenant.
    stripe_customer_id = ""
    if body.card_setup_token:
        try:
            stripe_customer_id = subscriptions.read_card_setup_token(body.card_setup_token)
        except Exception as e:
            logger.warning("provision: rejected card setup token (%s)", e)
            raise HTTPException(
                status_code=400,
                detail="Your payment session expired. Please re-enter your card details.",
            )

    has_card = bool(stripe_customer_id and body.payment_method_id and body.plan)
    if card_required() and not has_card:
        raise HTTPException(
            status_code=400,
            detail="A plan and payment method are required to start your free trial",
        )

    _started = time.monotonic()
    try:
        provision_data = body.model_dump(exclude={
            "email", "password",
            # Billing inputs are consumed here, not by the provisioner, and must
            # never end up on the tenant row.
            "plan", "card_setup_token", "payment_method_id", "address", "billing_name",
        })
        result = await provisioning.provision_tenant(provision_data)
        _duration_ms = int((time.monotonic() - _started) * 1000)
        logger.info("Provisioned tenant %s (%s) in %dms", result.get("tenant_id"), body.business_name, _duration_ms)

        distinct_id = result.get("tenant_id", "")
        if body.email and body.password:
            try:
                user_id = await db.create_auth_user(body.email, body.password, result["tenant_id"])
                # Default email call-summaries ON, sent to the owner's account email
                # (matches the marketing promise; tenant can change/disable in Settings).
                await db.update_tenant(result["tenant_id"], {
                    "user_id":             user_id,
                    "email":               body.email,
                    "notification_email":  body.email,
                    "email_enabled":       True,
                })
                logger.info("Created auth user for tenant %s", result["tenant_id"])
                distinct_id = user_id
            except Exception as e:
                logger.error("Auth user creation failed for tenant %s: %s", result.get("tenant_id"), e)

        # Start the trial subscription LAST, once the line actually exists. Doing
        # it here rather than before provisioning means a provisioning failure can
        # never leave a subscription attached to a tenant that does not work.
        #
        # Non-fatal by design: the tenant has a working AI receptionist at this
        # point, so a Stripe outage must not fail the signup. They fall back to
        # the card-free derived trial (services/trial) and keep a live line; the
        # error below is the signal to reconcile them.
        trial_sub: dict = {}
        if has_card:
            trial_sub = await subscriptions.create_trial_subscription(
                tenant_id=result["tenant_id"],
                plan=body.plan,
                customer_id=stripe_customer_id,
                payment_method_id=body.payment_method_id,
                email=body.email,
                business_name=body.billing_name.strip() or body.business_name,
                address=subscriptions.clean_address(body.address),
            )
            if trial_sub.get("ok"):
                analytics.capture(distinct_id, "trial_started", {
                    "tenant_id": result.get("tenant_id"),
                    "plan": body.plan,
                    "trial_ends_at": trial_sub.get("trial_ends_at"),
                })
            else:
                logger.error(
                    "TRIAL SUBSCRIPTION FAILED for tenant %s (plan=%s, customer=%s, error=%s) "
                    "— tenant is live on the card-free fallback trial and needs reconciling",
                    result.get("tenant_id"), body.plan, stripe_customer_id, trial_sub.get("error"),
                )
                analytics.capture(distinct_id, "trial_subscription_failed", {
                    "tenant_id": result.get("tenant_id"),
                    "plan": body.plan,
                    "error": trial_sub.get("error"),
                })

        if body.email and body.password:
            # Welcome email — non-fatal; the tenant is already provisioned.
            try:
                from services.email import send_welcome_email
                await send_welcome_email(
                    to=body.email,
                    business_name=body.business_name,
                    tenant_id=result["tenant_id"],
                    phone_number=result.get("phone_number", ""),
                )
            except Exception as e:
                logger.error("Welcome email failed for tenant %s: %s", result.get("tenant_id"), e)

        # PRIVACY: business metadata only — no phone numbers, no credentials
        common = {
            "tenant_id": result.get("tenant_id"),
            "business_name": body.business_name,
            "industry": body.industry,
            "country": body.country,
        }
        analytics.capture(distinct_id, "tenant_created", common)
        analytics.capture(distinct_id, "phone_number_provisioned", {"tenant_id": result.get("tenant_id")})
        analytics.capture(distinct_id, "provision_succeeded", {**common, "duration_ms": _duration_ms})
        if body.email:
            analytics.capture(distinct_id, "signup_completed", common)

        # Let the success screen state the exact charge date without a second
        # round-trip. Absent when the tenant fell back to the card-free trial.
        if trial_sub.get("ok"):
            result["trial"] = {
                "plan":          trial_sub.get("plan"),
                "status":        trial_sub.get("status"),
                "trial_ends_at": trial_sub.get("trial_ends_at"),
            }

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error provisioning '%s': %s", body.business_name, e)
        raise HTTPException(status_code=500, detail="Provisioning failed unexpectedly")


class SettingsUpdateRequest(BaseModel):
    notification_email:   str | None = None
    email_enabled:        bool | None = None
    sms_enabled:          bool | None = None
    whatsapp_enabled:     bool | None = None
    business_phone:       str | None = None
    sms_alert_number:     str | None = None
    business_hours_start: int | None = None
    business_hours_end:   int | None = None
    business_days:        list[int] | None = None
    break_start:          int | None = None
    break_end:            int | None = None
    booking_instructions: str | None = None
    auto_recrawl_enabled: bool | None = None
    slot_capacity:        int | None = None
    # Owner operating layer (editable business profile + instructions).
    extra_instructions:   str | None = None
    business_subtype:     str | None = None
    receptionist_tone:    str | None = None
    operating_priorities: list[str] | None = None

    @field_validator("slot_capacity")
    @classmethod
    def _valid_capacity(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 1 or v > 50:
            raise ValueError("slot_capacity must be between 1 and 50")
        return v

    @field_validator("business_phone", "sms_alert_number")
    @classmethod
    def _clean_phone(cls, v: str | None) -> str | None:
        # Permissive: allow +, digits, spaces, dashes, parentheses. Empty -> null
        # so the tenant can clear it. Reject anything obviously not a phone number.
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if len(v) > 32 or not re.fullmatch(r"[+]?[0-9 ()\-.]{6,32}", v):
            raise ValueError("Enter a valid phone number")
        # Store E.164 so SMS/WhatsApp sends work (formatting breaks 'whatsapp:<num>').
        return telephony.normalize_phone(v)


@router.patch("/settings/{tenant_id}")
async def update_settings(
    tenant_id: str,
    body: SettingsUpdateRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    await verify_tenant_owner(tenant_id, authorization)
    # exclude_unset (not exclude_none) so callers can explicitly clear a field by
    # sending null — needed to remove the daily break (break_start/break_end = null).
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided")
    # Owner-supplied free text is injected into the prompt — validate for
    # prompt-injection / unsafe-use before it can reach the assistant.
    if update_data.get("booking_instructions"):
        validate_business_instructions(update_data["booking_instructions"], field="booking instructions")
    if update_data.get("extra_instructions"):
        validate_business_instructions(update_data["extra_instructions"], field="business instructions")

    try:
        updated = await db.update_tenant(tenant_id, update_data)
    except Exception as e:
        logger.error("Settings update failed for tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Settings update failed")

    # Rebuild + push the prompt when an owner-operating-layer field changed.
    # Non-fatal: the settings save itself already succeeded.
    _PROMPT_FIELDS = {"extra_instructions", "business_subtype", "receptionist_tone", "operating_priorities"}
    if _PROMPT_FIELDS & update_data.keys() and updated and updated.get("vapi_assistant_id"):
        try:
            from services.provisioning import rebuild_and_push_system_prompt
            await rebuild_and_push_system_prompt(updated)
        except Exception as e:
            logger.warning("Prompt rebuild after settings update failed for tenant %s (non-fatal): %s", tenant_id, e)

    return _sanitize_tenant(updated)


@router.get("/status/{tenant_id}")
async def onboarding_status(tenant_id: str, authorization: Annotated[str | None, Header()] = None):
    await verify_tenant_owner(tenant_id, authorization)
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        logger.error("Tenant lookup failed for %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Tenant lookup failed")

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from services import trial
    return {**_sanitize_tenant(tenant), "trial": trial.trial_status(tenant)}


@router.post("/admin-reprompt/{tenant_id}")
async def admin_reprompt(
    tenant_id: str,
    x_admin_key: Annotated[str | None, Header()] = None,
):
    """Rebuild and push system prompt + patch Vapi assistant config for a tenant.
    Secured with VAPI_API_KEY as admin key (backend-only operation).
    """
    if x_admin_key != os.getenv("VAPI_API_KEY", ""):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    assistant_id = tenant.get("vapi_assistant_id")
    if not assistant_id:
        raise HTTPException(status_code=400, detail="No Vapi assistant on this tenant")

    # 1 — Patch top-level Vapi assistant config (endCallMessage, silence timeout)
    try:
        await vapi.update_assistant(assistant_id, {
            "endCallMessage": "",
            "silenceTimeoutSeconds": 10,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vapi assistant patch failed: {e}")

    # 2 — Rebuild system prompt from template + KB and push to Vapi
    if tenant.get("industry") == "custom":
        return {"status": "config_patched_only", "note": "Custom industry — prompt not rebuilt"}
    try:
        result = await provisioning.rebuild_and_push_system_prompt(tenant)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt rebuild failed: {e}")

    return {"status": "reprompted", **result}


@router.post("/repair-phone-url/{tenant_id}")
async def repair_phone_url(
    tenant_id: str,
    x_admin_key: Annotated[str | None, Header()] = None,
):
    """Patch the Vapi phone number for this tenant to include the correct serverUrl.

    This enables smart routing (assistant-request webhook) so date injection,
    caller recognition, and personalized greetings work on every call.
    Falls back to searching Vapi's phone list by E.164 number if the Vapi
    phone number ID isn't stored (covers tenants provisioned before this fix).
    """
    if x_admin_key != os.getenv("ADMIN_API_KEY", "") or not os.getenv("ADMIN_API_KEY", ""):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        tenant = await db.get_tenant_by_id(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tenant lookup failed: {e}")
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    twilio_phone = tenant.get("twilio_phone_number", "")
    vapi_phone_id = tenant.get("vapi_phone_number_id", "")
    server_url = f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended"

    # If we don't have the ID stored, search Vapi's list by E.164 number
    if not vapi_phone_id:
        try:
            numbers = await vapi.list_phone_numbers()
            for pn in numbers:
                if pn.get("number") == twilio_phone:
                    vapi_phone_id = pn.get("id", "")
                    break
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Vapi phone list failed: {e}")

    if not vapi_phone_id:
        raise HTTPException(status_code=404, detail=f"Could not find Vapi phone number for {twilio_phone}")

    try:
        await vapi.update_phone_number(vapi_phone_id, vapi.server_block(server_url))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vapi PATCH failed: {e}")

    # Persist the ID so future repairs are instant
    await db.update_tenant(tenant_id, {"vapi_phone_number_id": vapi_phone_id})

    logger.info("Repaired serverUrl for tenant %s phone %s (%s)", tenant_id, twilio_phone, vapi_phone_id)
    return {"status": "repaired", "vapi_phone_id": vapi_phone_id, "server_url": server_url}
