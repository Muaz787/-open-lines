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

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "knowledge_base" / "templates"

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
    kb_snippet = knowledge_context[:6000] if knowledge_context else "No website content available."

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
        model="gpt-4o",
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

    # Steps 4–11 are wrapped so any failure releases the purchased number before raising
    try:
        return await _provision_after_twilio(
            payload, subaccount_sid, subaccount_token, purchased_number,
            template, qualification_fields,
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
) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]
    owner_name: str = payload.get("owner_name", "")
    whatsapp_number: str = payload.get("whatsapp_number", "")
    website_url: str = payload.get("website_url", "")
    agent_name: str = payload.get("agent_name", "Alex")

    # Step 4 — Scrape website (non-fatal: provisioning continues without knowledge base)
    step = 4
    scraped_text = ""
    if website_url:
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
        greeting_template = (
            f"Hi, thank you for calling {business_name}. "
            f"I'm {agent_name}, your AI assistant. How can I help you today?"
        )
        logger.info("[Step %d] Built greeting template", step)
    except Exception as e:
        logger.error("[Step %d] Greeting template build failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 8 — Build system prompt
    step = 8
    try:
        extra_instructions: str = (payload.get("extra_instructions") or "").strip()

        if industry == "custom":
            logger.info("[Step %d] Generating custom system prompt via GPT-4o", step)
            system_prompt, qualification_fields = await _generate_custom_content(
                business_name=business_name,
                agent_name=agent_name,
                business_description=payload.get("business_description", ""),
                knowledge_context=scraped_text,
                extra_instructions=extra_instructions,
            )
        else:
            qualification_questions = "\n".join(
                f"- {q}" for q in qualification_fields.values()
            )
            knowledge_context = scraped_text[:8000] if scraped_text else "No website content available."
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

    # Step 9 — Create Vapi assistant
    step = 9
    try:
        tenant_stub = {
            "agent_name": agent_name,
            "greeting_template": greeting_template,
        }
        assistant_config = vapi.build_assistant_config(tenant_stub, system_prompt)
        vapi_assistant_id = await vapi.create_assistant(assistant_config)
        logger.info("[Step %d] Created Vapi assistant %s", step, vapi_assistant_id)
    except Exception as e:
        logger.error("[Step %d] Vapi assistant creation failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 10 — Import Twilio number into Vapi and assign assistant
    step = 10
    try:
        await vapi.import_twilio_number(
            phone_number=purchased_number,
            twilio_account_sid=subaccount_sid,
            twilio_auth_token=subaccount_token,
            assistant_id=vapi_assistant_id,
            label=business_name,
        )
        logger.info("[Step %d] Linked %s to Vapi assistant %s", step, purchased_number, vapi_assistant_id)
    except Exception as e:
        logger.error("[Step %d] Vapi phone import failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 11 — Insert tenant row in Supabase
    step = 11
    try:
        tenant_data = {
            "business_name": business_name,
            "industry": industry,
            "owner_name": owner_name,
            "whatsapp_number": whatsapp_number,
            "website_url": website_url,
            "agent_name": agent_name,
            "greeting_template": greeting_template,
            "qualification_fields": qualification_fields,
            "twilio_subaccount_sid": subaccount_sid,
            "twilio_auth_token": subaccount_token,
            "twilio_phone_number": purchased_number,
            "vapi_assistant_id": vapi_assistant_id,
            "pinecone_namespace": pinecone_namespace,
            "is_active": True,
        }
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
