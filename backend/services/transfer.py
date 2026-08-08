"""
Transfer helpers (pure) for AI Call Routing telephony.

Enforces two decisions:
  * BRIDGED-DIAL: warm/bridged transfer with sipVerb="dial", never blind /
    sipVerb="refer". Dialing keeps the operator on a bridged leg instead of handing
    the call off to the carrier via SIP REFER.

    PRICING NOTE — corrected 2026-08-08 after live validation. Earlier this said the
    dial mode keeps transfer time "inside Vapi's call duration (metered as plan
    minutes)". That is NOT true for our transfer mode. Vapi's call ENDS at the
    hand-off (endedReason="assistant-forwarded-call"): on the validating call,
    durationSeconds stopped ~2s after transferCall fired, before the operator even
    answered. Because usage.record_call_minutes keys off durationSeconds, the
    post-hand-off caller<->operator talk-time is NOT counted against the customer's
    plan minutes. That talk-time runs on the telephony (Twilio) operator leg and is
    absorbed as a small COGS (~a couple cents/min), NOT billed to the customer.
    Capturing the true talk-minutes needs DEFERRED Twilio-leg reconciliation (the
    operator leg is still in progress at end-of-call), and which account bears that
    leg's cost still needs confirming — both tracked as follow-ups (see
    routing_overflow memory). We still prefer dial over refer for a clean bridge.
  * DOMESTIC-ONLY destinations are enforced upstream at destination creation.

Tool type + transferPlan verified against the Vapi OpenAPI spec (schema
TransferCallTool; see routing_overflow memory / Phase 0).
"""
from __future__ import annotations

# Warm transfer that speaks a generated summary to the operator.
# We use the "wait-for-operator-to-speak-first" variant: Vapi dials the operator,
# waits for them to actually answer/say hello, THEN delivers the summary, THEN
# bridges the caller. For a HUMAN operator this is far more reliable than plain
# `warm-transfer-say-summary`, which speaks the moment the leg is dialed and gets
# missed against a ringing/half-answered line (first live test: operator heard no
# summary, caller was bridged straight in).
WARM_MODE = "warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary"
SIP_VERB = "dial"   # keeps a Twilio child leg -> transfer time stays metered
# Time budget to GENERATE the spoken summary. Vapi: if this times out the summary
# is empty and nothing is spoken. 5s was too tight on the first live call; 20s
# comfortably lets the summary generate before the operator is connected.
SUMMARY_TIMEOUT_SECONDS = 20


def build_destination(number: str, mode: str = WARM_MODE) -> dict:
    """The Vapi transfer destination returned to a `transfer-destination-request`.
    Complete transferPlan lives here; the AI never supplies or sees the number."""
    return {
        "type": "number",
        "number": number,
        "numberE164CheckEnabled": True,
        "transferPlan": {
            "mode": mode,
            "sipVerb": SIP_VERB,
            "timeout": 30,
            "dialTimeout": 30,
            # Vapi requires the {{transcript}} template variable in the summaryPlan
            # messages so the summary model actually receives the call content.
            # Without it, no usable summary is generated and NOTHING is spoken to the
            # operator (confirmed on two live calls: operator was bridged in silently).
            # System message carries the instruction; the user message carries the
            # transcript. Warm-transfer summaries require Twilio telephony (we use it).
            "summaryPlan": {
                "enabled": True,
                "timeoutSeconds": SUMMARY_TIMEOUT_SECONDS,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are given the transcript of a phone call to a business. "
                            "In one sentence, tell the operator who is calling and why, "
                            "so they can take over the call."
                        ),
                    },
                    {
                        "role": "user",
                        "content": "Here is the transcript:\n\n{{transcript}}\n\n",
                    },
                ],
            },
        },
    }


def outcome_from_ended_reason(ended_reason: str | None) -> str | None:
    """Map a Vapi call-ended reason to our transfer outcome enum, or None if the
    reason doesn't correspond to a transfer. Reasons verified in Phase 0."""
    r = (ended_reason or "").strip().lower()
    if r == "assistant-forwarded-call":
        return "answered"
    if r == "customer-busy":
        return "busy"
    if r == "customer-did-not-answer" or "silence-timeout" in r:
        return "no_answer"
    if r == "voicemail":
        return "voicemail"
    if "transfer-failed" in r or "warm-transfer" in r:   # error-*-warm-transfer-* / error-transfer-failed
        return "failed"
    if r == "customer-ended-call":
        return "caller_abandoned"
    return None


def disposition_for_outcome(outcome: str | None) -> str:
    """Inbox disposition for a transferred call, from its outcome."""
    if outcome == "answered":
        return "transferred"
    if outcome in ("busy", "no_answer", "voicemail"):
        return "transfer_unanswered"
    if outcome in ("failed", "declined", "caller_abandoned"):
        return "failed"
    return "transfer_unanswered"
