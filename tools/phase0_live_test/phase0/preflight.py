"""
Apply-time preflight. Validates ALL required configuration BEFORE the first
provider mutation, so provisioning never creates a resource and then discovers a
missing credential. Pure and unit-testable: pass an env mapping in.

`validate(...)` returns a list of human-readable problems (empty == ready). The CLI
aborts --apply if the list is non-empty.
"""
from __future__ import annotations

import os

from . import constants as C

_PLACEHOLDER_MARKERS = ("example", "tunnel.example", "__", "your_", "changeme", "placeholder")


def _placeholderish(v: str) -> bool:
    lv = (v or "").lower()
    return (not v) or any(m in lv for m in _PLACEHOLDER_MARKERS)


def repo_root_of(path: str) -> str | None:
    """Nearest ancestor containing a .git directory, or None."""
    cur = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def manifest_inside_repo(base: str) -> bool:
    evidence = os.path.abspath(os.path.join(base, C.EVIDENCE_DIR_NAME))
    root = repo_root_of(base) or repo_root_of(os.path.dirname(__file__))
    if not root:
        return False
    root = os.path.abspath(root)
    return evidence == root or evidence.startswith(root + os.sep)


def validate(env: dict, base: str, *, manifest_exists: bool) -> list[str]:
    problems: list[str] = []

    url = env.get("PHASE0_SERVER_URL", "")
    if _placeholderish(url) or not url.lower().startswith("https://"):
        problems.append("PHASE0_SERVER_URL must be an explicit non-placeholder HTTPS capture URL")

    if not env.get("VAPI_SERVER_SECRET"):
        problems.append("VAPI_SERVER_SECRET (webhook auth) must be set and non-empty")

    if not env.get("TWILIO_ACCOUNT_SID") or not env.get("TWILIO_AUTH_TOKEN"):
        problems.append("Twilio credentials (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN) required")

    if not env.get("VAPI_API_KEY"):
        problems.append("Vapi credential (VAPI_API_KEY) required")

    # Phase 0 requires the area-code SEARCH flow (no explicit-number path). This
    # matches provision.execute(), which always searches then purchases.
    area = env.get("PHASE0_AREA_CODE", "")
    if not (area.isdigit() and len(area) == 3):
        problems.append("PHASE0_AREA_CODE must be a 3-digit area code (area-code search flow)")

    if not [a for a in env.get("PHASE0_DEST_ALLOWLIST", "").split(",") if a.strip()]:
        problems.append("PHASE0_DEST_ALLOWLIST must contain at least one authorized destination")

    if env.get("PHASE0_MODE") not in (C.MODE_M1, C.MODE_M2):
        problems.append(f"PHASE0_MODE must be {C.MODE_M1} or {C.MODE_M2}")

    run_id = env.get("PHASE0_RUN_ID", "")
    if not run_id:
        problems.append("PHASE0_RUN_ID (unique run id) must be set")
    else:
        from .safety import run_id_ok
        ok, reason = run_id_ok(run_id)
        if not ok:
            problems.append(f"PHASE0_RUN_ID is not a valid path-safe id ({reason}); "
                            "use a UUID or [A-Za-z0-9_-]{8,64}")

    if env.get("PHASE0_SPEND_CONTROLS_ACK", "").lower() not in ("yes", "true", "1"):
        problems.append("PHASE0_SPEND_CONTROLS_ACK must confirm provider-side spend controls are configured")

    if not env.get("PHASE0_DENYLIST_PEPPER"):
        problems.append("PHASE0_DENYLIST_PEPPER must be set (mandatory production denylist)")

    if manifest_inside_repo(base):
        problems.append("operational manifest path is inside the repository — choose a --base outside the repo")

    # No --resume in Phase 0: an existing operational manifest ALWAYS fails closed.
    # Recovery is via stop/teardown + deliberate archival/deletion of the manifest.
    if manifest_exists:
        problems.append("an operational manifest already exists — provisioning is refused. "
                        "Run stop/teardown, verify cleanup, then archive/delete the manifest "
                        "before starting a new run.")

    return problems
