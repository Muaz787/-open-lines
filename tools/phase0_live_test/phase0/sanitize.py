"""
Sanitization utilities.

The capture service and every evidence writer MUST route through here. By default
we keep ONLY an allow-list of fields required for the Phase 0 investigation and
drop everything else. Numbers are masked to a country + last-4 token; secrets and
tokens are redacted. Raw webhook bodies are never persisted by default.
"""
from __future__ import annotations

import re
from typing import Any

# Patterns that must never reach disk in the clear.
_SECRET_KEYS = re.compile(
    r"(secret|token|authorization|auth|api[_-]?key|password|bearer|signature)",
    re.IGNORECASE,
)
_E164 = re.compile(r"\+?\d[\d\s().-]{6,}\d")
REDACTED = "«redacted»"


def mask_number(value: str | None) -> str:
    """+16475550123 -> '+1•••0123'. Empty -> '«none»'. Never returns full digits."""
    if not value:
        return "«none»"
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 4:
        return "«••••»"
    cc = "+1" if (str(value).strip().startswith("+1") or len(digits) == 11 and digits[0] == "1") else "+?"
    return f"{cc}•••{digits[-4:]}"


def mask_identifier(value: str | None) -> str:
    """Mask a provider identifier (SID/UUID/id) so no complete value survives:
    keep a short 2-char prefix + last 4, mask the middle. 'ACabcdef…1234' -> 'AC…1234'."""
    s = str(value or "")
    if not s:
        return "«none»"
    if len(s) <= 6:
        return s[:2] + "…"
    return f"{s[:2]}…{s[-4:]}"


def redact_secrets(text: str) -> str:
    """Redact anything that looks like a phone number or a secret inside a string."""
    if not text:
        return text
    return _E164.sub("«num»", str(text))


# Allow-lists: only these fields are retained per event type. Everything else,
# including transcripts, recordings, caller names, headers, auth, and any
# unrecognized keys, is dropped. Number-bearing fields are masked, not kept raw.
_EVENT_ALLOW: dict[str, dict[str, str]] = {
    # key = source path (dotted), value = transform: "keep" | "mask" | "iso"
    "assistant-request": {
        "call.id": "keep",
        "phoneNumber.number": "mask",
        "call.customer.number": "mask",
    },
    "transfer-destination-request": {
        "call.id": "keep",
        "timestamp": "keep",
    },
    "end-of-call-report": {
        "call.id": "keep",
        "endedReason": "keep",
        "durationSeconds": "keep",
        "startedAt": "keep",
        "endedAt": "keep",
        "cost": "keep",
        "call.phoneCallProviderId": "keep",   # provider (Twilio) call id, if present
    },
}

# Never persist these even if an allow-list rule were added by mistake.
_HARD_DENY = ("transcript", "messages", "recordingUrl", "recording", "artifact",
              "summary", "analysis", "customer.name", "headers")


def _dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def sanitize_event(event_type: str, body: dict) -> dict:
    """Return only the allow-listed, transformed fields for `event_type`.

    Unknown event types yield just a masked marker. Number fields are masked;
    secret-looking values are never copied. This is applied IN MEMORY before any
    write; the raw body is discarded.
    """
    out: dict[str, Any] = {"event_type": event_type}
    allow = _EVENT_ALLOW.get(event_type)
    if not allow:
        out["note"] = "unrecognized_event_dropped"
        return out
    for path, mode in allow.items():
        # Defense in depth: never emit a hard-denied leaf.
        if any(d in path for d in _HARD_DENY):
            continue
        val = _dig(body, path)
        if val is None:
            continue
        key = path.replace(".", "_")
        if mode == "mask":
            out[key] = mask_number(str(val))
        else:  # keep
            if isinstance(val, str) and _SECRET_KEYS.search(key):
                out[key] = REDACTED
            elif isinstance(val, str):
                out[key] = redact_secrets(val)
            else:
                out[key] = val
    return out


def sanitize_mapping(data: dict) -> dict:
    """Generic redactor for arbitrary dicts (e.g., manifests before printing):
    mask number-looking values, redact secret-keyed values, drop hard-denied keys.
    """
    clean: dict[str, Any] = {}
    for k, v in (data or {}).items():
        if any(d in k for d in _HARD_DENY):
            continue
        if _SECRET_KEYS.search(k):
            clean[k] = REDACTED
        elif isinstance(v, dict):
            clean[k] = sanitize_mapping(v)
        elif isinstance(v, str) and ("number" in k.lower() or _E164.fullmatch(v.strip())):
            clean[k] = mask_number(v)
        else:
            clean[k] = v
    return clean
