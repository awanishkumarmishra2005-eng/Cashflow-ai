# CashFlow AI
AI agent that bills clients, tracks PayPal payments, chases late payers, and proposes discounts for owner approval.

## Run
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in PayPal sandbox keys + Gemini key
3. `python app.py` then open http://localhost:5000

## Test payment
Chat: "Bill Rahul $50 for 2 logos, due Friday" -> open Pay link -> log in with a PayPal sandbox buyer account -> approve -> dashboard shows PAID (refresh or webhook).

## Deploy (Render)
Build: `pip install -r requirements.txt` | Start: `gunicorn app:app`
Set the same env vars + BASE_URL. Add webhook in PayPal dashboard: `<BASE_URL>/webhook`, event CHECKOUT.ORDER.APPROVED, then copy its Webhook ID into `PAYPAL_WEBHOOK_ID`.
Note: Render free disk resets, so SQLite data can vanish. Use "Load demo data" before recording.

## Safety
Money-changing actions (discounts) only create proposals; the owner must approve. Everything is logged.

## Webhook security
Every webhook is verified with PayPal's verify-webhook-signature API (needs `PAYPAL_WEBHOOK_ID`), and each event id is processed only once, so replayed or forged events are ignored. Without the Webhook ID, webhooks are rejected unless `ALLOW_UNVERIFIED_WEBHOOKS=1` (local testing only).

## LLM providers
The agent tries Ollama first, then Gemini, and logs every fallback in the activity log.
Local: install Ollama, run `ollama pull qwen2.5:7b`. Models under 7B often break tool-calling JSON.
Cloud (Render): Ollama is not available there, so set `LLM_ORDER=gemini`.

## Deployment files
- `render.yaml`: one-click Render blueprint (New > Blueprint, pick the repo, fill the secret env vars)
- `Procfile`: for Heroku-style hosts
- `Dockerfile`: `docker build -t cashflow . && docker run -p 8000:8000 --env-file .env cashflow`
- `GET /health`: health check for uptime monitors
- `DASH_PASSWORD`: protects the owner dashboard with a login (username can be anything). Client pay pages, `/webhook`, and `/health` stay public.
- `DB_PATH`: SQLite location. Free hosts reset the disk, so use "Load demo data" before recording.
