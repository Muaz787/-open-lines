.PHONY: backend frontend dev tunnel db test

# ── Individual services ──────────────────────────────────────────────────────

backend:
	cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# ── Concurrent dev (requires 'pip install honcho' or brew install overmind) ──

dev:
	@which overmind > /dev/null 2>&1 && overmind start -f Procfile || \
	which honcho    > /dev/null 2>&1 && honcho start                || \
	(echo "Running sequentially — install overmind or honcho for true concurrency" && \
	 $(MAKE) backend & $(MAKE) frontend & wait)

# ── Ngrok tunnel for Vapi webhooks ───────────────────────────────────────────

tunnel:
	@which ngrok > /dev/null 2>&1 || (echo "ngrok not found — install via: brew install ngrok/ngrok/ngrok" && exit 1)
	ngrok http 8000

# ── Schema helper ─────────────────────────────────────────────────────────────

db:
	@echo ""
	@echo "  ┌─────────────────────────────────────────────────────────┐"
	@echo "  │  Open Lines — Supabase Schema Setup                     │"
	@echo "  └─────────────────────────────────────────────────────────┘"
	@echo ""
	@echo "  1. Open https://supabase.com/dashboard and select your project"
	@echo "  2. Go to  SQL Editor  (left sidebar)"
	@echo "  3. Paste the contents of  backend/db/schema.sql  and click Run"
	@echo ""
	@echo "  Schema file: backend/db/schema.sql"
	@echo ""
	@cat backend/db/schema.sql
	@echo ""

# ── Tests ────────────────────────────────────────────────────────────────────

test:
	cd backend && source venv/bin/activate && python -m pytest tests/ -v
