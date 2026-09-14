"""
Computed lifecycle readiness state. Pure: derived from the manifest, the receipt,
and the local preflight — nothing is stored beyond the flags the CLI already sets.

The runbook must NOT instruct calls until the state is `call_test_ready`.

States (highest applicable wins):
  teardown_verified > teardown_incomplete > stopped > call_test_ready >
  mode_verified > provisioned > provider_preflight_ready > local_preflight_ready >
  not_ready
"""
from __future__ import annotations

STATES = [
    "local_preflight_ready", "provider_preflight_ready", "provisioned",
    "mode_verified", "call_test_ready", "stopped",
    "teardown_incomplete", "teardown_verified",
]


def compute_state(*, manifest: dict | None, receipt_ok: bool,
                  local_ready: bool, mode_consistent: bool) -> str:
    m = manifest or {}
    provisioned = bool(m.get("vapi_phone_number_id"))
    mode_verified = bool(m.get("mode_verified")) and mode_consistent

    if m.get("teardown_verified"):
        return "teardown_verified"
    if m.get("teardown_attempted"):
        return "teardown_incomplete"
    if m.get("stopped"):
        return "stopped"
    if provisioned and mode_verified and receipt_ok:
        return "call_test_ready"
    if provisioned and mode_verified:
        return "mode_verified"
    if provisioned:
        return "provisioned"
    if receipt_ok:
        return "provider_preflight_ready"
    if local_ready:
        return "local_preflight_ready"
    return "not_ready"


def guidance(state: str) -> str:
    if state == "call_test_ready":
        return "READY: you may place test calls per the worksheet."
    if state in ("stopped", "teardown_incomplete", "teardown_verified"):
        return "Run is stopping/torn down — do NOT place calls."
    return "NOT call-ready — do NOT place test calls until state is call_test_ready."
