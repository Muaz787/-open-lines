"""
Deterministic Phase 0 assistant + transfer configurations.

INBOUND DESIGN (explicit, per review): the temporary Vapi phone number is created
with the dev assistant BOUND directly (assistantId on the phone-number import), so
Vapi answers with a static assistant and NO assistant-request round-trip is used.
This deliberately keeps OpenLines' production assistant-resolution logic OUT of the
test — Phase 0 evaluates transfers, not routing. The assistant's own server config
still delivers `transfer-destination-request` and `end-of-call-report` to the
capture service. Verification FAILS if the phone number has no bound assistantId
(see cli.cmd_verify).

All values are concrete and validated against the current Vapi API reference
(docs.vapi.ai/api-reference/tools/create and /calls/assistant-based-warm-transfer).
There are no DOC? placeholders in these executable payloads. Fields whose live
effect is not yet verified against a real account are listed in README under
"Unverified provider assumptions".
"""
from __future__ import annotations

from . import constants as C

# Fixed Phase 0 identity — no production persona, no KB, no booking/payment tools.
_IDENTITY = (
    "You are OL-PHASE0-TESTBOT, a throwaway test receptionist used ONLY to validate "
    "call transfers. You have no knowledge base and cannot book, take payments, or "
    "look anything up. You must NEVER dial, read, or invent a phone number. To "
    "transfer, you may ONLY call the transfer-call tool with NO number — the server "
    "supplies the approved destination. Behaviour:\n"
    "- Greet: 'Phase zero test line. Say the test phrase to begin.'\n"
    "- When the caller asks to be transferred / to speak to a person, immediately "
    "call the transfer-call tool. Do not ask for details.\n"
    "- If a transfer fails and you are returned to the call, say 'The transfer did "
    "not connect; I'll note a callback,' then end the call.\n"
    "- Keep every reply to one short sentence."
)


def _model() -> dict:
    return {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "temperature": 0,
        "messages": [{"role": "system", "content": _IDENTITY}],
    }


def transfer_tool_dynamic(mode: str, sip_verb: str = C.DEFAULT_SIP_VERB) -> dict:
    """The native `transferCall` tool with EMPTY destinations, so Vapi emits
    `transfer-destination-request` and the capture service returns the approved
    number. The COMPLETE mode-specific transferPlan lives here (single source of
    truth); the dynamic webhook returns only a bare authorized destination so it
    can never alter the mode. Native transferCall takes destinations/transferPlan,
    NOT a custom `function` block."""
    assert mode in C.ALL_MODES, f"unknown mode {mode}"
    return {
        "type": C.TRANSFER_TOOL_TYPE,     # "transferCall" (OpenAPI-verified)
        "destinations": [],               # empty -> dynamic destination via server
        "transferPlan": _transfer_plan(mode, sip_verb),
    }


def transfer_tool_static(mode: str, dest_e164: str, sip_verb: str = C.DEFAULT_SIP_VERB) -> dict:
    """A transferCall tool with a fixed authorized destination (non-dynamic path)."""
    tool = transfer_tool_dynamic(mode, sip_verb)
    tool["destinations"] = [{
        "type": "number",
        "number": dest_e164,
        "numberE164CheckEnabled": True,
        "description": "Authorized Phase 0 test destination",
    }]
    return tool


def _transfer_plan(mode: str, sip_verb: str) -> dict:
    # timeout + dialTimeout are always present.
    plan: dict = {"mode": mode, "sipVerb": sip_verb, "timeout": 30, "dialTimeout": 30}
    if mode == C.MODE_M1:  # warm-transfer-say-summary
        plan["summaryPlan"] = {
            "enabled": True,
            "timeoutSeconds": 5,
            "messages": [{
                "role": "system",
                "content": "In one sentence, tell the operator this is a Phase 0 test transfer.",
            }],
        }
    elif mode == C.MODE_M2:  # warm-transfer-experimental (assistant-based)
        plan["transferAssistant"] = _transfer_assistant()
    return plan


def _transfer_assistant() -> dict:
    """The dedicated transfer assistant for assistant-based warm transfer (M2).
    Exposes Vapi's built-in transferSuccessful / transferCancel automatically."""
    return {
        "firstMessage": "Hi, this is a Phase 0 test transfer — can I hand the caller to you?",
        "firstMessageMode": "assistant-speaks-first",
        "maxDurationSeconds": 60,
        "silenceTimeoutSeconds": 20,
        "model": {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "temperature": 0,
            "messages": [{"role": "system", "content": (
                "You brief the operator on a Phase 0 test transfer. If the operator "
                "accepts, call transferSuccessful. If they do not answer, are busy, "
                "reject, or you reach voicemail, call transferCancel to return the "
                "caller to the original assistant."
            )}],
        },
        # Customer-facing messages during the transfer (exact type values).
        "messages": [
            {"type": "request-start", "content": "One moment while I connect you."},
            {"type": "request-failed", "content": "That didn't connect; let me take a message."},
        ],
    }


def dev_assistant_config(mode: str, server_url: str, server_secret: str) -> dict:
    """Full create-assistant payload for the dev (main) assistant under test."""
    server = {"url": server_url}
    if server_secret:
        server["secret"] = server_secret
    return {
        "name": f"{C.RESOURCE_PREFIX}-assistant-{mode}",
        "firstMessage": "Phase zero test line. Say the test phrase to begin.",
        "maxDurationSeconds": C.MAX_CALL_SECONDS,   # provider-enforced per-call cap
        "model": {**_model(), "tools": [transfer_tool_dynamic(mode)]},
        "server": server,
        # Required so the transfer + end-of-call events reach the capture service.
        "serverMessages": ["assistant-request", "transfer-destination-request", "end-of-call-report"],
    }


def import_number_body(e164: str, sub_sid: str, assistant_id: str,
                       server_url: str, server_secret: str) -> dict:
    """Create the Vapi phone number with the dev assistant BOUND (static binding),
    per the inbound design above."""
    body: dict = {
        "provider": "twilio",
        "number": e164,
        "twilioAccountSid": sub_sid,
        # twilioAuthToken is injected by the caller from env at apply time; never
        # stored in this module.
        "assistantId": assistant_id,
        "name": f"{C.RESOURCE_PREFIX}-number",
        "server": {"url": server_url},
    }
    if server_secret:
        body["server"]["secret"] = server_secret
    return body
