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
import re
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


# Larger input cap than before (was 6k) — richer extraction; still cost-reasonable
# for gpt-4.1-mini (~4-5k input tokens).
ANALYZE_INPUT_CHARS = 16000


async def classify_text(text: str, url: str = "", max_chars: int = ANALYZE_INPUT_CHARS) -> dict:
    """Public: run the structured Business Brief extraction on already-fetched
    content (used by the multi-page re-crawl, which passes a larger window so the
    brief reflects the whole site, not just the homepage)."""
    if not text or not text.strip():
        return _empty_detection()
    return await _classify(text, url, max_chars=max_chars)


def _empty_detection() -> dict:
    return {
        "business_name": "",
        "industry": "custom",
        "industry_confidence": 0.0,
        "country": "",
        "phone": "",
        "services": [],
        "service_areas": [],
        "faqs": [],
        "policies": [],
        "faq_count": 0,
        "suggested_instructions": "",
        "business_brief": "",
        "knowledge_preview": "",
    }


async def _classify(text: str, url: str, max_chars: int = ANALYZE_INPUT_CHARS) -> dict:
    if not OPENAI_API_KEY:
        logger.warning("Onboarding analyze: OPENAI_API_KEY unset — skipping classification")
        return _empty_detection()

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    snippet = text[:max_chars]

    user_prompt = f"""You are extracting knowledge for an AI phone receptionist from a business website.
Use ONLY facts present in the content below — never invent prices, hours, guarantees, or services.

Website URL: {url}
Website content (markdown, truncated):
{snippet}

Return valid JSON only with these keys:
{{
  "business_name": "the business's name, or empty string if unclear",
  "industry": "ONE of: realtor, clinic, dental, legal, plumber, builder, restaurant, beauty, parliament, custom",
  "industry_confidence": 0.0-1.0,
  "business_subtype": "a short, specific business type in 1-4 words (e.g. 'sushi restaurant', 'med spa', 'appliance repair', 'real estate team', 'pediatric dental clinic'), or empty string if unclear",
  "country": "ISO 3166-1 alpha-2 code ONLY when the site clearly shows the business's country — via a postal/mailing address, a phone number written with an international dialing code, or an explicit country/region statement. Do NOT guess from the domain, language, currency, or example content. If there is no clear signal, return an empty string.",
  "phone": "the business's primary public phone number exactly as written on the site (digits/+/()-/spaces), or empty string if none is shown",
  "services": ["up to 12 specific services offered (e.g. 'Refrigerator repair', 'Career Pilot Program')"],
  "service_areas": ["cities/regions/neighbourhoods served, if stated"],
  "faqs": [{{"q": "question a caller might ask", "a": "the answer from the site"}}],
  "policies": ["warranty/guarantee, labour/parts, cancellation, emergency/same-day, payment, or other notable policies, each as one line"],
  "behavioral_instructions": "5-8 newline-separated lines telling the AI HOW TO BEHAVE on calls for THIS business (book/qualify, what details to collect, when to take a message, how to handle pricing-by-diagnosis). Imperative. Behaviour only — NOT facts. When mentioning booking, say the appointment goes into the business's own calendar (never 'the customer's calendar'). For transparency, phrase it as letting callers know they've reached the business's virtual/automated receptionist — do NOT use the bare term 'AI'.",
  "business_brief": "A detailed, factual brief about the business written as plain text with short labelled sections. Include ONLY what the site supports, drawn from: Services (with brief descriptions), Service areas, Hours, Contact (phone/email), Booking process, Pricing, Warranty/guarantee, Emergency/same-day availability, Brands served, Special programs, Key policies, and Common caller questions with answers. Be specific and concise. This is FACTS the AI will answer from."
}}

Classify by what THIS business itself does for its OWN customers. Ignore industries it merely mentions as examples, case studies, integrations, or client verticals it serves — e.g. a software/SaaS/marketing/agency site that lists industries it helps is 'custom', NOT those industries. Set industry_confidence honestly: use below 0.5 when the site is generic, ambiguous, or is itself a tool/platform rather than a local service business.

industry hints: HVAC/roofing/plumbing/appliance-repair -> plumber; general contractor/renovation -> builder; medical/physio clinic -> clinic; dentist/orthodontist -> dental; lawyer -> legal; salon/spa/barber -> beauty; cafe/bar/eatery -> restaurant; estate agent/property -> realtor; flight school / aviation / driving school / tutoring / software / SaaS / other services -> custom; if none fit -> custom."""

    try:
        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You extract structured, factual business data from website content for an AI receptionist. Never invent facts. Always return valid JSON."},
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

    # Detected business phone — keep only phone-ish characters, drop if implausible.
    phone = str(data.get("phone", "") or "").strip()[:32]
    if phone and not re.fullmatch(r"[+]?[0-9 ()\-.]{6,32}", phone):
        phone = ""

    def _str_list(v, limit: int, maxlen: int = 80) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(x).strip()[:maxlen] for x in v if str(x).strip()][:limit]

    services      = _str_list(data.get("services"), 12)
    service_areas = _str_list(data.get("service_areas"), 20, 60)
    policies      = _str_list(data.get("policies"), 12, 200)

    faqs_raw = data.get("faqs") or []
    faqs = []
    if isinstance(faqs_raw, list):
        for f in faqs_raw[:10]:
            if isinstance(f, dict) and str(f.get("q", "")).strip():
                faqs.append({"q": str(f["q"]).strip()[:200], "a": str(f.get("a", "")).strip()[:600]})

    try:
        confidence = float(data.get("industry_confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "business_name": str(data.get("business_name", "") or "").strip()[:120],
        "industry": industry,
        "industry_confidence": round(max(0.0, min(1.0, confidence)), 2),
        "business_subtype": str(data.get("business_subtype", "") or "").strip()[:60],
        "country": country,
        "phone": phone,
        "services": services,
        "service_areas": service_areas,
        "faqs": faqs,
        "policies": policies,
        "faq_count": len(faqs),
        "suggested_instructions": str(data.get("behavioral_instructions", "") or "").strip()[:1500],
        "business_brief": str(data.get("business_brief", "") or "").strip()[:8000],
        "knowledge_preview": snippet[:280],
    }
