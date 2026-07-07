import os
import logging
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s",
)

# Redact obvious secrets from log lines as a safety net against accidental
# token/credential logging anywhere in the app.
import re as _re

_REDACT_PATTERNS = [
    (_re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", _re.I), r"\1[REDACTED]"),
    (_re.compile(r"\b(sk|rk|pk|whsec|xoxb|xoxp|sk_live|sk_test|rk_live|EAA)[_A-Za-z0-9]{12,}", _re.I), "[REDACTED]"),
    (_re.compile(r"((?:authorization|api[_-]?key|secret|token|password)\"?\s*[:=]\s*\"?)[^\s\"',}]+", _re.I), r"\1[REDACTED]"),
]


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            for pat, repl in _REDACT_PATTERNS:
                msg = pat.sub(repl, msg)
            record.msg = msg
            record.args = ()
        except Exception:
            pass
        return True


for _h in logging.getLogger().handlers:
    _h.addFilter(_RedactFilter())

logger = logging.getLogger(__name__)

app = FastAPI(title="Open Lines API")

from services.ratelimit import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
APP_ENV = os.getenv("APP_ENV", "development")

origins = [
    "https://openlines.ai",
    "https://www.openlines.ai",
    "https://open-lines.vercel.app",
    "https://pay.openlines.ai",
]
# Local dev origin only outside production.
if APP_ENV != "production":
    origins.append("http://localhost:3000")
if FRONTEND_URL and FRONTEND_URL not in origins:
    origins.append(FRONTEND_URL)

class _CatchAllMiddleware(BaseHTTPMiddleware):
    """Catch unhandled Python exceptions and return JSON.
    Must be added BEFORE CORSMiddleware so that add_middleware's LIFO ordering
    places it INSIDE CORSMiddleware — ensuring error responses still get CORS headers.
    """
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.error(
                "Unhandled exception on %s %s: %s",
                request.method, request.url.path, exc, exc_info=True,
            )
            # Don't leak exception type/message (which can contain identifiers or
            # internal detail) to clients in production.
            detail = (
                f"Internal server error: {type(exc).__name__}: {exc}"
                if APP_ENV != "production"
                else "Internal server error"
            )
            return JSONResponse(status_code=500, content={"detail": detail})


app.add_middleware(_CatchAllMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import webhooks, onboarding, leads, admin, knowledge, calendar, tools, billing, calls, hubspot, slack, stripe_connect, square_connect, payments, pay, zapier, staff, email_prefs

app.include_router(webhooks.router)
app.include_router(onboarding.router)
app.include_router(leads.router)
app.include_router(admin.router)
app.include_router(knowledge.router)
app.include_router(calendar.router)
app.include_router(tools.router)
app.include_router(staff.router)
app.include_router(billing.router)
app.include_router(calls.router)
app.include_router(hubspot.router)
app.include_router(slack.router)
app.include_router(stripe_connect.router)
app.include_router(square_connect.router)
app.include_router(payments.router)
app.include_router(pay.router)
app.include_router(email_prefs.router)

# Zapier integration is paused — only mount its routes when explicitly enabled.
from services import zapier as _zapier_service
if _zapier_service.ENABLED:
    app.include_router(zapier.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "environment": APP_ENV}


async def _sync_ngrok_url() -> None:
    """Detect the current ngrok tunnel URL and re-patch any connected Vapi assistants."""
    try:
        async with httpx.AsyncClient() as http:
            res = await http.get("http://localhost:4040/api/tunnels", timeout=3.0)
            res.raise_for_status()
            tunnels = res.json().get("tunnels", [])
    except Exception:
        return  # ngrok not running — nothing to do

    # Pick the https tunnel
    https_url = next(
        (t["public_url"] for t in tunnels if t.get("public_url", "").startswith("https")),
        None,
    )
    if not https_url:
        return

    old_url = os.environ.get("APP_BACKEND_URL", "")
    if https_url == old_url:
        logger.info("ngrok URL unchanged: %s", https_url)
        return

    logger.info("ngrok URL changed: %s → %s — re-patching Vapi assistants", old_url, https_url)
    os.environ["APP_BACKEND_URL"] = https_url

    # Update the module-level variable so build_calendar_tools picks up the new URL immediately
    import services.vapi as vapi_svc
    vapi_svc.APP_BACKEND_URL = https_url

    # Re-patch every tenant whose calendar is connected
    from db import supabase as db
    from routers.calendar import _CALENDAR_NOTE
    try:
        tenants = await db.get_tenants_with_calendar()
    except Exception as e:
        logger.error("Failed to fetch calendar tenants during ngrok sync: %s", e)
        return

    for tenant in tenants:
        assistant_id = tenant.get("vapi_assistant_id")
        if not assistant_id:
            continue
        try:
            tools = vapi_svc.build_calendar_tools(tenant["id"])
            current = await vapi_svc.get_assistant(assistant_id)
            messages = (current.get("model") or {}).get("messages") or []
            if messages and messages[0].get("role") == "system":
                existing = messages[0]["content"]
                if "CALENDAR BOOKING TOOLS AVAILABLE" in existing:
                    existing = existing[:existing.index("\n\nCALENDAR BOOKING TOOLS AVAILABLE")]
                messages[0]["content"] = existing + _CALENDAR_NOTE
            await vapi_svc.update_assistant(assistant_id, {
                "model": {
                    "provider": "openai", "model": "gpt-4.1-mini", "temperature": 0.7,
                    "tools": tools, "messages": messages,
                },
            })
            logger.info("Re-patched assistant %s with new ngrok URL", assistant_id)
        except Exception as e:
            logger.error("Failed to re-patch assistant %s: %s", assistant_id, e)


@app.on_event("startup")
async def startup_event():
    print("Open Lines API running on port 8000")
    await _sync_ngrok_url()
    from services.webhook_processor import start_background_processor
    start_background_processor()
