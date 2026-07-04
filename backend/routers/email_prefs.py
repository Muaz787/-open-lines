"""Email preferences — one-click unsubscribe for promotional (trial) email.

Honors CASL: the trial nudges carry a signed unsubscribe link and RFC 8058
List-Unsubscribe-Post header. Both the visible link (GET) and the one-click
POST land here, verify the HMAC token, and set marketing_unsubscribed_at so
services/trial.py stops sending. Operational email (call summaries, deposits,
receipts, account notices) is unaffected.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from db import supabase as db
from services.email import verify_unsubscribe_token, SUPPORT_EMAIL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])

_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — Open Lines</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F4F2EC;margin:0;padding:48px 16px;text-align:center;color:#001F3F">
<div style="max-width:440px;margin:0 auto;background:#fff;border:1px solid #E7E2D6;border-radius:12px;padding:32px">
<h1 style="font-size:20px;margin:0 0 10px">{title}</h1>
<p style="font-size:14px;color:#5A6A7A;line-height:1.6;margin:0">{msg}</p>
</div></body></html>"""


async def _unsubscribe(tenant_id: str, token: str) -> bool:
    if not verify_unsubscribe_token(tenant_id, token):
        return False
    try:
        await db.update_tenant(
            tenant_id,
            {"marketing_unsubscribed_at": datetime.now(timezone.utc).isoformat()},
        )
        logger.info("Marketing unsubscribe recorded for tenant %s", tenant_id)
        return True
    except Exception as e:
        logger.error("Unsubscribe update failed for tenant %s: %s", tenant_id, e)
        return False


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe_get(t: str = "", k: str = ""):
    if await _unsubscribe(t, k):
        return HTMLResponse(_PAGE.format(
            title="You're unsubscribed",
            msg=("You won't receive further trial or promotional emails from Open Lines. "
                 "Account, billing and call notifications are unaffected."),
        ))
    return HTMLResponse(
        _PAGE.format(
            title="Link invalid",
            msg=f"This unsubscribe link is invalid or has expired. Email {SUPPORT_EMAIL} and we'll help.",
        ),
        status_code=400,
    )


@router.post("/unsubscribe", response_class=PlainTextResponse)
async def unsubscribe_post(t: str = "", k: str = ""):
    """RFC 8058 one-click endpoint (List-Unsubscribe-Post)."""
    ok = await _unsubscribe(t, k)
    return PlainTextResponse("OK" if ok else "invalid", status_code=200 if ok else 400)
