"""
Deterministic routing engine (pure — no I/O, no provider calls).

The AI classifies (intent / urgency / requested person / language / confidence);
THIS module decides the destination. The AI never sees or emits a phone number —
it only triggers a transfer, and this engine picks a tenant-approved destination
by id. That keeps arbitrary dialing impossible by construction and makes every
routing decision auditable and unit-testable offline (no live calls).

Inputs are plain dicts so this module has no dependency on the eventual schema:

  profile      {mode, default_destination_id, urgent_destination_id,
                default_fallback_action ('callback'|'message'|'voicemail'),
                low_confidence_action ('handle_ai'|'callback'),
                confidence_threshold (0..1)}
  rules        [{id, priority, enabled, match:{intent, urgency, keywords[],
                 requested_person, new_vs_returning, language},
                 destination_id, fallback_destination_id}]
  destinations {id: {type, enabled}}
  context      {intent, urgency, requested_person, is_returning, language,
                confidence, text}

Returns a decision dict:
  {decision: 'handled_ai'|'transfer'|'callback',
   destination_id, matched_rule_id, reason}
"""
from __future__ import annotations

from dataclasses import dataclass

# Intents that must NEVER be dialed. A caller in danger is told to contact
# emergency services (handled by the assistant); the engine hard-blocks any
# destination. Distinct from a business-service "urgent" call, which MAY route to
# the tenant's approved on-call/urgent destination.
PUBLIC_EMERGENCY_INTENTS = frozenset({"public_emergency", "emergency"})
URGENT_INTENTS = frozenset({"urgent_service", "urgent"})
_URGENT_LEVELS = frozenset({"urgent", "emergency_service", "high"})

DEFAULT_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class Decision:
    decision: str                 # handled_ai | transfer | callback
    destination_id: str | None = None
    matched_rule_id: str | None = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {"decision": self.decision, "destination_id": self.destination_id,
                "matched_rule_id": self.matched_rule_id, "reason": self.reason}


def _dest_ok(destinations: dict, dest_id: str | None) -> bool:
    d = (destinations or {}).get(dest_id or "")
    return bool(d) and bool(d.get("enabled", True))


def _fallback(profile: dict) -> Decision:
    action = (profile.get("default_fallback_action") or "callback").lower()
    if action in ("message", "voicemail", "callback"):
        return Decision("callback", reason=f"fallback:{action}")
    return Decision("callback", reason="fallback:callback")


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _rule_matches(match: dict, ctx: dict) -> bool:
    """A rule matches only if every condition it specifies is satisfied (AND).
    Empty/absent conditions are wildcards."""
    if not match:
        return True
    if match.get("intent") and _norm(match["intent"]) != _norm(ctx.get("intent")):
        return False
    if match.get("urgency") and _norm(match["urgency"]) != _norm(ctx.get("urgency")):
        return False
    if match.get("language") and _norm(match["language"]) != _norm(ctx.get("language")):
        return False
    if match.get("requested_person") and _norm(match["requested_person"]) != _norm(ctx.get("requested_person")):
        return False
    nvr = match.get("new_vs_returning")
    if nvr in ("new", "returning"):
        want_returning = (nvr == "returning")
        if bool(ctx.get("is_returning")) != want_returning:
            return False
    kws = [_norm(k) for k in (match.get("keywords") or []) if _norm(k)]
    if kws:
        text = _norm(ctx.get("text"))
        if not any(k in text for k in kws):
            return False
    return True


def evaluate(profile: dict, rules: list[dict], destinations: dict, context: dict) -> Decision:
    """Pick a destination deterministically. Precedence:
       1. public emergency  -> never dial (handled_ai)
       2. business urgent    -> urgent/on-call destination (if valid)
       3. first matching rule by ascending priority (ties: first listed)
       4. low confidence     -> low_confidence_action
       5. default destination
       6. safe fallback (callback/message)
    """
    profile = profile or {}
    ctx = context or {}
    intent = _norm(ctx.get("intent"))

    # 1) Public emergency — hard block, never dial.
    if intent in PUBLIC_EMERGENCY_INTENTS:
        return Decision("handled_ai", reason="public_emergency_no_dial")

    # 2) Business-service urgency -> approved urgent/on-call destination.
    urgent = _norm(ctx.get("urgency")) in _URGENT_LEVELS or intent in URGENT_INTENTS
    if urgent:
        uid = profile.get("urgent_destination_id")
        if _dest_ok(destinations, uid):
            return Decision("transfer", uid, reason="urgent_escalation")
        # urgent but no valid urgent destination -> safe fallback, still flagged
        fb = _fallback(profile)
        return Decision(fb.decision, fb.destination_id, reason="urgent_no_destination")

    # 3) Deterministic rule evaluation (ascending priority; stable for ties).
    ordered = sorted(
        [r for r in (rules or []) if r.get("enabled", True)],
        key=lambda r: (int(r.get("priority", 1_000_000)),),
    )
    for r in ordered:
        if _rule_matches(r.get("match") or {}, ctx):
            dest = r.get("destination_id")
            if _dest_ok(destinations, dest):
                return Decision("transfer", dest, matched_rule_id=r.get("id"), reason="rule_match")
            alt = r.get("fallback_destination_id")
            if _dest_ok(destinations, alt):
                return Decision("transfer", alt, matched_rule_id=r.get("id"), reason="rule_fallback_destination")
            fb = _fallback(profile)
            return Decision(fb.decision, fb.destination_id, matched_rule_id=r.get("id"),
                            reason="rule_matched_destination_unavailable")

    # 4) Low confidence -> configured low-confidence behavior (default: stay AI).
    threshold = float(profile.get("confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD))
    conf = ctx.get("confidence")
    if conf is not None and float(conf) < threshold:
        if _norm(profile.get("low_confidence_action")) == "callback":
            return Decision("callback", reason="low_confidence")
        return Decision("handled_ai", reason="low_confidence")

    # 5) Default destination.
    did = profile.get("default_destination_id")
    if _dest_ok(destinations, did):
        return Decision("transfer", did, reason="default_destination")

    # 6) Safe fallback — never a silent drop.
    fb = _fallback(profile)
    return Decision(fb.decision, fb.destination_id, reason="no_match_" + fb.reason)
