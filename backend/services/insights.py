"""
AI Insights v2 — an "operations consultant" over a tenant's calls.

Design (per product spec):
  1. Aggregate per-call enrichment (intent/service/sentiment/knowledge gaps) +
     leads + appointments into deterministic FACTS in code — including
     sample sizes, so confidence is grounded in real evidence and conversion is
     measured ONLY among genuine sales opportunities (not tests/robocalls).
  2. One GPT "consultant" pass turns the significant facts into well-written,
     evidence-bearing insights / action items / knowledge improvements. It is
     told to use only the numbers we provide and to copy the evidence_count, so
     we can attach confidence deterministically and never invent strong claims
     from weak evidence.
  3. Result is cached per tenant and regenerated on demand (stale when new calls
     have arrived).
"""
import os
import json
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from db import supabase as db
from services.call_enrichment import OPPORTUNITY_INTENTS

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIN_OPP_FOR_CONVERSION = 5     # need this many sales opps before quoting a rate
MIN_CALLS_FOR_NARRATIVE = 3    # below this we show metrics only, no narrative
_ALLOWED_SEVERITY = {"positive", "opportunity", "monitor", "action"}

_client: AsyncOpenAI | None = None


def _openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _confidence(n: int) -> tuple[str, int]:
    if n >= 30:
        return ("high", 95)
    if n >= 12:
        return ("medium", 78)
    if n >= 5:
        return ("low", 55)
    return ("low", 38)


# --------------------------------------------------------------------------- #
# Data gathering
# --------------------------------------------------------------------------- #
async def _gather(tenant_id: str, days: int) -> tuple[list, list, list]:
    client = db.get_client()
    since = (_now() - timedelta(days=days)).isoformat()
    calls = (client.table("calls")
             .select("id,lead_id,duration_secs,created_at,intent,service_topic,sentiment,"
                     "pricing_question,ai_confident,knowledge_gap,gap_topic")
             .eq("tenant_id", tenant_id).gte("created_at", since).limit(5000).execute().data or [])
    leads = (client.table("leads")
             .select("id,phone,urgency,status,summary,created_at")
             .eq("tenant_id", tenant_id).gte("created_at", since).limit(5000).execute().data or [])
    appts = (client.table("appointments")
             .select("id,service,status,caller_phone,created_at")
             .eq("tenant_id", tenant_id).gte("created_at", since).limit(5000).execute().data or [])
    return calls, leads, appts


async def _total_call_count(tenant_id: str) -> int:
    res = db.get_client().table("calls").select("id", count="exact").eq("tenant_id", tenant_id).execute()
    return res.count or 0


# --------------------------------------------------------------------------- #
# Aggregation (deterministic facts)
# --------------------------------------------------------------------------- #
def _aggregate(calls: list, leads: list, appts: list) -> dict:
    total_calls = len(calls)
    intents = Counter((c.get("intent") or "other") for c in calls)
    opps = sum(intents[i] for i in OPPORTUNITY_INTENTS)

    appts_booked = sum(1 for a in appts if a.get("status") != "cancelled")
    cancelled = sum(1 for a in appts if a.get("status") == "cancelled")
    conversion = round(appts_booked / opps * 100) if opps >= MIN_OPP_FOR_CONVERSION else None

    durs = [c["duration_secs"] for c in calls if c.get("duration_secs")]
    avg_dur = round(sum(durs) / len(durs)) if durs else 0

    hot = sum(1 for l in leads if l.get("urgency") == "hot")
    warm = sum(1 for l in leads if l.get("urgency") == "warm")

    conf_vals = [c["ai_confident"] for c in calls if c.get("ai_confident") is not None]
    ai_conf_pct = round(sum(1 for v in conf_vals if v) / len(conf_vals) * 100) if conf_vals else None

    gap_calls = [c for c in calls if c.get("knowledge_gap")]
    gap_topics = Counter((c.get("gap_topic") or "general questions").strip().lower()
                         for c in gap_calls if (c.get("gap_topic") or "").strip())
    services = Counter(s for c in calls if (s := (c.get("service_topic") or "").strip()))
    pricing = sum(1 for c in calls if c.get("pricing_question"))
    sentiments = Counter((c.get("sentiment") or "neutral") for c in calls)

    hours: Counter = Counter()
    weekdays: Counter = Counter()
    for c in calls:
        try:
            dt = _parse_ts(c["created_at"])
        except Exception:
            continue
        hours[dt.hour] += 1
        weekdays[dt.strftime("%A")] += 1

    calls_per_lead = Counter(c.get("lead_id") for c in calls)
    returning = sum(1 for _, n in calls_per_lead.items() if n > 1)

    appt_phones = {a.get("caller_phone") for a in appts if a.get("status") != "cancelled"}
    follow_up = sum(1 for l in leads if l.get("urgency") in ("hot", "warm") and l.get("phone") not in appt_phones)

    busiest_hour = hours.most_common(1)[0] if hours else None
    busiest_day = weekdays.most_common(1)[0] if weekdays else None

    return {
        "total_calls": total_calls,
        "sales_opportunities": opps,
        "intent_breakdown": dict(intents),
        "new_leads": len(leads),
        "appointments_booked": appts_booked,
        "appointments_cancelled": cancelled,
        "booking_conversion_rate": conversion,
        "returning_customers": returning,
        "avg_call_duration_secs": avg_dur,
        "hot_leads": hot,
        "warm_leads": warm,
        "follow_up_required": follow_up,
        "ai_confidence_score": ai_conf_pct,
        "ai_confidence_sample": len(conf_vals),
        "knowledge_gap_calls": len(gap_calls),
        "knowledge_gaps_detected": len(gap_topics),
        "top_gap_topics": gap_topics.most_common(5),
        "top_services": services.most_common(6),
        "pricing_questions": pricing,
        "sentiment_breakdown": dict(sentiments),
        "busiest_hour": busiest_hour,
        "busiest_weekday": busiest_day,
    }


