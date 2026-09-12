import os
import re
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import HTTPException
from openai import AsyncOpenAI

from services import onboarding_lifecycle as lifecycle_ob
from services import phone_registry
from services import telephony, vapi, knowledge
from db import supabase as db

load_dotenv()

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

# Placeholder for the (refreshable) KB inside a stored custom prompt base. We
# string-replace it (never str.format) so GPT-authored braces can't break it.
KB_SENTINEL = "[[KNOWLEDGE_CONTEXT]]"

QUALIFICATION_FIELDS = {
    "realtor": {
        "budget": "What is your approximate budget for the property?",
        "pre_approved": "Have you been pre-approved for a mortgage?",
        "timeline": "When are you looking to buy or move?",
    },
    "clinic": {
        "patient_type": "Are you an existing patient or a new patient?",
        "symptoms": "Can you briefly describe what you're experiencing or the reason for your visit?",
        "urgency": "How long have you been experiencing this? Is this urgent or routine?",
    },
    "parliament": {
        "issue_type": "What is the nature of your inquiry — casework, a general question, or something else?",
        "constituency": "Can I confirm your home address and postal code so we can route your file correctly?",
        "callback_time": "What is the best time of day to reach you if someone needs to call back?",
    },
    "plumber": {
        "issue": "Can you describe the problem — is it a leak, a blockage, heating, or something else?",
        "address": "What is the address for the job?",
        "urgency": "How urgent is this — is it an emergency or can it wait for a scheduled appointment?",
    },
    "restaurant": {
        "party_size": "How many people will be dining?",
        "date_time": "What date and time were you thinking?",
        "special_requests": "Do you have any dietary requirements or special requests we should note?",
    },
    "builder": {
        "project_type": "What type of project is it — a new build, renovation, extension, or something else?",
        "timeline": "What is your rough timeline — when are you hoping to start?",
        "budget": "Do you have a budget range in mind for the project?",
    },
    "dental": {
        "patient_type": "Are you a current patient with us, or would this be your first visit?",
        "reason": "What is the reason for your visit — is it a check-up, a specific concern, or something else?",
        "urgency": "Are you experiencing any pain or discomfort right now?",
    },
    "legal": {
        "matter_type": "What area of law does your matter relate to — for example, family, real estate, corporate, or something else?",
        "urgency": "Is there any deadline or upcoming date we should be aware of?",
        "new_or_existing": "Have you worked with us before, or would this be a new matter?",
    },
    "beauty": {
        "service": "What service are you looking to book — a haircut, colour, treatment, or something else?",
        "preferred_time": "Do you have a preferred day or time?",
        "stylist": "Do you have a preferred stylist or therapist, or are you happy with whoever is available?",
    },
    "automotive": {
        "reason": "Are you calling about buying or selling a vehicle, service and repairs, or body/collision work?",
        "vehicle": "What's the year, make, and model of the vehicle?",
        "details": "What's the issue or what are you looking for, and how soon do you need it?",
    },
    "insurance": {
        "insurance_type": "What type of insurance is this about — auto, home, life, business, or something else?",
        "request_type": "Is this a new quote, a change to an existing policy, or a claim?",
        "client_status": "Are you a current client with us, or would this be new?",
    },
    "public_office": {
        "inquiry_type": "What is your inquiry about — casework or help with a personal issue, a comment on an issue, an event, or something else?",
        "address": "So we can route your file to the right team, can I confirm your home address and postal code?",
        "callback_time": "What's the best time of day to reach you if someone needs to call back?",
    },
    "courier": {
        "request_type": "Is this a new pickup or delivery, a quote, or a question about an existing order?",
        "locations": "What are the pickup and drop-off addresses?",
        "details": "What's being delivered — roughly the size or type — and how soon do you need it?",
    },
}


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug


def _load_template(industry: str) -> str:
    path = TEMPLATES_DIR / f"{industry}.txt"
    if not path.exists():
        raise ValueError(f"No system prompt template found for industry '{industry}'")
    return path.read_text(encoding="utf-8")


