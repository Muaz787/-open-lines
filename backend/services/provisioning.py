import os
import re
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import HTTPException

from services import telephony, vapi, knowledge
from db import supabase as db

load_dotenv()

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "")

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


async def provision_tenant(payload: dict) -> dict:
    business_name: str = payload["business_name"]
    industry: str = payload["industry"]
    owner_name: str = payload.get("owner_name", "")
    whatsapp_number: str = payload.get("whatsapp_number", "")
    website_url: str = payload.get("website_url", "")
    agent_name: str = payload.get("agent_name", "Alex")

    # Step 1 — Load system prompt template
    step = 1
    try:
        template = _load_template(industry)
        logger.info("[Step %d] Loaded template for industry '%s'", step, industry)
    except Exception as e:
        logger.error("[Step %d] Failed to load template: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 2 — Build qualification fields
    step = 2
    try:
        qualification_fields = QUALIFICATION_FIELDS.get(industry)
        if qualification_fields is None:
            raise ValueError(f"No qualification fields defined for industry '{industry}'")
        logger.info("[Step %d] Built qualification fields for '%s'", step, industry)
    except Exception as e:
        logger.error("[Step %d] Failed to build qualification fields: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 3 — Create Twilio sub-account, find and purchase a local number
    step = 3
    try:
        subaccount = await telephony.create_subaccount(business_name)
        subaccount_sid = subaccount["sid"]
        subaccount_token = subaccount["auth_token"]
        phone_number = await telephony.find_available_number(subaccount_sid, subaccount_token)
        purchased_number = await telephony.purchase_number(subaccount_sid, subaccount_token, phone_number)
        logger.info("[Step %d] Provisioned Twilio number %s", step, purchased_number)
    except Exception as e:
        logger.error("[Step %d] Twilio provisioning failed: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")

    # Step 4 — Scrape website
    step = 4
    scraped_text = ""
    if website_url:
        try:
            scraped_text = await knowledge.scrape_website(website_url)
            logger.info("[Step %d] Scraped website %s", step, website_url)
        except Exception as e:
            logger.error("[Step %d] Website scrape failed: %s", step, e)
            raise HTTPException(status_code=500, detail=f"Step {step} failed: {e}")
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
            # tenant_id is not yet known; use namespace as a stable identifier
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

    # Step 8 — Fill system prompt template
    step = 8
    try:
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
        logger.info("[Step %d] Filled system prompt template", step)
    except KeyError as e:
        logger.error("[Step %d] Missing placeholder in template: %s", step, e)
        raise HTTPException(status_code=500, detail=f"Step {step} failed: missing placeholder {e}")
    except Exception as e:
        logger.error("[Step %d] System prompt fill failed: %s", step, e)
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

    # Step 10 — Insert tenant row in Supabase
    step = 10
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

    # Step 11 — Return provisioning result
    return {
        "tenant_id": tenant_id,
        "phone_number": purchased_number,
        "assistant_id": vapi_assistant_id,
        "status": "live",
        "dashboard_url": f"{FRONTEND_URL}/dashboard/{tenant_id}",
    }
