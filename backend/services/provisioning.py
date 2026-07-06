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

Also provide exactly 3 qualification questions specific to this business type.

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
        # Match the business's own region: prefer a number in the area code of the
        # business's phone (or the phone the analyzer detected on their website),
        # falling back to the country's popular area codes / a national search.
        preferred_ac = telephony.area_code_from_phone(payload.get("business_phone", ""))
        if not preferred_ac and payload.get("analysis_token"):
            try:
                from services import website_analysis
                _cached = website_analysis.get_cached_scrape(payload["analysis_token"]) or {}
                preferred_ac = telephony.area_code_from_phone((_cached.get("detected") or {}).get("phone", ""))
            except Exception as e:
                logger.warning("[Step %d] Could not derive area code from analysis: %s", step, e)
        if preferred_ac:
            logger.info("[Step %d] Preferring area code %s from business phone", step, preferred_ac)
        phone_number = await telephony.find_available_number(
            subaccount_sid, subaccount_token, country_code, preferred_area_code=preferred_ac)
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
