"""Deterministic routing engine: priority, urgent/emergency handling, safe
fallback, and no-arbitrary-dialing (destinations resolved by id only)."""
from services import routing_engine as re


DESTS = {
    "reg": {"type": "phone", "enabled": True},
    "urgent": {"type": "phone", "enabled": True},
    "sales": {"type": "phone", "enabled": True},
    "disabled": {"type": "phone", "enabled": False},
}
PROFILE = {
    "default_destination_id": "reg", "urgent_destination_id": "urgent",
    "default_fallback_action": "callback", "confidence_threshold": 0.6,
}


def test_public_emergency_never_dials():
    d = re.evaluate(PROFILE, [], DESTS, {"intent": "public_emergency"})
    assert d.decision == "handled_ai"
    assert d.destination_id is None


def test_business_urgent_routes_to_oncall():
    d = re.evaluate(PROFILE, [], DESTS, {"urgency": "urgent"})
    assert d.decision == "transfer" and d.destination_id == "urgent"


def test_urgent_without_valid_destination_falls_back_safely():
    prof = {**PROFILE, "urgent_destination_id": "missing"}
    d = re.evaluate(prof, [], DESTS, {"urgency": "emergency_service"})
    assert d.decision == "callback"


def test_rule_priority_first_match_wins():
    rules = [
        {"id": "r2", "priority": 20, "match": {"intent": "sales"}, "destination_id": "sales"},
        {"id": "r1", "priority": 10, "match": {"intent": "sales"}, "destination_id": "reg"},
    ]
    d = re.evaluate(PROFILE, rules, DESTS, {"intent": "sales"})
    assert d.matched_rule_id == "r1" and d.destination_id == "reg"


def test_keyword_and_returning_conditions():
    rules = [{"id": "vip", "priority": 5,
              "match": {"new_vs_returning": "returning", "keywords": ["refund"]},
              "destination_id": "sales"}]
    hit = re.evaluate(PROFILE, rules, DESTS, {"is_returning": True, "text": "I need a refund please"})
    assert hit.destination_id == "sales"
    miss = re.evaluate(PROFILE, rules, DESTS, {"is_returning": False, "text": "refund"})
    assert miss.destination_id == "reg"           # not returning -> default


def test_disabled_rule_skipped():
    rules = [{"id": "off", "priority": 1, "enabled": False,
              "match": {"intent": "sales"}, "destination_id": "sales"}]
    d = re.evaluate(PROFILE, rules, DESTS, {"intent": "sales"})
    assert d.destination_id == "reg"              # falls through to default


def test_rule_destination_disabled_uses_fallback():
    rules = [{"id": "r", "priority": 1, "match": {"intent": "x"}, "destination_id": "disabled"}]
    d = re.evaluate(PROFILE, rules, DESTS, {"intent": "x"})
    assert d.decision == "callback" and d.reason.startswith("rule_matched_destination_unavailable")


def test_low_confidence_stays_ai_by_default():
    d = re.evaluate(PROFILE, [], DESTS, {"intent": "unclear", "confidence": 0.2})
    assert d.decision == "handled_ai" and d.reason == "low_confidence"


def test_low_confidence_callback_when_configured():
    prof = {**PROFILE, "low_confidence_action": "callback"}
    d = re.evaluate(prof, [], DESTS, {"confidence": 0.1})
    assert d.decision == "callback"


def test_no_match_uses_default_then_fallback():
    d = re.evaluate(PROFILE, [], DESTS, {"intent": "whatever", "confidence": 0.9})
    assert d.decision == "transfer" and d.destination_id == "reg"
    # remove default -> safe fallback, never a drop
    prof = {k: v for k, v in PROFILE.items() if k != "default_destination_id"}
    d2 = re.evaluate(prof, [], DESTS, {"intent": "whatever", "confidence": 0.9})
    assert d2.decision == "callback"


def test_engine_never_emits_a_number_only_ids():
    # every transfer decision references a destination_id that exists in DESTS
    for ctx in ({"urgency": "urgent"}, {"intent": "sales"}, {"confidence": 0.9}):
        rules = [{"id": "r", "priority": 1, "match": {"intent": "sales"}, "destination_id": "sales"}]
        d = re.evaluate(PROFILE, rules, DESTS, ctx)
        if d.decision == "transfer":
            assert d.destination_id in DESTS