def _performance(facts: dict) -> dict:
    note = None
    if facts["booking_conversion_rate"] is None and facts["sales_opportunities"] < MIN_OPP_FOR_CONVERSION:
        note = (f"Only {facts['sales_opportunities']} genuine sales opportunities so far — "
                "not enough to evaluate booking conversion reliably yet.")
    return {
        "calls_answered": facts["total_calls"],
        "sales_opportunities": facts["sales_opportunities"],
        "new_leads": facts["new_leads"],
        "appointments_booked": facts["appointments_booked"],
        "booking_conversion_rate": facts["booking_conversion_rate"],
        "conversion_note": note,
        "returning_customers": facts["returning_customers"],
        "avg_call_duration_secs": facts["avg_call_duration_secs"],
        "hot_leads": facts["hot_leads"],
        "follow_up_required": facts["follow_up_required"],
        "ai_confidence_score": facts["ai_confidence_score"],
        "knowledge_gaps_detected": facts["knowledge_gaps_detected"],
    }


def _sample_conversations(calls: list, leads: list, limit: int = 18) -> list:
    """Compact, summarized grounding for the LLM — opportunities and gap calls
    first, using the lead summary (never raw transcripts → bounded tokens)."""
    lead_by_id = {l["id"]: l for l in leads}
    picked = []
    for c in calls:
        is_opp = c.get("intent") in OPPORTUNITY_INTENTS
        is_gap = bool(c.get("knowledge_gap"))
        if not (is_opp or is_gap):
            continue
        summ = (lead_by_id.get(c.get("lead_id"), {}) or {}).get("summary") or ""
        picked.append({
            "intent": c.get("intent"),
            "service": c.get("service_topic") or "",
            "sentiment": c.get("sentiment") or "",
            "pricing_question": bool(c.get("pricing_question")),
            "knowledge_gap": bool(c.get("knowledge_gap")),
            "gap_topic": c.get("gap_topic") or "",
            "summary": summ[:240],
        })
        if len(picked) >= limit:
            break
    return picked


# --------------------------------------------------------------------------- #
# GPT consultant pass
# --------------------------------------------------------------------------- #
async def _consult(facts: dict, samples: list, business_name: str, industry: str) -> dict:
    prompt = (
        f"You are an experienced operations consultant reviewing one week of phone "
        f"activity for {business_name or 'a business'} (industry: {industry or 'unknown'}), "
        f"answered by an AI receptionist.\n\n"
        f"AGGREGATE FACTS (use ONLY these numbers — never invent figures):\n"
        f"{json.dumps(facts, indent=2)}\n\n"
        f"REPRESENTATIVE CONVERSATIONS (summaries):\n{json.dumps(samples, indent=2)}\n\n"
        "Write like a sharp consultant briefing the owner — specific, evidence-based, "
        "non-generic. Return JSON with:\n"
        '{\n'
        '  "headline": "one-sentence executive takeaway",\n'
        '  "insights": [ {"title": str, "body": "an OBSERVED pattern, not advice", '
        '"severity": "positive|opportunity|monitor|action", "evidence_count": int} ],\n'
        '  "action_items": [ {"title": str, "what_happened": str, "why": "why it matters", '
        '"recommendation": "what to change", "expected_benefit": str, '
        '"severity": "opportunity|monitor|action", "evidence_count": int} ],\n'
        '  "knowledge_improvements": [ {"title": str, "recommendation": "what to add to the '
        'knowledge base and why", "severity": "opportunity|monitor", "evidence_count": int} ]\n'
        '}\n\n'
        "Rules:\n"
        "- evidence_count = how many conversations/data points each item is based on, taken "
        "from the facts. Be honest; small numbers are fine.\n"
        "- Do NOT comment on booking conversion if booking_conversion_rate is null.\n"
        "- Prefer 3-5 insights, 2-4 action items, and knowledge improvements ONLY for real "
        "recurring gaps (top_gap_topics). Return [] for any section without enough evidence.\n"
        "- Never give generic advice ('improve qualification'); always tie to the data.\n"
    )
    resp = await _openai().chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are a precise, evidence-driven business operations consultant. Output valid JSON only. Never invent numbers."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(resp.choices[0].message.content)


