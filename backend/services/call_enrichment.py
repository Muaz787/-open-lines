"""
Per-call transcript analysis for AI Insights.

One GPT call extracts BOTH the lead fields we already used (caller_name,
key_details, urgency, summary, suggested_next_step) AND the new enrichment
signals (intent, service_topic, sentiment, pricing_question, ai_confident,
knowledge_gap, gap_topic). Intent classification is the keystone that lets the
insights engine evaluate conversion only among real sales opportunities instead
of treating every call (tests, robocalls, confirmations) as a lost lead.

Used by the end-of-call webhook (live) and by the admin backfill (existing
transcripts).
"""
import os
import json
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


INTENTS = {
    "sales_opportunity", "existing_customer", "booking_confirmation",
    "reschedule_or_cancel", "support_question", "spam_or_robocall",
    "wrong_number", "delivery_or_courier", "other",
}
SENTIMENTS = {"positive", "neutral", "negative"}

# Intents that count as a genuine new sales/booking opportunity (the conversion
# denominator). Everything else is excluded so conversion rate isn't skewed.
OPPORTUNITY_INTENTS = {"sales_opportunity"}


def _norm_intent(v) -> str:
    v = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in INTENTS else "other"


def _norm_sentiment(v) -> str:
    v = str(v or "").strip().lower()
    return v if v in SENTIMENTS else "neutral"


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "yes", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    return None


async def analyze_transcript(transcript: str, tenant: dict) -> dict:
    """Run the combined analysis. Returns a dict with both lead fields and the
    enrichment signals. Raises on hard failure (callers treat as non-fatal)."""
    qualification_fields = tenant.get("qualification_fields") or {}
    industry = tenant.get("industry", "")

    user_prompt = (
        f"Transcript:\n{transcript}\n\n"
        f"Business industry: {industry}\n"
        f"Qualification fields: {json.dumps(qualification_fields)}\n\n"
        "Analyze this phone call to an AI receptionist and return JSON only with these keys:\n"
        "- caller_name: string (or empty)\n"
        "- key_details: object matching the qualification fields above (best effort)\n"
        "- urgency: one of hot, warm, cold\n"
        "- summary: at most 2 sentences\n"
        "- suggested_next_step: short string\n"
        "- intent: ONE of [sales_opportunity, existing_customer, booking_confirmation, "
        "reschedule_or_cancel, support_question, spam_or_robocall, wrong_number, "
        "delivery_or_courier, other]. Use sales_opportunity ONLY for a NEW potential "
        "customer inquiring about services, pricing, availability, or wanting to book. "
        "Tests, telemarketers, surveys, and robocalls are spam_or_robocall. An existing "
        "client calling about a job/appointment already in progress is existing_customer.\n"
        "- service_topic: short label of the main service/topic requested "
        "(e.g. 'Refrigerator repair', 'Property viewing'), or empty string\n"
        "- sentiment: one of positive, neutral, negative\n"
        "- pricing_question: true if the caller asked about price, cost, or fees\n"
        "- ai_confident: true if the assistant answered the caller's questions confidently "
        "and handled the request; false if it struggled or deflected\n"
        "- knowledge_gap: true if the assistant could NOT confidently answer something or "
        "lacked information the caller wanted\n"
        "- gap_topic: if knowledge_gap is true, a short label of what it couldn't answer "
        "(e.g. 'dishwasher pricing', 'warranty coverage'); otherwise empty string\n"
    )

    resp = await _openai().chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You extract structured data and operational signals from AI receptionist call transcripts. Never invent facts. Return valid JSON only."},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)

    return {
        # Lead fields (backward compatible with the previous analysis)
        "caller_name": str(data.get("caller_name", "") or "").strip(),
        "key_details": data.get("key_details") or {},
        "urgency": str(data.get("urgency", "") or "").strip().lower(),
        "summary": str(data.get("summary", "") or "").strip(),
        "suggested_next_step": str(data.get("suggested_next_step", "") or "").strip(),
        # Enrichment signals
        "intent": _norm_intent(data.get("intent")),
        "service_topic": str(data.get("service_topic", "") or "").strip()[:80],
        "sentiment": _norm_sentiment(data.get("sentiment")),
        "pricing_question": bool(_as_bool(data.get("pricing_question"))),
        "ai_confident": _as_bool(data.get("ai_confident")),
        "knowledge_gap": bool(_as_bool(data.get("knowledge_gap"))),
        "gap_topic": str(data.get("gap_topic", "") or "").strip()[:80],
    }


# Keys that belong on the `calls` row (enrichment columns).
CALL_ENRICHMENT_KEYS = (
    "intent", "service_topic", "sentiment", "pricing_question",
    "ai_confident", "knowledge_gap", "gap_topic",
)


def call_enrichment(analysis: dict) -> dict:
    """Pick just the call-row enrichment columns from a full analysis dict."""
    return {k: analysis.get(k) for k in CALL_ENRICHMENT_KEYS}
