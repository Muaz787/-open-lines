"""
Secure storage helpers for routing destination phone numbers (plan §6.3).

A destination number is stored three ways, never in plaintext:
  * e164_encrypted — AES-256-GCM (services/security.encrypt), the recoverable value
  * e164_masked    — '+1•••1234', shown to owners by default
  * e164_hash      — HMAC-SHA256(pepper, normalized E.164), a KEYED equality hash
                     for duplicate detection + forwarding-loop prevention WITHOUT
                     decrypting (not a plain digest, so it isn't rainbow-tableable)

The pepper lives in ROUTING_HASH_PEPPER (env), never in the DB. This module has no
provider or DB dependencies; encryption is delegated to services.security.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

from services.telephony import normalize_phone


class DestinationSecurityError(Exception):
    pass


# Numbers we refuse as transfer destinations regardless of plan.
_EMERGENCY_NUMBERS = frozenset({"911", "112", "999", "000", "988", "211", "311", "411", "611"})
_PREMIUM_AREA_CODES = frozenset({"900", "976"})


def validate_destination_number(e164: str) -> tuple[bool, str]:
    """Safety floor for a transfer destination: reject emergency, premium, short
    codes, and anything that isn't a plausible E.164 number. Returns (ok, reason)."""
    raw = str(e164 or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits in _EMERGENCY_NUMBERS or raw in _EMERGENCY_NUMBERS:
        return False, "emergency_number"
    if len(digits) <= 5:
        return False, "short_code"
    n = normalize(e164)
    if not n.startswith("+") or len(re.sub(r"\D", "", n)) < 8:
        return False, "not_e164"
    # DOMESTIC-ONLY by default (product decision 2026-08-02): transfer destinations
    # must be NANP (+1). This closes the main toll-fraud / variable-rate cost risk.
    # International can be re-enabled later as an explicit per-destination opt-in.
    if not n.startswith("+1"):
        return False, "international_not_allowed"
    nanp = n[2:]
    if nanp[:3] in _PREMIUM_AREA_CODES:
        return False, "premium_number"
    if len(nanp) != 10:
        return False, "not_e164_nanp"
    return True, "ok"


def normalize(e164: str) -> str:
    """Best-effort E.164 normalization (reuses the telephony normalizer)."""
    return normalize_phone(e164)


def mask(e164: str) -> str:
    """'+16475551234' -> '+1•••1234'. Never returns the full number."""
    digits = "".join(ch for ch in str(e164 or "") if ch.isdigit())
    if len(digits) < 4:
        return "•••"
    cc = "+1" if (str(e164).strip().startswith("+1") or (len(digits) == 11 and digits[0] == "1")) else "+?"
    return f"{cc}•••{digits[-4:]}"


def _pepper() -> bytes:
    p = os.getenv("ROUTING_HASH_PEPPER", "")
    if not p:
        raise DestinationSecurityError(
            "ROUTING_HASH_PEPPER must be set to derive keyed destination hashes")
    return p.encode("utf-8")


def keyed_hash(e164: str) -> str:
    """Keyed HMAC-SHA256 of the normalized number. Same number -> same hash (for
    dedup/loop checks); different pepper -> different hash. Never reversible."""
    return hmac.new(_pepper(), normalize(e164).encode("utf-8"), hashlib.sha256).hexdigest()


def _country_of(e164: str) -> str | None:
    n = normalize(e164)
    return "NANP" if n.startswith("+1") else None


def secure_fields(e164: str) -> dict:
    """Build the DB column values for a phone destination. Delegates encryption to
    services.security.encrypt (AES-256-GCM). Raises if the number is empty."""
    n = normalize(e164)
    if not n:
        raise DestinationSecurityError("empty/invalid destination number")
    from services.security import encrypt
    return {
        "e164_encrypted": encrypt(n),
        "e164_masked": mask(n),
        "e164_hash": keyed_hash(n),
        "country": _country_of(n),
    }


def reveal(e164_encrypted: str) -> str:
    """Decrypt a stored destination (owner-authorized paths only)."""
    from services.security import decrypt
    return decrypt(e164_encrypted)


def is_same_number(e164: str, stored_hash: str) -> bool:
    """Loop/dedup check: does `e164` hash to `stored_hash`? (No decryption.)"""
    return bool(stored_hash) and hmac.compare_digest(keyed_hash(e164), stored_hash)
