"""Pure transfer helpers: destination builder (metered-mode-only) + outcome/
disposition mapping from Vapi end-of-call reasons."""
from services import transfer as t


def test_build_destination_is_warm_bridged_dial():
    d = t.build_destination("+16475551234")
    assert d["type"] == "number" and d["number"] == "+16475551234"
    plan = d["transferPlan"]
    assert plan["mode"] == "warm-transfer-say-summary"      # warm/bridged
    assert plan["sipVerb"] == "dial"                        # metered-mode-only rule
    assert "summaryPlan" in plan and plan["timeout"] == 30


def test_outcome_mapping():
    assert t.outcome_from_ended_reason("assistant-forwarded-call") == "answered"
    assert t.outcome_from_ended_reason("customer-busy") == "busy"
    assert t.outcome_from_ended_reason("customer-did-not-answer") == "no_answer"
    assert t.outcome_from_ended_reason("call.in-progress.error-warm-transfer-silence-timeout") == "no_answer"
    assert t.outcome_from_ended_reason("voicemail") == "voicemail"
    assert t.outcome_from_ended_reason("call.in-progress.error-transfer-failed") == "failed"
    assert t.outcome_from_ended_reason("customer-ended-call") == "caller_abandoned"
    # a normal (non-transfer) hangup reason doesn't map to a transfer outcome
    assert t.outcome_from_ended_reason("assistant-ended-call") is None
    assert t.outcome_from_ended_reason("") is None


def test_disposition_mapping():
    assert t.disposition_for_outcome("answered") == "transferred"
    assert t.disposition_for_outcome("busy") == "transfer_unanswered"
    assert t.disposition_for_outcome("no_answer") == "transfer_unanswered"
    assert t.disposition_for_outcome("voicemail") == "transfer_unanswered"
    assert t.disposition_for_outcome("failed") == "failed"
    assert t.disposition_for_outcome("caller_abandoned") == "failed"
