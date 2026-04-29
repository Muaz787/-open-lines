import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="Open Lines API")

FRONTEND_URL = os.getenv("FRONTEND_URL", "")
APP_ENV = os.getenv("APP_ENV", "development")

origins = ["http://localhost:3000"]
if FRONTEND_URL:
    origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import webhooks, onboarding, leads, admin

app.include_router(webhooks.router)
app.include_router(onboarding.router)
app.include_router(leads.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "environment": APP_ENV}


@app.on_event("startup")
async def startup_event():
    print("Open Lines API running on port 8000")
