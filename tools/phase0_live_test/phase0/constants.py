"""
Phase 0 live-test harness — constants.

Grounded in current provider documentation (cited in README.md). Nothing here
places a call or mutates a provider; these are the fixed, reviewable values the
harness uses when an operator later runs it WITH --apply.

No secrets and no complete telephone numbers appear in this file.
"""
from __future__ import annotations

# --- Identity / naming -------------------------------------------------------
# Every resource the harness creates carries this prefix so it is unmistakably a
# throwaway Phase 0 resource and never a production one.
RESOURCE_PREFIX = "OL-PHASE0-DEV"

# --- Vapi transfer modes ------------------------------------------------------
# Tool "type" discriminator for a transfer tool. Verified against the Vapi OpenAPI
# spec (api.vapi.ai/api-json -> schema TransferCallTool / CreateTransferCallToolDTO)
# on 2026-08-02: the discriminator is camelCase "transferCall".
TRANSFER_TOOL_TYPE = "transferCall"

# transferPlan.mode enum (exact values from the current API reference).
MODE_BLIND = "blind-transfer"
MODE_BLIND_SIP_SUMMARY = "blind-transfer-add-summary-to-sip-header"
MODE_WARM_SAY_MESSAGE = "warm-transfer-say-message"
MODE_WARM_SAY_SUMMARY = "warm-transfer-say-summary"                 # M1: standard warm + summary
MODE_WARM_WAIT_MESSAGE = "warm-transfer-wait-for-operator-to-speak-first-and-then-say-message"
MODE_WARM_WAIT_SUMMARY = "warm-transfer-wait-for-operator-to-speak-first-and-then-say-summary"
MODE_WARM_TWIML = "warm-transfer-twiml"
MODE_WARM_EXPERIMENTAL = "warm-transfer-experimental"              # M2: assistant-based warm transfer

ALL_MODES = frozenset({
    MODE_BLIND, MODE_BLIND_SIP_SUMMARY, MODE_WARM_SAY_MESSAGE, MODE_WARM_SAY_SUMMARY,
    MODE_WARM_WAIT_MESSAGE, MODE_WARM_WAIT_SUMMARY, MODE_WARM_TWIML, MODE_WARM_EXPERIMENTAL,
})

# The two modes under test in Phase 0. M1 and M2 are DISTINCT mechanisms:
#   M1 (warm-transfer-say-summary):  Vapi speaks a generated summary to the
#                                    operator. No transferAssistant.
#   M2 (warm-transfer-experimental): an assistant-based warm transfer with a
#                                    dedicated transferAssistant that exposes the
#                                    built-in transferSuccessful / transferCancel
#                                    tools (caller recovery path).
MODE_M1 = MODE_WARM_SAY_SUMMARY
MODE_M2 = MODE_WARM_EXPERIMENTAL

# sipVerb controls how the leg is placed. "dial" bridges via Twilio <Dial> and so
# creates an observable child Call SID on OUR subaccount (needed for the
# identifier/billing investigation). "refer" hands off to the carrier and hides
# the leg + its billing. Default to "dial" for maximum observability.
SIP_VERB_DIAL = "dial"
SIP_VERB_REFER = "refer"
DEFAULT_SIP_VERB = SIP_VERB_DIAL

# --- Local safety limits (harness-enforced; see README for provider-side) -----
MAX_CALLS = 20
MAX_CALL_SECONDS = 300  # 5 minutes; set as assistant.maxDurationSeconds (provider-enforced per call)
# Operational (NOT a provider-guaranteed hard cap). See README §budget.
BUDGET_THRESHOLD_USD = 25.0

# --- Number policy -----------------------------------------------------------
# Domestic NANP only for Phase 0. Reject emergency, premium, and short codes.
ALLOWED_COUNTRY_PREFIXES = ("+1",)             # NANP (CA/US)
EMERGENCY_NUMBERS = frozenset({"911", "112", "999", "000", "988", "211", "311", "411", "611"})
# NANP premium / special area codes to reject outright.
PREMIUM_AREA_CODES = frozenset({"900", "976"})

# --- Caller phrases (deterministic transfer triggers, one per test) ----------
# These are the exact words the operator SAYS to make the test assistant call the
# transfer-call tool. Fixed so runs are reproducible.
CALLER_PHRASES = {
    "L3_dynamic":  "Please connect me to a team member.",
    "M1_summary":  "I need to speak to a person now.",
    "M2_assist":   "Can you put me through to someone on the team?",
    "L5_busy":     "Please transfer me to the on-call line.",
    "L6_noanswer": "Please transfer me to the regular line.",
    "L7_voicemail":"Please transfer me to the team.",
}

# --- Rate card (published; used only for derived cost math, not billing) ------
# See README for sources. Values are USD/min and are DERIVED, not metered.
RATE_TWILIO_INBOUND_PER_MIN = 0.0085
RATE_TWILIO_OUTBOUND_PER_MIN = 0.013
RATE_VAPI_STACK_PER_MIN = 0.12  # our blended Vapi+STT+LLM+TTS COGS (repo/memory)

# --- Capture service ---------------------------------------------------------
WEBHOOK_PATH_PREFIX = "/hook"        # actual path is /hook/<run_id>
HEALTH_PATH = "/healthz"
MAX_BODY_BYTES = 256 * 1024          # reject webhook bodies larger than this
REQUIRED_CONTENT_TYPE = "application/json"
VAPI_SECRET_HEADER = "X-Vapi-Secret"  # header Vapi sends when server.secret is set

# --- Evidence storage --------------------------------------------------------
EVIDENCE_DIR_NAME = "phase0-evidence"
OPERATIONAL_MANIFEST = "manifest.operational.json"   # gitignored, chmod 0600, deleted after teardown
REVIEW_MANIFEST = "manifest.review.json"             # masked, safe to share
CALLCOUNT_FILE = "callcount"                          # local call budget counter
READINESS_RECEIPT = "readiness_receipt.json"         # written by preflight-live (no secrets)
RECEIPT_MAX_AGE_SEC = 1800                            # a receipt is valid for 30 minutes
