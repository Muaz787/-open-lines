import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from db import supabase as db
from services.short_links import is_valid_short_code, is_safe_payment_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pay"])

_404_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link not found — Open Lines</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:40px 32px;
      max-width:420px;width:100%;text-align:center}
.icon{width:64px;height:64px;border-radius:50%;background:rgba(239,68,68,.12);
      display:flex;align-items:center;justify-content:center;margin:0 auto 20px}
h1{font-size:20px;font-weight:700;margin-bottom:12px}
p{font-size:14px;color:#8b949e;line-height:1.6}
.powered{font-size:11px;color:#484f58;margin-top:28px}
</style>
</head>
<body>
<div class="card">
  <div class="icon">
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ef4444"
         stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
    </svg>
  </div>
  <h1>Payment link not found.</h1>
  <p>This link doesn&rsquo;t exist or may have already been used.<br>
     Please contact the business to request a new payment link.</p>
  <p class="powered">Powered by Open Lines</p>
</div>
</body>
</html>"""

_EXPIRED_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link expired — Open Lines</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
     display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:16px;padding:40px 32px;
      max-width:420px;width:100%;text-align:center}
.icon{width:64px;height:64px;border-radius:50%;background:rgba(251,191,36,.12);
      display:flex;align-items:center;justify-content:center;margin:0 auto 20px}
h1{font-size:20px;font-weight:700;margin-bottom:12px}
p{font-size:14px;color:#8b949e;line-height:1.6}
.powered{font-size:11px;color:#484f58;margin-top:28px}
</style>
</head>
<body>
<div class="card">
  <div class="icon">
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#f59e0b"
         stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
  </div>
  <h1>This payment link has expired.</h1>
  <p>Please contact the business to request a new link.</p>
  <p class="powered">Powered by Open Lines</p>
</div>
</body>
</html>"""


@router.get("/d/{short_code}", include_in_schema=False)
async def redirect_payment_link(short_code: str):
    if not is_valid_short_code(short_code):
        logger.warning("pay/redirect: invalid short_code format: %r", short_code)
        return HTMLResponse(_404_HTML, status_code=404)

    link = await db.get_payment_short_link_by_code(short_code)
    if not link:
        logger.info("pay/redirect: short_code not found: %s", short_code)
        return HTMLResponse(_404_HTML, status_code=404)

    expires_at = link.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=ZoneInfo("UTC"))
            if datetime.now(timezone.utc) > exp:
                logger.info("pay/redirect: expired: %s (tenant %s)", short_code, link.get("tenant_id"))
                return HTMLResponse(_EXPIRED_HTML, status_code=410)
        except Exception as e:
            logger.warning("pay/redirect: could not parse expires_at for %s: %s", short_code, e)

    payment_url = link.get("stripe_checkout_url", "")
    if not is_safe_payment_url(payment_url):
        logger.error("pay/redirect: unsafe URL blocked for short_code %s", short_code)
        return HTMLResponse(_404_HTML, status_code=404)

    try:
        await db.increment_short_link_click(link["id"])
    except Exception as e:
        logger.warning("pay/redirect: click tracking failed for %s: %s", short_code, e)

    logger.info(
        "pay/redirect: %s → payment (tenant %s, click #%s)",
        short_code, link.get("tenant_id"), (link.get("click_count") or 0) + 1,
    )
    return RedirectResponse(url=payment_url, status_code=302)