async def rebuild_and_push_system_prompt(tenant: dict) -> dict:
    """Rebuild the system prompt from the current KB and push it to the Vapi assistant.

    Returns {"status": "updated", "assistant_id": str} on success.
    Raises ValueError for missing/unsupported config, RuntimeError for downstream failures.
    """
    from services.vapi import _CALLER_LOOKUP_NOTE, update_assistant, build_calendar_tools, build_caller_lookup_tool
    from routers.calendar import _CALENDAR_NOTE

    tenant_id     = tenant["id"]
    industry      = tenant.get("industry", "")
    business_name = tenant["business_name"]
    agent_name    = tenant.get("agent_name", "Alex")
    assistant_id  = tenant.get("vapi_assistant_id")

    if not assistant_id:
        raise ValueError("Tenant has no Vapi assistant")

    # Fetch fresh structured KB (raw for regeneration context, wrapped for the prompt).
    structured_raw = ""
    knowledge_context = "No website content available."
    try:
        pinecone_namespace = tenant.get("pinecone_namespace", "")
        if pinecone_namespace:
            structured_raw = await knowledge.build_structured_knowledge(
                pinecone_namespace, business_brief=tenant.get("business_brief") or ""
            ) or ""
            if structured_raw:
                knowledge_context = vapi.wrap_untrusted_kb(structured_raw)
    except Exception as e:
        logger.warning("KB fetch failed during reprompt for tenant %s (continuing): %s", tenant_id, e)

    # Industry body: custom tenants reuse their stored base (KB refreshed); the
    # rest render their industry template. Custom is no longer frozen.
    if industry == "custom":
        industry_body = await _custom_body(tenant, knowledge_context, structured_raw)
    else:
        template = _load_template(industry)
        qualification_fields    = QUALIFICATION_FIELDS.get(industry, {})
        qualification_questions = "\n".join(f"- {q}" for q in qualification_fields.values())
        industry_body = template.format(
            business_name=business_name,
            agent_name=agent_name,
            qualification_questions=qualification_questions,
            knowledge_context=knowledge_context,
        )

    # Owner operating layer (subtype/tone/priorities/editable instructions) sits
    # above the industry body; safety preamble is prepended later.
    owner_layer = _owner_layer_block(
        tenant.get("business_subtype"),
        tenant.get("receptionist_tone"),
        tenant.get("operating_priorities"),
        tenant.get("extra_instructions"),
    )
    system_prompt = owner_layer + industry_body

    base_system_prompt = system_prompt

    system_prompt += _CALLER_LOOKUP_NOTE
    _has_booking = bool(
        tenant.get("google_refresh_token") or tenant.get("microsoft_refresh_token")
        or tenant.get("square_appointments_enabled")
    )
    if _has_booking:
        system_prompt += _CALENDAR_NOTE

    # Named-staff roster — tell the AI how to capture, match, and CONFIRM a
    # caller-requested team member (avoids mis-spelled / wrong assignments).
    try:
        _staff = await db.get_active_staff(tenant_id)
    except Exception:
        _staff = []
    if _staff:
        _roster = ", ".join(s["name"] for s in _staff)
        _example = _staff[0]["name"]
        system_prompt += (
            f"\n\nTEAM MEMBERS\n"
            f"This business has multiple team members: {_roster}.\n"
            f"- If the caller asks to book with a specific person, pass that name in the `staff` "
            f"argument of check_availability and book_appointment (exactly as the caller said it — the "
            f"backend matches it to the roster above, correcting minor mis-hearings).\n"
            f"- ALWAYS confirm the team member's name back to the caller before booking, e.g. "
            f"\"Just to confirm, that's with {_example}?\".\n"
            f"- If you're unsure who they mean, ask and offer the names above. Do NOT guess.\n"
            f"- Never put a person's name in the `service` field.\n"
            f"- If the caller has no preference, omit `staff` and the system assigns whoever is free."
        )

    # Square Appointments — offer exactly the services synced from the merchant's
    # Square catalog so the AI uses names that map cleanly to a bookable service.
    if tenant.get("square_appointments_enabled"):
        try:
            _sq_services = await db.get_square_services(tenant_id, bookable_only=True)
        except Exception:
            _sq_services = []
        if _sq_services:
            _names = ", ".join(s["name"] for s in _sq_services if s.get("name"))
            system_prompt += (
                f"\n\nSERVICES (Square Appointments)\n"
                f"Offer only these bookable services: {_names}.\n"
                f"- Pass the caller's chosen service in the `service` argument exactly; the backend "
                f"matches it to the list above.\n"
                f"- Availability is read live from the business's Square calendar."
            )

    # W4: multi-location tenants learn their own location NAMES (never ids) so the
    # assistant can ask which one before checking availability. Empty string for a
    # single-location tenant, so their prompt is byte-identical to before.
    try:
        from services import call_location
        system_prompt += await call_location.location_prompt_block_for(tenant)
    except Exception as e:
        logger.warning("Location prompt block failed for %s: %s", tenant_id, e)

    tools = (
        build_calendar_tools(tenant_id)
        if _has_booking
        else [build_caller_lookup_tool(tenant_id)]
    )
    model_payload: dict = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "temperature": 0.8,
        "messages": [{"role": "system", "content": vapi.ensure_receptionist_style(
            vapi.ensure_safety_preamble(system_prompt))}],
        "tools": tools,
    }

    tenant_key = vapi.get_tenant_vapi_key(tenant)
    try:
        await update_assistant(assistant_id, {"model": model_payload}, api_key=tenant_key)
        logger.info("Reprompted assistant %s for tenant %s", assistant_id, tenant_id)
    except Exception as e:
        raise RuntimeError(f"Vapi assistant update failed: {e}") from e

    try:
        await db.update_tenant(tenant_id, {"last_system_prompt": base_system_prompt})
    except Exception as e:
        logger.warning("Could not store last_system_prompt for tenant %s: %s", tenant_id, e)

    return {"status": "updated", "assistant_id": assistant_id}


async def _generate_custom_content(
    business_name: str,
    agent_name: str,
    business_description: str,
    knowledge_context: str,
) -> tuple[str, dict]:
    """Generate a custom receptionist script (with a refreshable KB slot) and 3
    qualification questions for an 'Other' business.

    The returned script contains the KB_SENTINEL token where reference knowledge
    is injected, so this base can be stored and refreshed on later rebuilds
    instead of regenerating from scratch every time. Owner instructions are NOT
    baked in here — they live in the higher-precedence owner layer."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY must be set for custom industry provisioning")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    kb_for_context = (knowledge_context or "").strip()[:6000]

    user_prompt = f"""Write a complete AI phone receptionist script for this business:

Business name: {business_name}
Business type / description: {business_description}
AI agent name: {agent_name}

The script MUST follow this exact structure:
1. PERSONALITY section — 3-4 bullet points describing tone and approach
2. GOAL — 1-2 sentences stating the objective of every call
3. CONVERSATION FLOW with these numbered steps:
   Step 1 — Greet and Capture Name: use a greeting that includes "{business_name}" and "{agent_name}" by name, ask for caller's name
   Step 2 — Understand the Request: open question to understand why they're calling
   Step 3 — Ask Qualification Questions: 3 questions, one at a time, relevant to this business
   Step 4 — Answer Questions: answer using the business knowledge. Put the literal token {KB_SENTINEL} on its own line in this step where the reference knowledge belongs — do NOT copy any knowledge text into the script; the system injects it later.
   Step 5 — Arrange Next Steps: schedule, book, or arrange a callback as appropriate
   Step 6 — Confirm Contact Details: NEVER ask the caller to say their phone number (you already have it from caller ID); confirm they can be reached on it
   Step 7 — Warm Wrap-Up
4. RULES section — 6-8 specific, business-relevant rules

The script must use the actual business name ("{business_name}") and agent name ("{agent_name}") throughout, not placeholders (except the single {KB_SENTINEL} token in Step 4).

For CONTEXT ONLY — use this to write relevant questions and rules, but do NOT copy it verbatim into the script:
{kb_for_context or "No website content available."}

Also provide exactly 3 qualification questions specific to this business type. Give each a
short, descriptive snake_case key that names what it captures (e.g. "business_type",
"current_system", "timeline") — NOT generic names like key1/key2/key3.

