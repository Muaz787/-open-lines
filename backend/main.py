import os
import logging
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="Open Lines API")

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
APP_ENV = os.getenv("APP_ENV", "development")

origins = [
    "http://localhost:3000",
    "https://openlines.ai",
    "https://www.openlines.ai",
    "https://open-lines.vercel.app",
]
if FRONTEND_URL and FRONTEND_URL not in origins:
    origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import webhooks, onboarding, leads, admin, knowledge, calendar, tools

app.include_router(webhooks.router)
app.include_router(onboarding.router)
app.include_router(leads.router)
app.include_router(admin.router)
app.include_router(knowledge.router)
app.include_router(calendar.router)
app.include_router(tools.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "environment": APP_ENV}


@app.get("/debug/env")
async def debug_env():
    """Temporary: confirm Google OAuth env vars are present (values hidden)."""
    return {
        "GOOGLE_CLIENT_ID":     bool(os.getenv("GOOGLE_CLIENT_ID")),
        "GOOGLE_CLIENT_SECRET": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        "GOOGLE_REDIRECT_URI":  bool(os.getenv("GOOGLE_REDIRECT_URI")),
        "GOOGLE_REDIRECT_URI_value": os.getenv("GOOGLE_REDIRECT_URI", "NOT SET"),
    }


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
                    "provider": "openai", "model": "gpt-4o", "temperature": 0.7,
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
