"""
Mistral OCR — extract text from scanned PDFs and image uploads.

Used as a fallback when a PDF has no text layer (scanned), and directly for
image uploads. Gracefully disabled when MISTRAL_API_KEY is unset (callers then
behave exactly as before OCR existed). Cost ~ $0.004/page; the page budget is
bounded by the caller (per-plan cap in kb_limits).
"""
from __future__ import annotations

import os
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_MISTRAL_URL = "https://api.mistral.ai/v1/ocr"
_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def ocr_available() -> bool:
    return bool(os.getenv("MISTRAL_API_KEY"))


def _mime(name: str) -> str:
    n = name.lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    return "application/pdf"


async def ocr_document(content: bytes, filename: str, max_pages: int) -> str:
    """Return OCR'd text (concatenated per-page markdown), or '' if OCR is
    unavailable or fails. For PDFs, only the first `max_pages` pages are processed."""
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        logger.info("OCR skipped for %s — MISTRAL_API_KEY unset", filename)
        return ""

    b64 = base64.b64encode(content).decode()
    name = (filename or "").lower()
    if name.endswith(_IMAGE_EXTS):
        body = {"model": _MODEL,
                "document": {"type": "image_url", "image_url": f"data:{_mime(name)};base64,{b64}"}}
    else:
        body = {"model": _MODEL,
                "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"},
                "pages": list(range(max(1, int(max_pages))))}  # 0-indexed page budget → bounds cost

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            res = await client.post(
                _MISTRAL_URL, json=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            if not res.is_success:
                logger.warning("Mistral OCR %s for %s: %s", res.status_code, filename, res.text[:300])
                return ""
            data = res.json()
    except Exception as e:
        logger.warning("Mistral OCR call failed for %s: %s", filename, e)
        return ""

    pages = data.get("pages") or []
    return "\n\n".join(
        (p.get("markdown") or "").strip() for p in pages if (p.get("markdown") or "").strip()
    )
