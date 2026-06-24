import os
import re
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import HTTPException
from openai import AsyncOpenAI

from services import telephony, vapi, knowledge
from db import supabase as db

load_dotenv()

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

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
    if industry == "custom":
        raise ValueError("Custom industry tenants must be re-provisioned manually")

    template = _load_template(industry)

    qualification_fields   = QUALIFICATION_FIELDS.get(industry, {})
    qualification_questions = "\n".join(f"- {q}" for q in qualification_fields.values())

    knowledge_context = "No website content available."
    try:
        pinecone_namespace = tenant.get("pinecone_namespace", "")
        if pinecone_namespace:
            structured = await knowledge.build_structured_knowledge(
                pinecone_namespace, business_brief=tenant.get("business_brief") or ""
            )
            if structured:
                knowledge_context = vapi.wrap_untrusted_kb(structured)
    except Exception as e:
        logger.warning("KB fetch failed during reprompt for tenant %s (continuing): %s", tenant_id, e)

    system_prompt = template.format(
        business_name=business_name,
        agent_name=agent_name,
        qualification_questions=qualification_questions,
        knowledge_context=knowledge_context,
    )

    extra = (tenant.get("extra_instructions") or "").strip()
    if extra:
        system_prompt += f"\n\nADDITIONAL INSTRUCTIONS FROM {business_name.upper()}\n{extra}"

    base_system_prompt = system_prompt

    system_prompt += _CALLER_LOOKUP_NOTE
    if tenant.get("google_refresh_token"):
        system_prompt += _CALENDAR_NOTE

    tools = (
        build_calendar_tools(tenant_id)
        if tenant.get("google_refresh_token")
        else [build_caller_lookup_tool(tenant_id)]
    )
    model_payload: dict = {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "temperature": 0.7,
        "messages": [{"role": "system", "content": vapi.ensure_safety_preamble(system_prompt)}],
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
    extra_instructions: str,
) -> tuple[str, dict]:
    """Use GPT-4o to generate a system prompt and qualification fields for a custom business type."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY must be set for custom industry provisioning")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    kb_snippet = vapi.wrap_untrusted_kb(knowledge_context[:6000]) if knowledge_context else "No website content available."

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
   Step 4 — Answer Questions: answer using the knowledge context below
   Step 5 — Arrange Next Steps: schedule, book, or arrange a callback as appropriate
   Step 6 — Confirm Contact Details: NEVER ask the caller to say their phone number (you already have it from caller ID); confirm they can be reached on it
   Step 7 — Warm Wrap-Up
4. RULES section — 6-8 specific, business-relevant rules

The script must use the actual business name ("{business_name}") and agent name ("{agent_name}") throughout, not placeholders.

Knowledge context to include verbatim in Step 4:
{kb_snippet}

Also provide exactly 3 qualification questions specific to this business type.

{"Additional instructions to weave in: " + extra_instructions if extra_instructions else ""}

Return valid JSON only:
{{
  "system_prompt": "...(complete script here)...",
  "qualification_fields": {{
    "key1": "First qualification question?",
    "key2": "Second qualification question?",
    "key3": "Third qualification question?"
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

    if extra_instructions:
        system_prompt += f"\n\nADDITIONAL INSTRUCTIONS FROM {business_name.upper()}\n{extra_instructions}"

    return system_prompt, qualification_fields


async def provision_tenant(payload: dict) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]

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
        phone_number = await telephony.find_available_number(subaccount_sid, subaccount_token, country_code)
        purchased_number = await telephony.purchase_number(subaccount_sid, subaccount_token, phone_number)
        logger.info("[Step %d] Provisioned Twilio number %s", step, purchased_number)
    except Exception as e:
        logger.error("[Step %d] Twilio provisioning failed: %s", step, e)
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
            payload, subaccount_sid, subaccount_token, purchased_number,
            template, qualification_fields, prescraped_text,
        )
    except HTTPException:
        logger.warning("Rolling back: releasing number %s on sub-account %s", purchased_number, subaccount_sid)
        await telephony.release_number(subaccount_sid, subaccount_token, purchased_number)
        raise


async def _provision_after_twilio(
    payload: dict,
    subaccount_sid: str,
    subaccount_token: str,
    purchased_number: str,
    template: str | None,
    qualification_fields: dict | None,
    prescraped_text: str | None = None,
) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]
    owner_name: str = payload.get("owner_name", "")
    whatsapp_number: str = payload.get("whatsapp_number", "")
    website_url: str = payload.get("website_url", "")
    agent_name: str = payload.get("agent_name", "Alex")

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
    try:
        extra_instructions: str = (payload.get("extra_instructions") or "").strip()

        # Prefer the structured Business Brief from analysis; fall back to raw scrape.
        brief_text = (predetected.get("business_brief") or "").strip()

        if industry == "custom":
            logger.info("[Step %d] Generating custom system prompt via GPT-4o", step)
            system_prompt, qualification_fields = await _generate_custom_content(
                business_name=business_name,
                agent_name=agent_name,
                business_description=payload.get("business_description", ""),
                knowledge_context=brief_text or scraped_text,
                extra_instructions=extra_instructions,
            )
        else:
            qualification_questions = "\n".join(
                f"- {q}" for q in qualification_fields.values()
            )
            kb_text = brief_text or scraped_text[:8000]
            knowledge_context = vapi.wrap_untrusted_kb(kb_text) if kb_text else "No website content available."
            system_prompt = template.format(
                business_name=business_name,
                agent_name=agent_name,
                qualification_questions=qualification_questions,
                knowledge_context=knowledge_context,
            )
            if extra_instructions:
                system_prompt += f"\n\nADDITIONAL INSTRUCTIONS FROM {business_name.upper()}\n{extra_instructions}"

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
            "whatsapp_number": whatsapp_number,
            "website_url": website_url,
            "agent_name": agent_name,
            "greeting_template": greeting_template,
            "qualification_fields": qualification_fields,
            "twilio_subaccount_sid": subaccount_sid,
            "twilio_auth_token": subaccount_token,
            "twilio_phone_number": purchased_number,
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
        tenant = await db.insert_tenant(tenant_data)
        tenant_id = tenant["id"]
        logger.info("[Step %d] Inserted tenant %s", step, tenant_id)
    except Exception as e:
        logger.error("[Step %d] Supabase insert failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    return {
        "tenant_id": tenant_id,
        "phone_number": purchased_number,
        "assistant_id": vapi_assistant_id,
        "status": "live",
        "dashboard_url": f"{FRONTEND_URL}/dashboard/{tenant_id}",
    }
