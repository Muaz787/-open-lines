"""
Mandatory production-resource guard.

--apply MUST fail closed if the denylist is missing, empty, unreadable, or
malformed, or if no pepper is configured. Denied identifiers are stored ONLY as
keyed hashes (HMAC-SHA256 with a pepper that lives in the environment, never in
the file), so the file carries no raw production numbers, ids, hosts, or secrets.

Seed it with `phase0.cli seed-denylist` from an operator-local file of production
identifiers (gitignored). Raw denied values are never printed — errors show only a
short hash prefix.
"""
from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlparse

from .safety import normalize_id


class DenylistError(Exception):
    """Raised to FAIL CLOSED — apply must abort."""


def _pepper() -> bytes:
    p = os.environ.get("PHASE0_DENYLIST_PEPPER", "")
    if not p:
        raise DenylistError("PHASE0_DENYLIST_PEPPER not set — refusing to apply (fail closed)")
    return p.encode("utf-8")


def keyed_hash(value: str) -> str:
    return hmac.new(_pepper(), normalize_id(value).encode("utf-8"), sha256).hexdigest()


def host_of(url_or_host: str) -> str:
    s = (url_or_host or "").strip()
    if "://" in s:
        return (urlparse(s).hostname or "").lower()
    return s.split("/")[0].lower()


@dataclass
class Denylist:
    id_hashes: frozenset[str]
    host_hashes: frozenset[str]

    def is_denied(self, value: str) -> bool:
        return keyed_hash(value) in self.id_hashes

    def is_host_denied(self, url_or_host: str) -> bool:
        h = host_of(url_or_host)
        return bool(h) and hmac.new(_pepper(), h.encode(), sha256).hexdigest() in self.host_hashes

    def assert_target_allowed(self, target: str) -> None:
        if self.is_denied(target):
            raise DenylistError(f"target matches a PRODUCTION deny-list entry ({keyed_hash(target)[:8]}…) — refused")

    def assert_host_allowed(self, url_or_host: str) -> None:
        if self.is_host_denied(url_or_host):
            raise DenylistError("webhook/tunnel host matches a PRODUCTION host — refused")


def default_path(base: str) -> str:
    from . import constants as C
    return os.path.join(base, C.EVIDENCE_DIR_NAME, "production_denylist.hashes")


def load_or_fail(path: str) -> Denylist:
    """Load + validate. Any problem raises DenylistError (fail closed). Also
    forces pepper presence so apply cannot proceed without it."""
    _pepper()  # raises if unset
    if not os.path.exists(path):
        raise DenylistError(f"mandatory denylist missing at {path} — run seed-denylist first (fail closed)")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise DenylistError(f"denylist unreadable/malformed: {type(e).__name__} (fail closed)")
    if not isinstance(data, dict) or data.get("algo") != "hmac-sha256":
        raise DenylistError("denylist malformed: bad structure/algo (fail closed)")
    ids = data.get("hashes")
    hosts = data.get("host_hashes")
    if not isinstance(ids, list) or not isinstance(hosts, list):
        raise DenylistError("denylist malformed: hashes/host_hashes not lists (fail closed)")
    if not ids and not hosts:
        raise DenylistError("denylist empty — refusing to apply (fail closed)")
    if not all(isinstance(h, str) and len(h) == 64 for h in ids + hosts):
        raise DenylistError("denylist malformed: hash entries invalid (fail closed)")
    return Denylist(frozenset(ids), frozenset(hosts))


def seed(path: str, *, ids: list[str], hosts: list[str]) -> dict:
    """Write a denylist of KEYED HASHES only. Raw values are never persisted or
    returned. Returns a sanitized summary (counts only)."""
    payload = {
        "version": 1,
        "algo": "hmac-sha256",
        "hashes": sorted({keyed_hash(v) for v in ids if v.strip()}),
        "host_hashes": sorted({hmac.new(_pepper(), host_of(h).encode(), sha256).hexdigest()
                               for h in hosts if h.strip()}),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.chmod(path, 0o600)
    return {"id_count": len(payload["hashes"]), "host_count": len(payload["host_hashes"])}
