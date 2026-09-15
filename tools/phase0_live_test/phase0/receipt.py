"""
Readiness receipt written by the read-only live preflight (preflight-live).

The receipt records that provider credential + capture-health checks passed for a
specific run id at a specific time. It contains NO credentials and NO raw provider
payloads — only check names and booleans. `provision --apply` refuses unless a
valid receipt exists (present, all checks passed, matching run id, not stale).
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone

from . import constants as C

# The exact minimum set of checks that must all be boolean true. A standalone
# "ok": true is NEVER trusted — it must agree with these individual checks.
REQUIRED_CHECKS = (
    "capture_health", "run_id_match", "capture_mode_match",
    "twilio_read", "vapi_read", "spend_controls_ack",
)


def _path(base: str) -> str:
    return os.path.join(base, C.EVIDENCE_DIR_NAME, C.READINESS_RECEIPT)


def write(base: str, run_id: str, checks: dict) -> str:
    d = os.path.join(base, C.EVIDENCE_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    os.chmod(d, stat.S_IRWXU)
    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checks": {k: bool(v) for k, v in checks.items()},   # booleans only
        "ok": all(checks.values()),
    }
    p = _path(base)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)   # 0600 (owner-only; validated on read)
    return p


def load(base: str) -> dict | None:
    try:
        with open(_path(base), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return None


def validate(base: str, run_id: str, *, now: datetime | None = None,
             max_age_sec: int = C.RECEIPT_MAX_AGE_SEC) -> list[str]:
    """Return problems (empty == valid). Fail closed on missing / failed / missing
    required check / non-boolean value / unknown structure / ok-conflict / bad
    timestamp or run id / unsafe permissions. A standalone `ok:true` is not trusted."""
    path = _path(base)
    rec = load(base)
    if rec is None:
        return ["live-preflight receipt missing — run `preflight-live --apply` first"]
    problems: list[str] = []

    # Permissions must be owner-only (no group/other bits).
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & 0o077:
            problems.append("live-preflight receipt permissions are unsafe (must be owner-only)")
    except OSError:
        problems.append("live-preflight receipt is unreadable")

    if not isinstance(rec, dict) or not isinstance(rec.get("checks"), dict):
        return problems + ["live-preflight receipt has an unknown structure"]
    checks = rec["checks"]

    # Every value present must be a real boolean (not 1/"true"/etc).
    for k, v in checks.items():
        if not isinstance(v, bool):
            problems.append(f"receipt check '{k}' is not a boolean")

    # The exact required set must all be present and exactly True.
    for req in REQUIRED_CHECKS:
        if req not in checks:
            problems.append(f"receipt missing required check '{req}'")
        elif checks.get(req) is not True:
            problems.append(f"receipt check '{req}' is not true")

    # `ok` must agree with the individual checks (do not trust ok alone).
    computed_ok = bool(checks) and all(v is True for v in checks.values())
    if rec.get("ok") is not computed_ok:
        problems.append("receipt 'ok' conflicts with individual checks")

    if rec.get("run_id") != run_id:
        problems.append("live-preflight receipt is for a different PHASE0_RUN_ID")

    try:
        ts = datetime.fromisoformat(rec.get("created_at", ""))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - ts).total_seconds()
        if age > max_age_sec:
            problems.append(f"live-preflight receipt is stale (> {max_age_sec}s old) — re-run preflight-live")
        if age < -60:
            problems.append("live-preflight receipt timestamp is in the future — invalid")
    except (ValueError, TypeError):
        problems.append("live-preflight receipt has an invalid timestamp")

    return problems