Return valid JSON only:
{{
  "system_prompt": "...(complete script here)...",
  "qualification_fields": {{
    "business_type": "First qualification question?",
    "current_system": "Second qualification question?",
    "timeline": "Third qualification question?"
  }}
}}"""

    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert at writing professional AI phone receptionist scripts. "
                    "Always return valid JSON. Write scripts that are warm, efficient, and natural-sounding."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    data = json.loads(response.choices[0].message.content)
    system_prompt: str = data["system_prompt"]
    qualification_fields: dict = data["qualification_fields"]

    # Guarantee the base stays refreshable even if the model dropped the token.
    if KB_SENTINEL not in system_prompt:
        system_prompt += f"\n\nBUSINESS KNOWLEDGE (reference)\n{KB_SENTINEL}"

    return system_prompt, qualification_fields


def _owner_layer_block(
    business_subtype: str | None,
    receptionist_tone: str | None,
    operating_priorities: list[str] | None,
    extra_instructions: str | None,
) -> str:
    """Instruction-priority header + owner operating rules — sits above the
    industry body and below the safety preamble."""
    return vapi.INSTRUCTION_PRIORITY + vapi.render_owner_layer(
        business_subtype=business_subtype,
        receptionist_tone=receptionist_tone,
        operating_priorities=operating_priorities,
        business_instructions=(extra_instructions or "").strip() or None,
    )


async def _custom_body(tenant: dict, wrapped_kb: str, kb_raw: str) -> str:
    """Custom industry body with fresh KB injected. Reuses the stored
    custom_prompt_base; regenerates it ONCE if missing (older custom tenants),
    so custom tenants pick up KB/website changes instead of being frozen."""
    base = (tenant.get("custom_prompt_base") or "").strip()
    if not base:
        logger.info("No custom_prompt_base for tenant %s — regenerating once from description + KB", tenant.get("id"))
        base, _qual = await _generate_custom_content(
            business_name=tenant["business_name"],
            agent_name=tenant.get("agent_name", "Alex"),
            business_description=tenant.get("business_description", "") or "",
            knowledge_context=kb_raw,
        )
        try:
            await db.update_tenant(tenant["id"], {"custom_prompt_base": base})
        except Exception as e:
            logger.warning("Could not store custom_prompt_base for tenant %s: %s", tenant.get("id"), e)
    return base.replace(KB_SENTINEL, wrapped_kb or "No website content available.")


def _onboarding_result(tenant: dict, *, onboarding_state: str,
                       phone_number: str = "", status: str = "",
                       next_step: str = "") -> dict:
    """The shape every provisioning outcome returns.

    One builder so a diverted country, a resumed attempt and a finished signup
    cannot describe themselves in three different vocabularies -- the frontend
    switches on `onboarding_state`, never on the absence of a field.
    """
    return {
        "tenant_id": tenant["id"],
        "phone_number": phone_number,
        "assistant_id": tenant.get("vapi_assistant_id") or "",
        "onboarding_state": onboarding_state,
        "status": status or onboarding_state,
        "next_step": next_step,
        "dashboard_url": f"{FRONTEND_URL}/dashboard/{tenant['id']}",
    }


def _completed_result(tenant: dict) -> dict:
    return _onboarding_result(
        tenant, onboarding_state=lifecycle_ob.ACTIVE, status="live",
        phone_number=str(tenant.get("twilio_phone_number") or ""))


def _regulatory_pending_result(tenant: dict, country: str) -> dict:
    """A real, working account that cannot hold a number yet.

    NOT an error, and the wording matters: the customer has an account, and what
    remains is a verification step their country's regulator requires -- not a
    failure of ours. W9I-C replaces the placeholder next_step with the form.
    """
    return _onboarding_result(
        tenant, onboarding_state=lifecycle_ob.REGULATORY_REQUIRED,
        next_step="regulatory_information_required")


async def _claim_or_resume_tenant(payload: dict, country: str) -> tuple[dict, bool]:
    """The onboarding tenant for THIS attempt -- created once, then resumed.

    The key is opaque and per-attempt. A retry carrying the same key lands on the
    same tenant; a genuinely new signup carries a new key and gets a new tenant.
    Deliberately NOT keyed on email or business_name: one person legitimately runs
    two businesses and two businesses share a name, so either would refuse real
    signups -- and on an unauthenticated endpoint either would also answer "does
    this email already exist?" for anyone who asked.
    """
    key = str(payload.get("onboarding_key") or "").strip()
    if not key:
        # Callers that predate the key still work; they simply cannot resume.
        # Their tenant is created the same way, without a claim.
        row = await db.insert_tenant(_initial_tenant_row(payload, country))
        return row, False

    existing = await db.find_onboarding_tenant(key)
    if existing:
        logger.info("[Step 0] Resuming onboarding tenant %s", existing["id"])
        return existing, True

    claimed = await db.claim_onboarding_tenant(key, _initial_tenant_row(payload, country))
    if claimed is not None:
        return claimed, False

    # Lost the race to a concurrent request carrying the same key.
    existing = await db.find_onboarding_tenant(key)
    if existing:
        logger.info("[Step 0] Lost the onboarding claim — resuming tenant %s",
                    existing["id"])
        return existing, True
    raise HTTPException(status_code=503,
                        detail="Could not start onboarding. Please try again.")


def _initial_tenant_row(payload: dict, country: str) -> dict:
    """The minimum durable tenant. Everything else is filled in as it is earned.

    business_country_code is written HERE, from the country the customer chose in
    the form, because that explicit choice is the only trustworthy signal -- and
    signup is the one moment it can be captured before any country-sensitive
    provider boundary is crossed. `country` (the analyzer's guess) is kept
    separate and unchanged; they answer different questions.
    """
    return {
        "business_name": payload["business_name"],
        "industry": payload["industry"],
        "owner_name": payload.get("owner_name", ""),
        "country": country or None,
        "business_country_code": country or None,
        "website_url": payload.get("website_url", ""),
        "is_active": True,
        "onboarding_state": lifecycle_ob.initial_state(country),
    }


async def provision_tenant(payload: dict) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]

    # ── Step 0 — THE TENANT, BEFORE ANY PROVIDER IS TOUCHED (W9I-B) ───────
    # This used to be Step 12, and the ordering was not a style choice: every
    # regulatory artefact Ireland needs -- address, business details,
    # authorisation, profile, provider claims -- is keyed on tenant_id by a
    # composite foreign key, so the tenant has to exist before any of it can. An
    # Irish tenant must also be able to REST here, valid and un-numbered, while
    # the customer supplies compliance information.
    #
    # The old order was accidentally safe against duplicates because it failed
    # before inserting anything. Moving the insert to the front removes that
    # accident, so the onboarding key replaces it deliberately: one attempt, one
    # key, and the partial unique index decides which concurrent request creates
    # the tenant while the loser resumes into it.
    requested_country = str(payload.get("country") or "").strip().upper()
    tenant, resumed = await _claim_or_resume_tenant(payload, requested_country)
    tenant_id = tenant["id"]
    state = str(tenant.get("onboarding_state") or "")

    # Already finished: a completed tenant is FROZEN to this path. Returned as-is,
    # before any write, so possession of an onboarding key can never reopen or
    # mutate a live account. Checked on the state alone -- not on whether a number
    # happens to be present -- so a tenant marked active without one is still
    # closed to resume rather than falling through to provisioning.
    if state == lifecycle_ob.ACTIVE:
        logger.info("[Step 0] Onboarding already complete for tenant %s — returning "
                    "the finished state", tenant_id)
        return _completed_result(tenant)

    # ── THE STORED COUNTRY IS AUTHORITATIVE ON RESUME ─────────────────────
    # The diversion below decides whether a regulator has to be satisfied before a
    # number can exist, and an earlier version of this code took that decision
    # from the REQUEST. That was a real hole: a second call carrying the same key
    # and a different country would have bought a Canadian number for a tenant
    # whose compliance country was already recorded as IE -- wrong country on the
    # invoice, and a canonical phone row disagreeing with the tenant it belongs
    # to. business_country_code is written once, at claim time, and a mismatch is
    # refused rather than silently ignored: a customer who thinks they changed
    # country must be told they did not.
    country = requested_country
    if resumed:
        stored = str(tenant.get("business_country_code") or "").strip().upper()
        if stored:
            if requested_country and requested_country != stored:
                logger.warning("[Step 0] Refusing a country change on resume for "
                               "tenant %s", tenant_id)
                raise HTTPException(
                    status_code=409,
                    detail={"status": "country_already_set",
                            "business_country_code": stored,
                            "message": "This signup was started for a different "
                                       "country. Please start again to change it."})
            country = stored

    # ── THE REGULATED-COUNTRY DIVERSION ──────────────────────────────────
    # Ireland stops here. W9C and W9H-QA.2 both measured that an Irish local
    # number is refused at PURCHASE time without a validated AddressSid and an
    # approved Bundle, and that Twilio exposes no way to learn that beforehand --
    # so there is nothing to branch on inside the number search. The only correct
    # move is to not reach telephony at all. The tenant is real, the account
    # works, and W9I-C gives the customer the compliance form.
    if lifecycle_ob.needs_regulatory_clearance(country):
        logger.info("[Step 0] %s requires regulatory clearance — tenant %s created "
                    "without telephony", country, tenant_id)
        return _regulatory_pending_result(tenant, country)

    # Step 1 — Load system prompt template (skip for custom industry)
    step = 1
    try:
        if industry == "custom":
            template = None
            logger.info("[Step %d] Custom industry — template will be AI-generated", step)
        else:
            template = _load_template(industry)
            logger.info("[Step %d] Loaded template for industry '%s'", step, industry)
    except Exception as e:
        logger.error("[Step %d] Failed to load template: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 2 — Build qualification fields (skip for custom industry)
    step = 2
    try:
        if industry == "custom":
            qualification_fields = None
            logger.info("[Step %d] Custom industry — qualification fields will be AI-generated", step)
        else:
            qualification_fields = QUALIFICATION_FIELDS.get(industry)
            if qualification_fields is None:
                raise ValueError(f"No qualification fields defined for industry '{industry}'")
            logger.info("[Step %d] Built qualification fields for '%s'", step, industry)
    except Exception as e:
        logger.error("[Step %d] Failed to build qualification fields: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 3 — Create Twilio sub-account, find and purchase a local number
    step = 3
    subaccount_sid = subaccount_token = purchased_number = None
    try:
        subaccount = await telephony.create_subaccount(business_name)
        subaccount_sid = subaccount["sid"]
        subaccount_token = subaccount["auth_token"]
        country_code = payload.get("country", "CA")
        # Match the business's own region: prefer the area code of the business's
        # phone, and keep the number in the business's PROVINCE (from the phone's
        # area code, else the province the analyzer detected from the address /
        # service area). Ontario businesses get an Ontario number, etc.
        preferred_ac = telephony.area_code_from_phone(payload.get("business_phone", ""))
        detected_province = ""
        if payload.get("analysis_token"):
            try:
                from services import website_analysis
                _cached = website_analysis.get_cached_scrape(payload["analysis_token"]) or {}
                _detected = _cached.get("detected") or {}
                if not preferred_ac:
                    preferred_ac = telephony.area_code_from_phone(_detected.get("phone", ""))
                detected_province = (_detected.get("province") or "").strip()
            except Exception as e:
                logger.warning("[Step %d] Could not derive area code/province from analysis: %s", step, e)
        logger.info("[Step %d] Number region: preferred_ac=%s, province=%s", step, preferred_ac or "-", detected_province or "-")
        phone_number = await telephony.find_available_number(
            subaccount_sid, subaccount_token, country_code,
            preferred_area_code=preferred_ac, province=detected_province)
        purchased_number, purchased_sid = await telephony.purchase_number_with_sid(
            subaccount_sid, subaccount_token, phone_number)
        logger.info("[Step %d] Provisioned Twilio number %s", step, purchased_number)
    except Exception as e:
        logger.error("[Step %d] Twilio provisioning failed: %s", step, e)
        # ── W9A · never leak the sub-account this attempt created ───────────
        # create_subaccount() runs BEFORE any number can be searched or bought,
        # and a number purchase can fail for reasons we cannot pre-validate --
        # an Irish local number needs an AddressSid, and Twilio only says so at
        # purchase time. Without this, every such failure left a live
        # sub-account behind, and every retry created another one.
        #
        # Only an account created inside THIS try block is closed:
        # subaccount_sid is None until create_subaccount() returns, so a failure
        # before that point closes nothing, and a pre-existing account can never
        # be reached from here.
        if subaccount_sid:
            closed = await telephony.close_subaccount(subaccount_sid)
            if not closed:
                # Reported, not swallowed: an orphan nobody knows about is worse
                # than a noisy provisioning error.
                logger.error("[Step %d] ORPHANED Twilio sub-account %s — close it "
                             "by hand", step, subaccount_sid)
            subaccount_sid = subaccount_token = None
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Reuse the pre-provision website scrape if onboarding already did one.
    prescraped_text = None
    analysis_token = payload.get("analysis_token", "")
    if analysis_token:
        try:
            from services import website_analysis
            cached = website_analysis.get_cached_scrape(analysis_token)
            if cached:
                prescraped_text = cached.get("text", "")
                logger.info("[provision] Reusing cached scrape (%d chars) for token", len(prescraped_text or ""))
        except Exception as e:
            logger.warning("[provision] Could not load cached scrape: %s", e)

    # Steps 4–11 are wrapped so any failure releases the purchased number before raising
    try:
        return await _provision_after_twilio(
            payload, tenant, subaccount_sid, subaccount_token, purchased_number,
            purchased_sid, template, qualification_fields, prescraped_text,
        )
    except HTTPException:
        logger.warning("Rolling back: releasing number %s on sub-account %s", purchased_number, subaccount_sid)
        # Best effort — release_number now raises on a Twilio error, and the
        # original provisioning failure is the one worth surfacing.
        released = False
        try:
            released = await telephony.release_number(
                subaccount_sid, subaccount_token, purchased_number)
        except Exception as e:
            logger.error("Rollback release of %s failed: %s", purchased_number, e)
        # Step 13 may already have inserted a canonical row before the failure
        # that brought us here. Left behind as 'provisioning' it is still a live
        # permanent by tpn_one_current_permanent and still owns the E.164 by
        # tpn_owned_e164_key, so this tenant could never be provisioned again --
        # the same divergence the release path had, reached from the other side.
        # Only on a CONFIRMED Twilio delete, and fenced on the identity we bought.
        if released:
            await _rollback_canonical_row(
                tenant["id"], purchased_number, subaccount_sid, purchased_sid)
        raise


async def _provision_after_twilio(
    payload: dict,
    tenant: dict,
    subaccount_sid: str,
    subaccount_token: str,
    purchased_number: str,
    purchased_sid: str,
    template: str | None,
    qualification_fields: dict | None,
    prescraped_text: str | None = None,
) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]
    owner_name: str = payload.get("owner_name", "")
    website_url: str = payload.get("website_url", "")
    agent_name: str = payload.get("agent_name", "Alex")
    # Gender-appropriate voice: preset names map to a fixed voice; a custom name
    # uses the voice_gender the tenant picked ('female' default).
    voice_gender: str = (payload.get("voice_gender") or "female")
    voice_id: str = vapi.resolve_voice_id(agent_name, voice_gender)
    # Structured business profile (owner operating layer). Empty -> defaults at build.
    business_subtype: str = (payload.get("business_subtype") or "").strip()
    receptionist_tone: str = (payload.get("receptionist_tone") or "").strip()
    operating_priorities: list[str] = [
        str(p).strip() for p in (payload.get("operating_priorities") or []) if str(p).strip()
    ]
    business_description: str = (payload.get("business_description") or "").strip()

    # Reuse the onboarding analysis (Business Brief + structured extracts) when present.
    predetected: dict = {}
    _atok = payload.get("analysis_token", "")
    if _atok:
        try:
            from services import website_analysis as _wa
            _c = _wa.get_cached_scrape(_atok)
            if _c and _c.get("detected"):
                predetected = _c["detected"]
        except Exception:
            pass

    # Step 4 — Scrape website (non-fatal: provisioning continues without knowledge base).
    # Reuse the onboarding pre-scrape when present to avoid a second Firecrawl call.
    step = 4
    scraped_text = ""
    if prescraped_text:
        scraped_text = prescraped_text
        logger.info("[Step %d] Reusing onboarding pre-scrape (%d chars)", step, len(scraped_text))
    elif website_url:
        try:
            scraped_text = await knowledge.scrape_website(website_url)
            logger.info("[Step %d] Scraped website %s", step, website_url)
        except Exception as e:
            logger.warning("[Step %d] Website scrape failed (continuing without KB): %s", step, e)
    else:
        logger.info("[Step %d] No website_url provided, skipping scrape", step)

    # Step 5 — Generate Pinecone namespace
    step = 5
    try:
        pinecone_namespace = _slugify(business_name)
        logger.info("[Step %d] Pinecone namespace: '%s'", step, pinecone_namespace)
    except Exception as e:
        logger.error("[Step %d] Namespace generation failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 6 — Embed and store scraped content
    step = 6
    vectors_stored = 0
    if scraped_text:
        try:
            vectors_stored = await knowledge.embed_and_store(
                namespace=pinecone_namespace,
                text=scraped_text,
                tenant_id=pinecone_namespace,
                source_id="website-onboarding",
                source_type="website",
            )
            logger.info("[Step %d] Stored %d vectors", step, vectors_stored)
        except Exception as e:
            logger.error("[Step %d] Embed/store failed: %s", step, e)
            raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")
    else:
        logger.info("[Step %d] No scraped text to embed", step)

    # Step 7 — Build greeting template
    step = 7
    try:
        # The AI + recording disclosure is prepended at call time (see vapi.ensure_call_disclosure),
        # so the greeting itself stays warm and uncluttered.
        greeting_template = (
            f"Hi, thank you for calling {business_name}! "
            f"I'm {agent_name}. How can I help you today?"
        )
        logger.info("[Step %d] Built greeting template", step)
    except Exception as e:
        logger.error("[Step %d] Greeting template build failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 8 — Build system prompt
    step = 8
    custom_prompt_base = None
    try:
        extra_instructions: str = (payload.get("extra_instructions") or "").strip()

        # Prefer the structured Business Brief from analysis; fall back to raw scrape.
        brief_text = (predetected.get("business_brief") or "").strip()
        kb_text = brief_text or scraped_text[:8000]
        knowledge_context = vapi.wrap_untrusted_kb(kb_text) if kb_text else "No website content available."

        if industry == "custom":
            logger.info("[Step %d] Generating custom system prompt via GPT", step)
            # Store the base WITH the KB sentinel so later rebuilds can refresh KB.
            custom_prompt_base, qualification_fields = await _generate_custom_content(
                business_name=business_name,
                agent_name=agent_name,
                business_description=business_description,
                knowledge_context=kb_text,
            )
            industry_body = custom_prompt_base.replace(KB_SENTINEL, knowledge_context)
        else:
            qualification_questions = "\n".join(
                f"- {q}" for q in qualification_fields.values()
            )
            industry_body = template.format(
                business_name=business_name,
                agent_name=agent_name,
                qualification_questions=qualification_questions,
                knowledge_context=knowledge_context,
            )

        # Owner operating layer above the industry body (priority + profile + instructions).
        system_prompt = _owner_layer_block(
            business_subtype, receptionist_tone, operating_priorities, extra_instructions
        ) + industry_body

        logger.info("[Step %d] Built system prompt (%d chars)", step, len(system_prompt))
    except KeyError as e:
        logger.error("[Step %d] Missing placeholder in template: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: missing placeholder {e}")
    except Exception as e:
        logger.error("[Step %d] System prompt build failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 9 — Create Vapi sub-organization (isolated 10-call concurrent limit per tenant)
    step = 9
    suborg_id = suborg_key_encrypted = suborg_key = None
    try:
        suborg = await vapi.create_suborg(business_name)
        suborg_id = suborg["id"]
        raw_key = suborg["api_key"]
        from services.security import encrypt
        suborg_key_encrypted = encrypt(raw_key)
        suborg_key = raw_key
        logger.info("[Step %d] Created Vapi sub-org %s for '%s'", step, suborg_id, business_name)
    except Exception as e:
        logger.warning("[Step %d] Vapi sub-org creation failed (continuing with parent org pool): %s", step, e)
        # Non-fatal: tenant will share parent org pool instead of having an isolated limit

    # Step 10 — Create Vapi assistant
    step = 10
    try:
        tenant_stub = {
            "agent_name": agent_name,
            "greeting_template": greeting_template,
            "voice_id": voice_id,
            "voice_gender": voice_gender,
        }
        assistant_config = vapi.build_assistant_config(tenant_stub, system_prompt)
        vapi_assistant_id = await vapi.create_assistant(assistant_config, api_key=suborg_key)
        logger.info("[Step %d] Created Vapi assistant %s", step, vapi_assistant_id)
    except Exception as e:
        logger.error("[Step %d] Vapi assistant creation failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 11 — Import Twilio number into Vapi and assign assistant
    step = 11
    try:
        vapi_phone_id = await vapi.import_twilio_number(
            phone_number=purchased_number,
            twilio_account_sid=subaccount_sid,
            twilio_auth_token=subaccount_token,
            label=business_name,
            server_url=f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended",
            api_key=suborg_key,
        )
        logger.info("[Step %d] Linked %s to Vapi assistant %s", step, purchased_number, vapi_assistant_id)
    except Exception as e:
        logger.error("[Step %d] Vapi phone import failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 12 — Insert tenant row in Supabase
    step = 12
    try:
        tenant_data = {
            "business_name": business_name,
            "industry": industry,
            "owner_name": owner_name,
            "country": payload.get("country", "") or None,
            "website_url": website_url,
            "agent_name": agent_name,
            "voice_id": voice_id,
            "voice_gender": voice_gender,
            "business_subtype": business_subtype or None,
            "receptionist_tone": receptionist_tone or None,
            "operating_priorities": operating_priorities or None,
            "business_description": business_description or None,
            "custom_prompt_base": custom_prompt_base,
            "greeting_template": greeting_template,
            "qualification_fields": qualification_fields,
            "twilio_subaccount_sid": subaccount_sid,
            "twilio_auth_token": subaccount_token,
            "vapi_assistant_id": vapi_assistant_id,
            "vapi_phone_number_id": vapi_phone_id,
            "pinecone_namespace": pinecone_namespace,
            "last_system_prompt": system_prompt,
            "is_active": True,
        }
        if scraped_text and website_url:
            from datetime import datetime as _dt, timezone as _tz
            tenant_data["last_crawl_at"]     = _dt.now(_tz.utc).isoformat()
            tenant_data["last_crawl_status"] = "success"
            tenant_data["last_crawl_source"] = "onboarding"
            tenant_data["last_crawl_pages"]  = (scraped_text.count("\n\n") + 1)
        # Persist the onboarding Business Brief + structured extracts (homepage-level;
        # the first scheduled re-crawl / Sync upgrades these from the full site crawl).
        # Business phone: prefer an explicit value from the form, else the number
        # detected on the website. Editable later in Settings.
        business_phone = (payload.get("business_phone") or predetected.get("phone") or "").strip()
        if business_phone:
            tenant_data["business_phone"] = business_phone[:32]
        if predetected.get("business_brief"):
            tenant_data["business_brief"]          = predetected.get("business_brief")
            tenant_data["extracted_services"]      = predetected.get("services") or []
            tenant_data["extracted_faqs"]          = predetected.get("faqs") or []
            tenant_data["extracted_service_areas"] = predetected.get("service_areas") or []
            tenant_data["extracted_policies"]      = predetected.get("policies") or []
        if suborg_id:
            tenant_data["vapi_suborg_id"] = suborg_id
        if suborg_key_encrypted:
            tenant_data["vapi_suborg_api_key"] = suborg_key_encrypted
        # The tenant already exists -- Step 0 created it before any provider was
        # touched -- so this UPDATES it rather than inserting a second one. A
        # resumed attempt overwrites the same row with the same work.
        tenant_id = tenant["id"]
        # Settled at Step 0 and never re-guessed from a later request. Popped
        # rather than absent-by-luck, so a future edit to tenant_data cannot
        # reintroduce a country rewrite.
        tenant_data.pop("country", None)
        tenant_data.pop("business_country_code", None)
        updated = await db.update_tenant(tenant_id, tenant_data)
        logger.info("[Step %d] Updated onboarding tenant %s", step, tenant_id)
    except Exception as e:
        logger.error("[Step %d] Supabase tenant update failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # ── Step 13 — THE CANONICAL PHONE ROW (W9I-B) ─────────────────────────
    # W9I-A found signup writing the number ONLY to the legacy scalar, leaving
    # tenant_phone_numbers -- the model routing prefers and the whole two-number
    # Irish migration depends on -- populated by backfill alone. Both are written
    # here, through the one path that owns them, so they cannot diverge again.
    #
    # register_permanent inserts `provisioning`, which phone_lifecycle excludes
    # from ROUTABLE_STATUSES; mark_active flips it to `active` and mirrors the
    # scalar at the same moment. Between the two an inbound caller cannot be sent
    # to a number whose webhook is already wired but whose row is not yet live.
    step = 13
    try:
        reg = await phone_registry.register_permanent(
            tenant_id=tenant_id, e164=purchased_number,
            provider_account_sid=subaccount_sid, provider_sid=purchased_sid or "",
            iso_country=str(payload.get("country") or "").strip().upper() or "CA")
        if reg["status"] != phone_registry.OK or not reg.get("row"):
            raise RuntimeError(f"canonical phone registration refused: {reg.get('detail')}")
        await phone_registry.mark_active(tenant_id=tenant_id,
                                        number_row_id=reg["row"]["id"],
                                        e164=purchased_number)
        logger.info("[Step %d] Canonical phone row active for tenant %s", step, tenant_id)
    except Exception as e:
        logger.error("[Step %d] Canonical phone persistence failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    try:
        await db.update_tenant(tenant_id, {"onboarding_state": lifecycle_ob.ACTIVE})
    except Exception as e:
        # The line works; the marker lagging is not worth failing a signup for.
        logger.error("Could not mark onboarding complete for tenant %s: %s", tenant_id, e)

    return {
        "tenant_id": tenant_id,
        "phone_number": purchased_number,
        "assistant_id": vapi_assistant_id,
        "onboarding_state": lifecycle_ob.ACTIVE,
        "status": "live",
        "next_step": "",
        "dashboard_url": f"{FRONTEND_URL}/dashboard/{tenant_id}",
    }


async def _rollback_canonical_row(tenant_id: str, e164: str,
                                  subaccount_sid: str, provider_sid: str) -> None:
    """Retire a canonical row a failed provisioning attempt may have created.

    Never raises: the provisioning failure that triggered the rollback is the
    error worth surfacing, and a rollback that raises would replace it with a
    less useful one. A row left behind is loud in the log and reconcilable;
    hiding the original failure is not.
    """
    from db import phone_numbers as db_phones
    try:
        row = await db_phones.find_owned_by_e164(e164)
        if not row or str(row.get("tenant_id") or "") != str(tenant_id):
            return
        rel = await phone_registry.mark_released(
            tenant_id=str(tenant_id), number_row_id=str(row["id"]),
            expected_e164=e164,
            expected_provider_sid=str(row.get("provider_sid") or ""),
            expected_provider_account_sid=str(row.get("provider_account_sid") or ""),
            last_error="provisioning rolled back")
        if not rel["released"]:
            logger.error("Rollback: canonical row %s for %s not released (%s)",
                         row.get("id"), e164, rel.get("detail"))
    except Exception as e:
        logger.error("Rollback: canonical retirement of %s failed: %s", e164, e)


async def release_tenant_number(tenant: dict) -> dict:
    """Give a tenant's phone number back — the inverse of provisioning it.

    DESTRUCTIVE AND IRREVERSIBLE. Twilio can reassign a released number to
    somebody else, so a business that loses one loses it for good and its callers
    reach a stranger. Every caller must be a deliberate act: the retention purge
    (where the row is being deleted anyway) or an explicit admin action.

    Vapi is detached FIRST, on purpose. If the Twilio release then fails we are
    left paying for a number nobody routes to, which the next run fixes. The
    reverse order would leave Vapi pointing at a number Twilio has already handed
    to someone else — that failure sends real calls to the wrong business.

    Idempotent: the tenant's number fields are cleared on success, and a missing
    number is reported as already released rather than treated as an error.

    Never raises. Returns {"released": bool, "steps": {...}, "reason": str}.
    """
    from db import supabase as db
    from db import phone_numbers as db_phones

    tenant_id  = str(tenant.get("id") or "")
    number     = str(tenant.get("twilio_phone_number") or "")
    sub_sid    = str(tenant.get("twilio_subaccount_sid") or "")
    sub_token  = str(tenant.get("twilio_auth_token") or "")
    vapi_id    = str(tenant.get("vapi_phone_number_id") or "")
    steps: dict = {}

    # The canonical row is resolved FIRST, before anything is given away, and by
    # E.164 rather than by "the tenant's current number". Reading it up front is
    # what lets the transition at the end be fenced on the identity we saw here:
    # if a replacement arrives in between, the fence misses and the replacement
    # survives.
    canonical = None
    if number:
        try:
            canonical = await db_phones.find_owned_by_e164(number)
            if canonical and str(canonical.get("tenant_id") or "") != tenant_id:
                # Another tenant holds this E.164 canonically. Releasing on this
                # tenant's credentials would take away a number the books say is
                # someone else's. Refuse; this needs a human.
                logger.error(
                    "release: %s is canonically owned by tenant %s, not %s -- refusing",
                    number, canonical.get("tenant_id"), tenant_id)
                return {"released": False, "steps": {},
                        "reason": "canonical_owner_mismatch"}
        except Exception as e:
            # Not knowing the canonical state is not a reason to proceed: the
            # whole point is that provider release and canonical state converge.
            logger.error("release: canonical lookup failed for tenant %s: %s", tenant_id, e)
            return {"released": False, "steps": {}, "reason": "canonical_lookup_failed"}
    steps["canonical_row"] = bool(canonical)

    if not number:
        # No scalar. A canonical row can still be live here -- that is exactly the
        # drift this gate closes -- so say so rather than reporting a clean no-op.
        try:
            orphan = await db_phones.get_current_permanent(tenant_id)
        except Exception:
            orphan = None
        if orphan:
            logger.error(
                "release: tenant %s has no scalar number but canonical row %s is "
                "still %s on %s -- reconcile it before releasing",
                tenant_id, orphan.get("id"), orphan.get("status"), orphan.get("e164"))
            return {"released": False, "steps": steps,
                    "reason": "canonical_row_without_scalar"}
        return {"released": True, "steps": steps, "reason": "no_number_on_tenant"}

    logger.warning(
        "RELEASING number %s for tenant %s (%s) — subscription_status=%s. This cannot be undone.",
        number, tenant_id, tenant.get("business_name"), tenant.get("subscription_status"),
    )

    if vapi_id:
        try:
            steps["vapi_deleted"] = await vapi.delete_phone_number(
                vapi_id, api_key=vapi.get_tenant_vapi_key(tenant)
            )
        except Exception as e:
            logger.error("release: Vapi delete failed for tenant %s: %s", tenant_id, e)
            steps["vapi_deleted"] = False
        if not steps["vapi_deleted"]:
            # Stop here rather than release the Twilio number underneath a live
            # Vapi record. Retryable — nothing has been given away yet.
            return {"released": False, "steps": steps, "reason": "vapi_delete_failed"}
    else:
        steps["vapi_deleted"] = True  # nothing registered

    if not (sub_sid and sub_token):
        logger.error(
            "release: tenant %s has number %s but no subaccount credentials — "
            "release it manually in the Twilio console",
            tenant_id, number,
        )
        return {"released": False, "steps": steps, "reason": "missing_twilio_credentials"}

    try:
        deleted = await telephony.release_number(sub_sid, sub_token, number)
    except Exception as e:
        logger.error("release: Twilio release failed for tenant %s: %s", tenant_id, e)
        return {"released": False, "steps": steps, "reason": "twilio_release_failed"}

    if not deleted:
        # Twilio accepted the request but the number was not on this sub-account.
        # Do NOT clear the row: either the credentials point somewhere else and
        # the number is still being billed, or it is genuinely already gone — and
        # silently clearing would destroy the only record of which it was.
        steps["twilio_released"] = False
        logger.error(
            "release: %s was not found on sub-account %s for tenant %s — leaving the "
            "tenant row intact; check the number's actual sub-account in Twilio",
            number, sub_sid, tenant_id,
        )
        return {"released": False, "steps": steps, "reason": "twilio_number_not_found"}

    steps["twilio_released"] = True

    # Twilio has confirmed the delete. ONLY NOW may the books say released --
    # everything above this line is "we asked", which is not proof.
    #
    # Canonical first and scalar second, through the one primitive that owns
    # both, so they cannot end up disagreeing. Before W9I-B.1 this was a bare
    # update_tenant that cleared the scalar and left the canonical row 'active':
    # the number was gone at Twilio, unroutable in fact, and still counted as
    # the tenant's live permanent -- which made every later reprovision buy a
    # number and immediately throw it away.
    from datetime import datetime, timezone
    if canonical:
        try:
            rel = await phone_registry.mark_released(
                tenant_id=tenant_id, number_row_id=str(canonical["id"]),
                expected_e164=number,
                expected_provider_sid=str(canonical.get("provider_sid") or ""),
                expected_provider_account_sid=str(canonical.get("provider_account_sid") or ""))
        except Exception as e:
            logger.error(
                "release: number %s released at Twilio for tenant %s but the "
                "canonical transition raised: %s -- the row still reads live",
                number, tenant_id, e)
            steps["canonical_released"] = False
            steps["tenant_cleared"] = False
            return {"released": True, "steps": steps,
                    "reason": "canonical_update_failed", "number": number}
        steps["canonical_released"] = rel["released"]
        steps["canonical_idempotent"] = rel["idempotent"]
        steps["tenant_cleared"] = rel["scalar_cleared"]
        if not rel["released"]:
            logger.error(
                "release: number %s is gone at Twilio for tenant %s but the "
                "canonical row was not transitioned (%s)",
                number, tenant_id, rel.get("detail"))
            return {"released": True, "steps": steps,
                    "reason": f"canonical_not_released:{rel.get('detail')}",
                    "number": number}
    else:
        # A legacy tenant that predates the canonical model. There is nothing to
        # transition, so the fenced scalar clear stands alone -- still fenced, so
        # it cannot clear a replacement.
        try:
            cleared = await db.clear_tenant_number_fenced(
                tenant_id, number, datetime.now(timezone.utc).isoformat())
            steps["tenant_cleared"] = bool(cleared)
        except Exception as e:
            logger.error(
                "release: number %s released for tenant %s but clearing the row failed: %s",
                number, tenant_id, e)
            steps["tenant_cleared"] = False

    logger.info("Released number %s for tenant %s", number, tenant_id)
    return {"released": True, "steps": steps, "reason": "", "number": number}


async def reprovision_tenant_number(tenant: dict) -> dict:
    """Give a returning tenant a working phone line again.

    The inverse of release_tenant_number(), for the case that decision makes
    possible: we keep the tenant row when we reclaim a number, so their knowledge
    base, settings and history survive — but without this they'd come back to a
    working account with no phone line and no way to get one, since
    provision_tenant() only ever runs at signup.

    Reuses their existing Twilio subaccount and Vapi assistant, so this is just
    the number: find, buy, import, record. They do NOT get their old number back
    — that one is gone for good and may belong to someone else now.

    Deliberately admin-triggered rather than automatic on re-subscribe. It spends
    money on a real phone number, and a webhook retry storm that buys a number per
    delivery is a worse failure than a support ticket.

    Never raises. Returns {"provisioned": bool, "number": str, "reason": str}.
    """
    from db import supabase as db

    tenant_id = str(tenant.get("id") or "")
    sub_sid   = str(tenant.get("twilio_subaccount_sid") or "")
    sub_token = str(tenant.get("twilio_auth_token") or "")

    if tenant.get("twilio_phone_number"):
        return {"provisioned": False, "number": str(tenant["twilio_phone_number"]),
                "reason": "tenant_already_has_a_number"}

    # PREFLIGHT, BEFORE ANY MONEY IS SPENT (W9I-B.1 Stage H).
    # The scalar guard above is not sufficient on its own: a tenant whose scalar
    # was cleared but whose canonical row is still live passes it, buys a real
    # number, and is then refused by register_permanent below -- after the
    # non-refundable monthly rental has been charged (USD 1.15 for a Canadian
    # local number, measured). Ask the canonical model, which is the authority
    # on whether this tenant already holds a permanent number, and refuse here.
    #
    # This does not replace the post-purchase check. A preflight sees a moment
    # ago; live_conflict and tpn_one_current_permanent are what hold under a
    # race. Both are required, for different failures.
    try:
        live = await phone_registry.current_permanent_conflict(tenant_id)
    except Exception as e:
        # Unable to establish whether a purchase is safe. Spending money on a
        # maybe is the one outcome worth avoiding here.
        logger.error("reprovision: canonical preflight failed for tenant %s: %s",
                     tenant_id, e)
        return {"provisioned": False, "number": "", "reason": "canonical_preflight_failed"}
    if live:
        logger.error(
            "reprovision: tenant %s still holds canonical permanent row %s "
            "(%s, %s) -- refusing BEFORE purchasing a replacement",
            tenant_id, live.get("id"), live.get("e164"), live.get("status"))
        return {"provisioned": False, "number": "",
                "reason": "canonical_permanent_still_live"}

    if not (sub_sid and sub_token):
        return {"provisioned": False, "number": "", "reason": "missing_twilio_credentials"}
    if not tenant.get("vapi_assistant_id"):
        return {"provisioned": False, "number": "", "reason": "no_assistant_on_tenant"}

    country = str(tenant.get("country") or "CA")
    # Keep them local to the number they already publish, if we know it.
    preferred_ac = ""
    try:
        preferred_ac = telephony.area_code_from_phone(str(tenant.get("business_phone") or ""))
    except Exception:
        pass

    try:
        candidate = await telephony.find_available_number(
            sub_sid, sub_token, country, preferred_area_code=preferred_ac,
        )
        number, number_sid = await telephony.purchase_number_with_sid(
            sub_sid, sub_token, candidate)
    except Exception as e:
        logger.error("reprovision: Twilio purchase failed for tenant %s: %s", tenant_id, e)
        return {"provisioned": False, "number": "", "reason": "twilio_purchase_failed"}

    try:
        vapi_phone_id = await vapi.import_twilio_number(
            phone_number=number,
            twilio_account_sid=sub_sid,
            twilio_auth_token=sub_token,
            label=str(tenant.get("business_name") or "Open Lines"),
            server_url=f"{vapi.APP_BACKEND_URL}/webhooks/vapi-call-ended",
            api_key=vapi.get_tenant_vapi_key(tenant),
        )
    except Exception as e:
        # We already own a number Vapi can't route to. Hand it straight back
        # rather than start billing for a line that will never ring.
        logger.error("reprovision: Vapi import failed for tenant %s, releasing %s: %s", tenant_id, number, e)
        try:
            await telephony.release_number(sub_sid, sub_token, number)
        except Exception as release_err:
            logger.error("reprovision: rollback release of %s also failed: %s", number, release_err)
        return {"provisioned": False, "number": "", "reason": "vapi_import_failed"}

    # The canonical row, through the SAME path signup uses. This flow had the
    # identical drift W9I-A found in signup: it wrote the legacy scalar and left
    # tenant_phone_numbers unaware of a number it had just bought.
    try:
        reg = await phone_registry.register_permanent(
            tenant_id=tenant_id, e164=number, provider_account_sid=sub_sid,
            provider_sid=number_sid, iso_country=country.strip().upper() or "CA")
        if reg["status"] != phone_registry.OK or not reg.get("row"):
            logger.error("reprovision: canonical registration refused for tenant %s "
                         "(%s) — releasing %s", tenant_id, reg.get("detail"), number)
            try:
                await telephony.release_number(sub_sid, sub_token, number)
            except Exception as release_err:
                logger.error("reprovision: rollback release failed: %s", release_err)
            return {"provisioned": False, "number": "",
                    "reason": "canonical_registration_refused"}
        await phone_registry.mark_active(tenant_id=tenant_id,
                                        number_row_id=reg["row"]["id"], e164=number)
    except Exception as e:
        logger.error("reprovision: canonical phone persistence failed for tenant %s: %s",
                     tenant_id, e)
        return {"provisioned": False, "number": "", "reason": "phone_persistence_failed"}

    try:
        await db.update_tenant(tenant_id, {
            "vapi_phone_number_id": vapi_phone_id,
            # Clear the reclaim history. Leaving number_released_at set would make
            # release_due_at() return None forever, so this new number could never
            # be reclaimed if they lapse again — and the stale warning flags would
            # suppress the notices they'd be owed next time.
            "number_released_at":        None,
            "number_release_warn1_sent": False,
            "number_release_warn2_sent": False,
        })
    except Exception as e:
        logger.error(
            "reprovision: bought %s for tenant %s but the DB write failed: %s — "
            "the number is live on Twilio and must be reconciled by hand",
            number, tenant_id, e,
        )
        return {"provisioned": False, "number": number, "reason": "db_write_failed"}

    logger.info("Reprovisioned number %s for tenant %s (%s)", number, tenant_id, tenant.get("business_name"))
    return {"provisioned": True, "number": number, "reason": ""}
