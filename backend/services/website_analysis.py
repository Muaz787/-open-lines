"""
Pre-provision website analysis for onboarding: scrape the business website,
classify the industry, and extract business name / country / services / FAQs /
suggested AI instructions — so the UI can demonstrate value before the (slow)
provisioning step.

The scraped markdown is cached in-memory under a short-lived token so the
subsequent /onboarding/provision call can reuse it instead of scraping twice.
"""
import os
import json
import time
import uuid
import logging

from openai import AsyncOpenAI

from services import knowledge

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Must mirror VALID_INDUSTRIES in routers/onboarding.py
_INDUSTRIES = (
    "realtor", "clinic", "dental", "legal", "plumber",
    "builder", "restaurant", "beauty", "parliament", "custom",
)

# ---------------------------------------------------------------------------
# In-memory scrape cache (analyze -> provision happen within ~1 min)
# ---------------------------------------------------------------------------

_CACHE: dict[str, dict] = {}
_TTL_SECONDS = 1800  # 30 min


def _evict() -> None:
    cutoff = time.time() - _TTL_SECONDS
    for k in [k for k, v in _CACHE.items() if v["ts"] < cutoff]:
        _CACHE.pop(k, None)


def cache_scrape(text: str, detected: dict) -> str:
    _evict()
    token = uuid.uuid4().hex
    _CACHE[token] = {"text": text, "detected": detected, "ts": time.time()}
    return token


def get_cached_scrape(token: str) -> dict | None:
    _evict()
    return _CACHE.get(token)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

async def analyze_website(url: str) -> dict:
    """Scrape + classify. Returns detected fields plus an analysis_token that
    /provision can use to reuse the scrape. Never raises for a failed scrape —
    returns scrape_ok=False so the user can still proceed manually."""
    text = ""
    scrape_ok = True
    try:
        text = await knowledge.scrape_website(url)
    except Exception as e:
        logger.warning("Onboarding analyze: scrape failed for %s: %s", url, e)
        scrape_ok = False

    if not text:
        scrape_ok = False

    detected = await _classify(text, url) if text else _empty_detection()
    token = cache_scrape(text, detected)

    return {
        **detected,
        "analysis_token": token,
        "scrape_ok": scrape_ok,
        "knowledge_chars": len(text),
    }


def _empty_detection() -> dict:
    return {
        "business_name": "",
        "industry": "custom",
        "industry_confidence": 0.0,
        "country": "",
        "services": [],
        "faq_count": 0,
        "suggested_instructions": "",
        "knowledge_preview": "",
    }


async def _classify(text: str, url: str) -> dict:
    if not OPENAI_API_KEY:
        logger.warning("Onboarding analyze: OPENAI_API_KEY unset — skipping classification")
        return _empty_detection()

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    snippet = text[:6000]

    user_prompt = f"""Analyse this business website and extract structured data.

Website URL: {url}
Website content (markdown, truncated):
{snippet}

Return valid JSON only with these keys:
{{
  "business_name": "the business's name, or empty string if unclear",
  "industry": "ONE of: realtor, clinic, dental, legal, plumber, builder, restaurant, beauty, parliament, custom",
  "industry_confidence": 0.0-1.0,
  "country": "ISO 3166-1 alpha-2 code (e.g. CA, US, GB, AU, IE, NZ) inferred from address/phone/domain, or empty string",
  "services": ["up to 6 short service names the business offers"],
  "faq_count": <integer estimate of distinct FAQs/questions answerable from the site>,
  "suggested_instructions": "3-5 short newline-separated instruction lines for an AI phone receptionist for THIS business (e.g. 'Answer listing inquiries', 'Schedule property viewings'). Imperative, one per line."
}}

industry mapping hints: HVAC/roofing/plumbing -> plumber; general contractor/renovation -> builder; medical/physio/health clinic -> clinic; dentist/orthodontist -> dental; lawyer/solicitor -> legal; salon/spa/barber -> beauty; cafe/bar/eatery -> restaurant; estate agent/property -> realtor; if none fit -> custom."""

    try:
        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You extract structured business data from website content. Always return valid JSON."},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.warning("Onboarding analyze: classification failed for %s: %s", url, e)
        return _empty_detection()

    industry = str(data.get("industry", "custom")).lower().strip()
    if industry not in _INDUSTRIES:
        industry = "custom"

    country = str(data.get("country", "") or "").upper().strip()[:2]

    services = data.get("services") or []
    if isinstance(services, list):
        services = [str(s).strip() for s in services if str(s).strip()][:6]
    else:
        services = []

    try:
        confidence = float(data.get("industry_confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        faq_count = int(data.get("faq_count", 0))
    except (TypeError, ValueError):
        faq_count = 0

    return {
        "business_name": str(data.get("business_name", "") or "").strip()[:120],
        "industry": industry,
        "industry_confidence": round(max(0.0, min(1.0, confidence)), 2),
        "country": country,
        "services": services,
        "faq_count": max(0, faq_count),
        "suggested_instructions": str(data.get("suggested_instructions", "") or "").strip()[:1200],
        "knowledge_preview": snippet[:280],
    }