def _clamp_severity(v, default: str) -> str:
    v = str(v or "").strip().lower()
    return v if v in _ALLOWED_SEVERITY else default


def _attach_conf(item: dict) -> dict:
    n = int(item.get("evidence_count") or 0)
    level, pct = _confidence(n)
    item["sample_size"] = n
    item["confidence"] = level
    item["confidence_pct"] = pct
    return item


# --------------------------------------------------------------------------- #
# Public: generate + cache
# --------------------------------------------------------------------------- #
async def generate(tenant: dict) -> dict:
    tenant_id = tenant["id"]
    calls, leads, appts = await _gather(tenant_id, WINDOW_DAYS)
    facts = _aggregate(calls, leads, appts)
    perf = _performance(facts)

    ai_perf = {
        "confidence_pct": facts["ai_confidence_score"],
        "sample": facts["ai_confidence_sample"],
        "knowledge_gap_calls": facts["knowledge_gap_calls"],
        "notes": [],
    }

    payload: dict = {
        "window_label": f"last {WINDOW_DAYS} days",
        "headline": None,
        "performance": perf,
        "insights": [],
        "action_items": [],
        "knowledge_improvements": [],
        "ai_performance": ai_perf,
        "data_basis": {"total_calls": facts["total_calls"], "window_days": WINDOW_DAYS},
    }

    if facts["total_calls"] < MIN_CALLS_FOR_NARRATIVE:
        payload["headline"] = "Not enough calls yet to surface reliable patterns — metrics will sharpen as more calls come in."
        return payload

    try:
        out = await _consult(facts, _sample_conversations(calls, leads),
                             tenant.get("business_name", ""), tenant.get("industry", ""))
    except Exception as e:
        logger.error("insights consult failed for tenant %s: %s", tenant_id, e)
        payload["headline"] = "Metrics are ready; the narrative analysis is temporarily unavailable — try refreshing."
        return payload

    payload["headline"] = str(out.get("headline") or "").strip() or None

    for it in (out.get("insights") or [])[:6]:
        if not it.get("title"):
            continue
        payload["insights"].append(_attach_conf({
            "title": str(it.get("title")).strip(),
            "body": str(it.get("body") or "").strip(),
            "severity": _clamp_severity(it.get("severity"), "opportunity"),
            "evidence_count": it.get("evidence_count"),
        }))

    for it in (out.get("action_items") or [])[:5]:
        if not it.get("title"):
            continue
        payload["action_items"].append(_attach_conf({
            "title": str(it.get("title")).strip(),
            "what_happened": str(it.get("what_happened") or "").strip(),
            "why": str(it.get("why") or "").strip(),
            "recommendation": str(it.get("recommendation") or "").strip(),
            "expected_benefit": str(it.get("expected_benefit") or "").strip(),
            "severity": _clamp_severity(it.get("severity"), "action"),
            "evidence_count": it.get("evidence_count"),
        }))

    for it in (out.get("knowledge_improvements") or [])[:5]:
        if not it.get("title"):
            continue
        payload["knowledge_improvements"].append(_attach_conf({
            "title": str(it.get("title")).strip(),
            "recommendation": str(it.get("recommendation") or "").strip(),
            "severity": _clamp_severity(it.get("severity"), "opportunity"),
            "evidence_count": it.get("evidence_count"),
        }))

    return payload


async def _read_cache(tenant_id: str) -> dict | None:
    res = db.get_client().table("ai_insights").select("*").eq("tenant_id", tenant_id).limit(1).execute()
    return (res.data or [None])[0]


async def _write_cache(tenant_id: str, payload: dict, count: int) -> None:
    db.get_client().table("ai_insights").upsert({
        "tenant_id": tenant_id,
        "payload": payload,
        "generated_at": _now().isoformat(),
        "source_call_count": count,
    }).execute()


async def get_insights(tenant: dict, refresh: bool = False) -> dict:
    """Return cached insights (fast). Generates only on `refresh` or when no
    cache exists yet. Marks `stale` when new calls have arrived since caching."""
    tenant_id = tenant["id"]
    count = await _total_call_count(tenant_id)
    cache = await _read_cache(tenant_id)

    if cache and not refresh:
        return {
            **cache["payload"],
            "generated_at": cache.get("generated_at"),
            "stale": count != (cache.get("source_call_count") or 0),
            "has_data": True,
        }

    if not cache and not refresh:
        # Keep first load fast — let the UI offer "Generate".
        return {"has_data": False, "generated_at": None, "stale": False}

    payload = await generate(tenant)
    try:
        await _write_cache(tenant_id, payload, count)
    except Exception as e:
        logger.error("insights cache write failed for tenant %s: %s", tenant_id, e)
    return {**payload, "generated_at": _now().isoformat(), "stale": False, "has_data": True}
