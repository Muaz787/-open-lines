"""Pure transfer helpers: destination builder (metered-mode-only) + outcome/
disposition mapping from Vapi end-of-call reasons."""
from services import transfer as t


# Vapi schema enums confirmed against the OpenAPI spec (2026-08-03):
# TransferPlan.mode includes 'warm-transfer-say-summary' (NOT 'warm-transfer-with-summary'),
# TransferPlan.sipVerb includes 'dial', and TransferDestinationNumber accepts 'transferPlan'.
VALID_TRANSFER_MODES = {
    "blind-transfer", "blind-transfer-add-summary-to-sip-header",
    "warm-transfer-say-message", "warm-transfer-say-summary", "warm-transfer-twiml",
    "warm-transfer-wait-for-operator-to-speak-first-and-then-say-message",
    "warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary",
    "warm-transfer-experimental",
}


def test_build_destination_is_warm_bridged_dial():
    d = t.build_destination("+16475551234")
    assert d["type"] == "number" and d["number"] == "+16475551234"
    plan = d["transferPlan"]
    # wait-for-operator variant: speak the summary only AFTER a human answers (first
    # live test showed plain say-summary was missed against a half-answered line)
    assert plan["mode"] == "warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary"
    assert plan["sipVerb"] == "dial"                        # metered-mode-only rule
    assert "summaryPlan" in plan and plan["timeout"] == 30


def test_summary_plan_has_generous_generation_timeout():
    # 5s was too tight on the first live call (empty summary -> nothing spoken).
    # Give the summary time to generate before the operator is connected.
    plan = t.build_destination("+16475551234")["transferPlan"]
    assert plan["summaryPlan"]["enabled"] is True
    assert plan["summaryPlan"]["timeoutSeconds"] >= 15


def test_dynamic_destination_carries_schema_valid_plan():
    # The complete warm-transfer plan lives ONLY on the dynamic destination (not on
    # the assistant tool), and every value it uses is a current Vapi schema enum.
    plan = t.build_destination("+16475551234")["transferPlan"]
    assert plan["mode"] in VALID_TRANSFER_MODES
    assert plan["sipVerb"] in {"refer", "bye", "dial"}
    assert plan["summaryPlan"]["enabled"] is True


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
