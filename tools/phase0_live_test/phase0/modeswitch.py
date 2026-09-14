"""
M1/M2 selection + read-back verification (pure logic; the CLI wraps it with the
provider patch/read calls under --apply).

Procedure:
  1. Patch the temp phone number's assistantId to the selected mode's assistant.
  2. Read the phone number + assistant back.
  3. Verify assistantId, transfer mode, and serverMessages match what we requested.
  4. Refuse to mark the mode "ready" if requested != stored.
  5. Record the selected mode in the operational + review manifests.

M2 uses `warm-transfer-experimental` with an INLINE transferAssistant — there is no
separate transfer-assistant resource to bind or verify.
"""
from __future__ import annotations

from . import constants as C

REQUIRED_SERVER_MESSAGES = ("transfer-destination-request", "end-of-call-report")

_EXPECTED_MODE = {
    C.MODE_M1: C.MODE_WARM_SAY_SUMMARY,
    C.MODE_M2: C.MODE_WARM_EXPERIMENTAL,
}


def expected_mode(selected: str) -> str:
    if selected not in _EXPECTED_MODE:
        raise ValueError(f"selected mode must be M1 ({C.MODE_M1}) or M2 ({C.MODE_M2}), got {selected}")
    return _EXPECTED_MODE[selected]


def _tool_mode(assistant_readback: dict) -> str | None:
    tools = ((assistant_readback or {}).get("model") or {}).get("tools") or []
    for t in tools:
        if t.get("type") == C.TRANSFER_TOOL_TYPE:
            return (t.get("transferPlan") or {}).get("mode")
    return None


def verify_ready(selected: str, requested_assistant_id: str,
                 phone_readback: dict, assistant_readback: dict) -> tuple[bool, list[str]]:
    """Return (ready, reasons). Ready only if EVERY check matches the request."""
    reasons: list[str] = []
    want_mode = expected_mode(selected)

    bound = (phone_readback or {}).get("assistantId")
    if bound != requested_assistant_id:
        reasons.append(f"bound assistantId {bound!r} != requested {requested_assistant_id!r}")

    sm = (assistant_readback or {}).get("serverMessages") or []
    for req in REQUIRED_SERVER_MESSAGES:
        if req not in sm:
            reasons.append(f"serverMessages missing {req}")

    got_mode = _tool_mode(assistant_readback)
    if got_mode != want_mode:
        reasons.append(f"transfer mode {got_mode!r} != expected {want_mode!r}")

    return (not reasons), reasons
