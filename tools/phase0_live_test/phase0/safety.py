"""
Safety guards: destination/source allow-lists, number-class rejection, local call
budget, and the production-resource guard.

The production guard is ALLOW-LIST FIRST: a mutating operation may only target a
resource id that appears in the operational manifest the harness itself created.
Production ids therefore can never be targeted (they are never in the manifest).
A hashed deny-list adds defense in depth without storing any raw production value.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from . import constants as C


class SafetyError(Exception):
    """Raised when an operation would violate a Phase 0 safety rule."""


# A run id must be a UUID or an equivalently strong, path-safe token. The charset
# alone excludes slashes, backslashes, whitespace, and query/fragment characters;
# length + dot-traversal + control-char checks close the rest.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def run_id_ok(run_id: str) -> tuple[bool, str]:
    s = run_id or ""
    if not (8 <= len(s) <= 64):
        return False, "length_out_of_range"
    if ".." in s:
        return False, "dot_traversal"
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        return False, "control_char"
    if any(c in s for c in "/\\?#& \t\n\r%"):
        return False, "illegal_char"
    if not _RUN_ID_RE.match(s):
        return False, "format"
    return True, "ok"


def normalize(number: str) -> str:
    s = (number or "").strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if s.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits[0] == "1":
        return "+" + digits
    return "+" + digits


def number_class_ok(number: str) -> tuple[bool, str]:
    """Return (ok, reason). Rejects emergency, premium, short, and non-domestic."""
    raw = (number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits in C.EMERGENCY_NUMBERS or raw in C.EMERGENCY_NUMBERS:
        return False, "emergency_number"
    if len(digits) <= 5:
        return False, "short_code"
    e164 = normalize(number)
    if not any(e164.startswith(p) for p in C.ALLOWED_COUNTRY_PREFIXES):
        return False, "non_domestic"
    nanp = e164[2:] if e164.startswith("+1") else digits
    if nanp[:3] in C.PREMIUM_AREA_CODES:
        return False, "premium_area_code"
    if len(nanp) != 10:
        return False, "not_e164_nanp"
    return True, "ok"


def assert_destination_allowed(number: str, allowlist: list[str]) -> None:
    ok, reason = number_class_ok(number)
    if not ok:
        raise SafetyError(f"destination rejected: {reason}")
    allow = {normalize(a) for a in (allowlist or [])}
    if normalize(number) not in allow:
        raise SafetyError("destination not in authorized allow-list")


def assert_source_allowed(number: str, allowlist: list[str] | None) -> None:
    # Source allow-listing is best-effort: forwarded calls may not preserve
    # caller ID, so an empty allow-list means "unknown, accept" (documented).
    if not allowlist:
        return
    if normalize(number) not in {normalize(a) for a in allowlist}:
        raise SafetyError("source not in authorized allow-list")


# --- Production-resource guard ----------------------------------------------

def _sha(value: str) -> str:
    return hashlib.sha256(normalize_id(value).encode("utf-8")).hexdigest()


def normalize_id(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


@dataclass
class Guard:
    """Allow-list of resource ids this run is permitted to touch (from the
    operational manifest) plus an optional hashed production deny-list."""
    allowed_ids: frozenset[str]
    denied_hashes: frozenset[str] = frozenset()

    @classmethod
    def from_manifest(cls, manifest: dict, denylist_path: str | None = None) -> "Guard":
        ids = set()
        for v in (manifest or {}).values():
            if isinstance(v, str) and v:
                ids.add(normalize_id(v))
        denied = set()
        if denylist_path:
            try:
                with open(denylist_path, "r", encoding="utf-8") as fh:
                    denied = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
            except FileNotFoundError:
                denied = set()
        return cls(frozenset(ids), frozenset(denied))

    def assert_target_allowed(self, target: str) -> None:
        t = normalize_id(target)
        if _sha(target) in self.denied_hashes:
            raise SafetyError("target matches a production deny-list hash — refused")
        if t not in self.allowed_ids:
            raise SafetyError(
                "target is not a resource this run created (not in operational "
                "manifest) — refused to prevent touching production/unknown resources"
            )


# --- Local call budget -------------------------------------------------------

def check_call_budget(current_count: int) -> None:
    if current_count >= C.MAX_CALLS:
        raise SafetyError(f"local call budget reached ({C.MAX_CALLS} calls) — stop and review")


def check_duration(seconds: int) -> None:
    if seconds > C.MAX_CALL_SECONDS:
        raise SafetyError(f"call duration {seconds}s exceeds cap {C.MAX_CALL_SECONDS}s")
