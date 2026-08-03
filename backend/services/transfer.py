"""
Transfer helpers (pure) for AI Call Routing telephony.

Enforces the two locked decisions:
  * METERED-MODE-ONLY: warm/bridged transfer with sipVerb="dial" so the whole
    transfer stays inside Vapi's call duration (metered as ordinary call minutes;
    the "absorb into plan minutes" pricing model relies on this). NEVER blind /
    sipVerb="refer" (carrier hand-off would drop the call out of the meter).
  * DOMESTIC-ONLY destinations are enforced upstream at destination creation.

Tool type + transferPlan verified against the Vapi OpenAPI spec on 2026-08-02
(schema TransferCallTool; see routing_overflow memory / Phase 0).
"""
from __future__ import annotations

# Warm transfer that speaks a generated summary to the operator (M1 in Phase 0).
WARM_MODE = "warm-transfer-say-summary"
SIP_VERB = "dial"   # keeps a Twilio child leg -> transfer time stays metered


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
            "summaryPlan": {
                "enabled": True,
                "timeoutSeconds": 5,
                "messages": [{
                    "role": "system",
                    "content": "In one sentence, tell the operator who is calling and why.",
                }],
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
