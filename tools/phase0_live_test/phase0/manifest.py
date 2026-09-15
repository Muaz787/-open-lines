"""
Manifest handling.

Two artifacts:
  - OPERATIONAL manifest: real resource ids the harness created. Gitignored,
    chmod 0600, never printed in full, deleted after teardown verification.
  - REVIEW manifest: masked ids only, safe to share. Contains no full numbers,
    credentials, transcripts, recording URLs, or tokens.
"""
from __future__ import annotations

import json
import os
import stat

from . import constants as C
from .sanitize import mask_identifier, mask_number, sanitize_mapping

# Keys whose values are telephone numbers (masked in the review manifest).
_NUMBER_KEYS = ("number",)
# Keys that are safe to keep in the clear (not provider identifiers).
_CLEAR_KEYS = frozenset({"resource_prefix", "selected_mode", "run_id",
                         "number_address_requirements"})


def _evidence_dir(base: str) -> str:
    d = os.path.join(base, C.EVIDENCE_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, stat.S_IRWXU)  # 0700
    return d


def write_operational(base: str, data: dict) -> str:
    """Atomic write: a concurrent reader (e.g. the capture service) always sees the
    complete old file or the complete new file, never a partial one."""
    d = _evidence_dir(base)
    path = os.path.join(d, C.OPERATIONAL_MANIFEST)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    os.replace(tmp, path)                        # atomic rename
    return path


def read_operational(base: str) -> dict:
    path = os.path.join(base, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def redacted_view(data: dict) -> dict:
    """Safe-to-print view of the operational manifest (never the raw file)."""
    return sanitize_mapping(data)


def to_review(data: dict) -> dict:
    """Build the shareable review manifest. Provider identifiers (SIDs/UUIDs/ids)
    and phone numbers are MASKED so no complete value survives; secret-ish keys are
    dropped entirely. Complete identifiers live only in the restricted operational
    manifest."""
    review: dict = {}
    for k, v in (data or {}).items():
        lk = k.lower()
        if any(s in lk for s in ("secret", "token", "auth", "key", "password")):
            continue  # never include, even masked
        if k in _CLEAR_KEYS:
            review[k] = v
        elif k == "number" or lk.endswith("_number") or "phone_number" in lk:
            review[k] = mask_number(str(v))
        elif lk.endswith(("_sid", "_id")) or lk in ("number_sid", "suborg_id") or "assistant" in lk:
            review[k] = mask_identifier(str(v))   # SIDs/UUIDs/provider ids
        else:
            review[k] = v
    return review


def write_review(base: str, data: dict) -> str:
    d = _evidence_dir(base)
    path = os.path.join(d, C.REVIEW_MANIFEST)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_review(data), fh, indent=2, ensure_ascii=False)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)  # 0640
    return path


def delete_operational(base: str) -> bool:
    """Delete the operational manifest after successful teardown verification."""
    path = os.path.join(base, C.EVIDENCE_DIR_NAME, C.OPERATIONAL_MANIFEST)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
