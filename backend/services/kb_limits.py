"""
Per-plan knowledge-base upload limits (file size + page caps).

Resolved from the tenant's subscription. The free trial deliberately mirrors
Starter so prospects fully experience document upload — but its OCR page cap
stays small (OCR is a paid external call at ~$0.004/page).
"""
from __future__ import annotations

_ACTIVE_SUB_STATUSES = {"active", "trialing", "past_due", "canceling"}

# max_file_mb: reject files larger than this
# max_pages:   pages processed per doc (text layer); extra pages truncated + warned
# ocr_pages:   max pages sent to Mistral OCR for scanned docs (bounds OCR spend)
_LIMITS: dict[str, dict] = {
    "trial":    {"max_file_mb": 10, "max_pages": 50,   "ocr_pages": 10},
    "starter":  {"max_file_mb": 10, "max_pages": 50,   "ocr_pages": 50},
    "pro":      {"max_file_mb": 25, "max_pages": 300,  "ocr_pages": 300},
    "business": {"max_file_mb": 50, "max_pages": 1000, "ocr_pages": 1000},
}

MAX_FILES_PER_UPLOAD = 10


def kb_limits(tenant: dict) -> dict:
    """Return {tier, max_file_mb, max_bytes, max_pages, ocr_pages} for a tenant."""
    plan = (tenant.get("subscription_plan") or "").lower()
    status = (tenant.get("subscription_status") or "").lower()
    if status in _ACTIVE_SUB_STATUSES and plan in _LIMITS:
        tier = plan
    else:
        tier = "trial"  # no active paid plan → trial tier (upload gating handled elsewhere)
    base = _LIMITS[tier]
    return {"tier": tier, "max_bytes": base["max_file_mb"] * 1024 * 1024, **base}
