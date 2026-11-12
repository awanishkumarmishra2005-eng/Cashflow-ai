# Devpost submission text (copy into the form)

## Project name
CashFlow AI

## Tagline
An AI agent that bills your clients, chases late payments, and never moves money without your approval.

## Inspiration
Freelancers and small shops lose time and money chasing late invoices. Asking a client "have you paid yet?" is awkward, and most tools only send a link. We wanted an assistant that does the follow-up work for you.

## What it does
- Type or speak "Bill Rahul $50 for 2 logos, due Friday" (English or Hindi). The agent creates a PayPal checkout order and a payment link.
- Clients open a clean pay page and pay with PayPal. The dashboard updates to PAID automatically.
- For late invoices, the agent drafts reminders with a tone matched to how late the payment is.
- The agent can propose a discount, but only the owner can approve it. Every agent action is logged.

## How we built it
Python + Flask backend. PayPal REST: OAuth with token caching, Orders v2 (create and capture), return URL handling, and webhooks with signature verification and idempotency. AI: an agent loop that picks from six tools (create invoice, list invoices, list overdue, draft reminder, propose discount, summary), using Gemini with an optional local Ollama provider and automatic fallback. SQLite storage. Frontend: plain HTML/CSS/JS with 3D tilt cards and payment confetti. Deployed on Render.

## Challenges
Model availability changes (we hit retired Gemini models and 503s), so we added retries and model fallback. We also kept all money-changing actions behind owner approval.

## What's next
Payment plans, voice input, client reliability scores, and cash-flow forecasts.

## Built with
python, flask, paypal-rest-api, paypal-webhooks, gemini-api, ollama, sqlite, javascript, render

## Testing instructions (for judges)
Open the live URL, log in with any username and the password: <PUT YOUR DASH_PASSWORD HERE>. Click "Load demo data" or type "Bill Rahul $50 for logos due Friday". Open the client pay page and pay using a PayPal sandbox buyer account (credentials: <PUT SANDBOX PERSONAL EMAIL + PASSWORD HERE>).

## Demo video script (under 3 minutes)
0:00-0:20  Problem: late payments, awkward chasing.
0:20-1:30  Bill someone by chat, open the pay page, pay with the sandbox buyer, watch the dashboard turn green with confetti.
1:30-2:15  "Chase overdue": agent drafts reminders. Agent proposes a discount, you approve it.
2:15-3:00  Tech: PayPal Orders + webhooks (verified), AI agent tools, approval guardrail, impact for small sellers.
