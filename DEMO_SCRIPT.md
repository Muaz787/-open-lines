# Open Lines — Demo & Local Dev Guide

## Prerequisites

| Tool | Install |
|------|---------|
| Python 3.11+ | `brew install python@3.11` |
| Node 18+ | `brew install node` |
| ngrok | `brew install ngrok/ngrok/ngrok` |
| overmind *(optional, for `make dev`)* | `brew install overmind` |

---

## 1. Environment Setup

### Backend — `backend/.env`

```env
# Supabase
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>

# Twilio (master account)
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...

# Vapi
VAPI_API_KEY=...

# OpenAI
OPENAI_API_KEY=sk-...

# Firecrawl
FIRECRAWL_API_KEY=fc-...

# Pinecone
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=open-lines

# App
APP_ENV=development
APP_BACKEND_URL=https://<your-ngrok-subdomain>.ngrok-free.app
FRONTEND_URL=http://localhost:3000

# Make (for WhatsApp notifications)
MAKE_WEBHOOK_URL=https://hook.eu1.make.com/...
```

### Frontend — `frontend/.env.local`

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 2. Database Setup

Run the schema against your Supabase project once:

```bash
make db
# follow the printed instructions, or:
# 1. Open Supabase → SQL Editor
# 2. Paste contents of backend/db/schema.sql
# 3. Click Run
```

---

## 3. Install Dependencies

```bash
# Backend
cd backend && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

---

## 4. Run the Full Stack

```bash
# Terminal 1 — both services together (requires overmind or honcho)
make dev

# — OR — split terminals:
make backend    # Terminal 1: FastAPI on :8000
make frontend   # Terminal 2: Next.js on :3000
```

---

## 5. Expose the Backend via ngrok

Vapi needs a public URL to POST call events. Open a third terminal:

```bash
make tunnel
# → Forwarding  https://xxxx-xx-xx-xx-xx.ngrok-free.app → localhost:8000
```

Copy the `https://` URL. Update `APP_BACKEND_URL` in `backend/.env`:

```
APP_BACKEND_URL=https://xxxx-xx-xx-xx-xx.ngrok-free.app
```

Then restart the backend so it picks up the new value.

---

## 6. Provision Shahid's Business

```bash
curl -X POST http://localhost:8000/onboarding/provision \
  -H "Content-Type: application/json" \
  -d '{
    "business_name":   "Shahid Real Estate",
    "industry":        "realtor",
    "owner_name":      "Shahid",
    "whatsapp_number": "+1XXXXXXXXXX",
    "website_url":     "https://shahidrealestate.ca",
    "agent_name":      "Alex"
  }'
```

**Expected response (≈60 s):**

```json
{
  "tenant_id":     "uuid-...",
  "phone_number":  "+14165550100",
  "assistant_id":  "vapi-...",
  "status":        "live",
  "dashboard_url": "http://localhost:3000/dashboard/uuid-..."
}
```

---

## 7. Point Vapi's Server URL to Your Tunnel

After provisioning, the Vapi assistant is already created with
`serverUrl` pointing to `APP_BACKEND_URL/webhooks/vapi-call-ended`.

If you changed your ngrok URL, update the assistant via the API:

```bash
curl -X PATCH https://api.vapi.ai/assistant/<assistant_id> \
  -H "Authorization: Bearer $VAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"serverUrl": "https://xxxx-xx-xx-xx-xx.ngrok-free.app/webhooks/vapi-call-ended"}'
```

To verify the webhook is reachable:

```bash
curl https://xxxx-xx-xx-xx-xx.ngrok-free.app/health
# → {"status":"ok","version":"0.1.0","environment":"development"}
```

---

## 8. Share the Dashboard with Shahid

```
http://localhost:3000/dashboard/<tenant_id>
```

Replace `localhost:3000` with your production frontend URL when deploying.

The dashboard auto-refreshes every 30 seconds. After each call ends, Vapi
POSTs to `/webhooks/vapi-call-ended`, which:

1. Looks up the tenant by the called number
2. Runs GPT-4o to extract a structured lead summary
3. Saves the call + updates the lead in Supabase
4. Sends a WhatsApp notification via Make

---

## 9. Run Tests

```bash
make test
# or directly:
cd backend && source venv/bin/activate && python -m pytest tests/ -v
```

All tests mock external APIs — no real credentials needed.

---

## 10. Sync Knowledge Base Manually

If the website content changes, trigger a re-scrape:

```bash
curl -X POST http://localhost:8000/webhooks/sync-knowledge \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "<uuid>"}'
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SUPABASE_URL not set` | Check `backend/.env` is in the right place and `load_dotenv()` runs before any import |
| Vapi webhook not firing | Confirm ngrok tunnel is running and `APP_BACKEND_URL` matches the live URL |
| `No available numbers found` | Try adding more area codes to `find_available_number()` in `telephony.py` |
| GPT-4o analysis returns `{}` | Check `OPENAI_API_KEY` is valid; inspect logs for the raw response |
| Pinecone upsert fails | Confirm index name matches `PINECONE_INDEX_NAME` and dimensions = 1536 (text-embedding-3-small) |
