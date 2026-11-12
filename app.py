import os, re, json, time, sqlite3, requests
from datetime import date, datetime
from flask import Flask, request, jsonify, render_template, redirect, Response
from dotenv import load_dotenv

load_dotenv()
PP = "https://api-m.sandbox.paypal.com"
DB = os.getenv("DB_PATH", "cashflow.db")  # point at a persistent disk in production
app = Flask(__name__)
_tok = {"v": None, "exp": 0}


# ---------- database ----------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, client TEXT, description TEXT,
        amount REAL, currency TEXT DEFAULT 'USD', due_date TEXT, status TEXT DEFAULT 'PENDING',
        order_id TEXT, link TEXT);
    CREATE TABLE IF NOT EXISTS approvals(id INTEGER PRIMARY KEY, invoice_id INTEGER, kind TEXT,
        details TEXT, status TEXT DEFAULT 'OPEN');
    CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, ts TEXT);
    CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, ts TEXT, tool TEXT, detail TEXT);
    """)
    c.commit()
    c.close()


def log(tool, detail):
    detail = re.sub(r"key=[^&\s]+", "key=***", str(detail))  # never store API keys in logs
    c = db()
    c.execute("INSERT INTO log(ts,tool,detail) VALUES(?,?,?)",
              (datetime.now().strftime("%d %b %H:%M:%S"), tool, str(detail)[:300]))
    c.commit()
    c.close()


# ---------- PayPal ----------
def token():
    if _tok["v"] and time.time() < _tok["exp"]:
        return _tok["v"]
    r = requests.post(PP + "/v1/oauth2/token",
                      auth=(os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_SECRET")),
                      data={"grant_type": "client_credentials"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    _tok.update(v=j["access_token"], exp=time.time() + j["expires_in"] - 60)
    return _tok["v"]



def pp(method, path, **kw):
    for i in range(3):
        r = requests.request(
            method,
            PP + path,
            timeout=20,
            headers={
                "Authorization": "Bearer " + token(),
                "Content-Type": "application/json"
            },
            **kw
        )

        if r.status_code != 429:
            break

        time.sleep(2 * (i + 1))

    if not r.ok:
        try:
            error_details = r.json()
        except ValueError:
            error_details = r.text

        print("\n========== PAYPAL API ERROR ==========")
        print("HTTP Status:", r.status_code)
        print("Request ID:", r.headers.get("PayPal-Debug-Id", "Unavailable"))
        print("Error Details:", json.dumps(error_details, indent=2)
              if isinstance(error_details, dict) else error_details)
        print("======================================\n")

        raise RuntimeError(
            f"PayPal API error {r.status_code}: {error_details}"
        )

    return r.json()

def make_order(client, description, amount, currency):
    base = os.getenv("BASE_URL") or request.host_url.rstrip("/")
    o = pp("POST", "/v2/checkout/orders", json={
        "intent": "CAPTURE",
        "purchase_units": [{"description": f"{client}: {description}"[:120],
                            "amount": {"currency_code": currency, "value": f"{amount:.2f}"}}],
        "application_context": {"return_url": base + "/return", "cancel_url": base + "/"}})
    link = next((l["href"] for l in o["links"] if l["rel"] in ("payer-action", "approve")), None)
    return o["id"], link


def refresh(inv):
    """Check PayPal for payment; capture the order if the buyer approved it."""
    if inv["status"] == "PAID" or not inv["order_id"]:
        return
    try:
        o = pp("GET", f"/v2/checkout/orders/{inv['order_id']}")
        if o["status"] == "APPROVED":
            o = pp("POST", f"/v2/checkout/orders/{inv['order_id']}/capture", json={})
        if o["status"] == "COMPLETED":
            c = db()
            c.execute("UPDATE invoices SET status='PAID' WHERE id=?", (inv["id"],))
            c.commit()
            c.close()
            log("payment_received", f"Invoice #{inv['id']} paid by {inv['client']}")
    except Exception as e:
        log("refresh_error", e)


# ---------- agent tools ----------
def create_invoice(client, description, amount, due_date, currency="USD"):
    amount = round(float(amount), 2)
    order_id, link = make_order(client, description, amount, currency)
    c = db()
    cur = c.execute("INSERT INTO invoices(client,description,amount,currency,due_date,order_id,link)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (client, description, amount, currency, due_date, order_id, link))
    c.commit()
    iid = cur.lastrowid
    c.close()
    log("create_invoice", f"#{iid} {client} {amount} {currency} due {due_date}")
    return {"invoice_id": iid, "payment_link": link}


def rows(where="", args=()):
    c = db()
    r = [dict(x) for x in c.execute("SELECT * FROM invoices " + where, args)]
    c.close()
    today = date.today().isoformat()
    for x in r:
        if x["status"] == "PENDING" and x["due_date"] and x["due_date"] < today:
            x["status"] = "OVERDUE"
            x["days_late"] = (date.today() - date.fromisoformat(x["due_date"])).days
    return r


def list_invoices():
    return rows()


def list_overdue():
    return [x for x in rows() if x["status"] == "OVERDUE"]


def draft_reminder(invoice_id, tone="polite"):
    inv = rows("WHERE id=?", (invoice_id,))
    if not inv:
        return "Invoice not found"
    i = inv[0]
    text = llm(f"Write a short {tone} payment reminder message (3 sentences max) to {i['client']} for "
               f"{i['amount']} {i['currency']} ({i['description']}), due {i['due_date']}. "
               f"Include this payment link: {i['link']}. Plain text only.", as_json=False)
    log("draft_reminder", f"#{invoice_id} tone={tone}")
    return text


def propose_discount(invoice_id, percent):
    """Only creates a proposal. The owner must approve it."""
    c = db()
    c.execute("INSERT INTO approvals(invoice_id,kind,details) VALUES(?,?,?)",
              (invoice_id, "discount", json.dumps({"percent": float(percent)})))
    c.commit()
    c.close()
    log("propose_discount", f"#{invoice_id} {percent}% (waiting for owner approval)")
    return "Proposal created. Waiting for owner approval."


def get_summary():
    r = rows()
    s = lambda st: round(sum(x["amount"] for x in r if x["status"] == st), 2)
    return {"earned": s("PAID"), "pending": s("PENDING"), "overdue": s("OVERDUE"), "count": len(r)}


TOOLS = {"create_invoice": create_invoice, "list_invoices": list_invoices,
         "list_overdue": list_overdue, "draft_reminder": draft_reminder,
         "propose_discount": propose_discount, "get_summary": get_summary}

TOOL_DOC = """create_invoice(client, description, amount, due_date as YYYY-MM-DD, currency default USD)
list_invoices()
list_overdue()
draft_reminder(invoice_id, tone: polite|firm|final)  - pick tone from days_late
propose_discount(invoice_id, percent)  - only proposes, owner approves
get_summary()"""


# ---------- LLM (tries providers in order; default: Ollama, then Gemini) ----------
def _ollama(prompt, as_json):
    body = {"model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"), "prompt": prompt, "stream": False}
    if as_json:
        body["format"] = "json"
    r = requests.post(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/generate", json=body, timeout=20)
    r.raise_for_status()
    return r.json()["response"]


def _gemini(prompt, as_json):
    """Retries busy errors (429/5xx) and falls back to a second Gemini model."""
    models = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash")]
    models += [m for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",") if m and m not in models]
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if as_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    last = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for i in range(3):
            r = requests.post(url, params={"key": os.getenv("GEMINI_API_KEY")}, json=body, timeout=40)
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(2 * (i + 1))
        if r.ok:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        last = f"{model}: HTTP {r.status_code}"
        log("gemini_model_failed", last)
    raise RuntimeError(f"Gemini busy or unavailable ({last})")


PROVIDERS = {"ollama": _ollama, "gemini": _gemini}


def llm(prompt, as_json=True):
    last = None
    for name in os.getenv("LLM_ORDER", "ollama,gemini").split(","):
        name = name.strip()
        if name == "gemini" and not os.getenv("GEMINI_API_KEY"):
            continue
        try:
            out = PROVIDERS[name](prompt, as_json)
            if as_json:
                out = parse_json(out)  # validate; fall through to next provider if unusable
            return out
        except Exception as e:
            last = e
            log("llm_fallback", f"{name} failed: {e}")
    raise RuntimeError(f"All LLM providers failed: {last}")


def parse_json(text):
    """Small models sometimes wrap JSON in extra text; pull out the first {...} block."""
    try:
        return json.loads(text)
    except Exception:
        i, j = text.find("{"), text.rfind("}")
        return json.loads(text[i:j + 1])


def agent(msg):
    system = (f"You are CashFlow AI, an assistant that helps a freelancer get paid. Today is "
              f"{date.today().isoformat()}. Tools:\n{TOOL_DOC}\n"
              'Reply ONLY with JSON. To use a tool: {"tool": "name", "args": {...}}. '
              'To answer the user: {"reply": "text"}. Use one tool at a time. '
              "Never invent invoice ids; use list tools first if unsure. Hindi or English input is fine; "
              "reply in the user's language.")
    hist = [f"User: {msg}"]
    for _ in range(5):
        out = llm(system + "\n\n" + "\n".join(hist))
        if "reply" in out:
            return out["reply"]
        name, args = out.get("tool"), out.get("args", {})
        try:
            res = TOOLS[name](**args)
        except Exception as e:
            res = f"error: {e}"
        hist.append(f"Assistant called {name} {json.dumps(args)}\nTool result: {json.dumps(res)[:1500]}")
    return "Done."


# ---------- routes ----------
PUBLIC = ("/pay/", "/return", "/api/invoice/", "/webhook", "/health")


@app.before_request
def guard():
    """Optional password for the owner dashboard (set DASH_PASSWORD). Client pay pages stay public."""
    pw = os.getenv("DASH_PASSWORD")
    if not pw or request.path.startswith(PUBLIC):
        return None
    a = request.authorization
    if not a or a.password != pw:
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="CashFlow AI"'})


@app.route("/health")
def health():
    return jsonify(status="ok", paypal=bool(os.getenv("PAYPAL_CLIENT_ID")),
                   llm_order=os.getenv("LLM_ORDER", "ollama,gemini"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/pay/<int:iid>")
def pay_page(iid):
    return render_template("pay.html", iid=iid)


@app.route("/return")
def paypal_return():
    """PayPal sends the buyer here with ?token=<order id> after approval."""
    r = rows("WHERE order_id=?", (request.args.get("token"),))
    if not r:
        return redirect("/")
    refresh(r[0])
    return redirect(f"/pay/{r[0]['id']}")


@app.route("/api/invoice/<int:iid>")
def invoice_api(iid):
    r = rows("WHERE id=?", (iid,))
    if not r:
        return jsonify(error="not found"), 404
    refresh(r[0])
    return jsonify(rows("WHERE id=?", (iid,))[0])


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        return jsonify(reply=agent(request.json["message"]))
    except Exception as e:
        return jsonify(reply=f"Error: {e}"), 500


@app.route("/api/state")
def state():
    for inv in rows():
        refresh(inv)
    c = db()
    ap = [dict(x) for x in c.execute("SELECT * FROM approvals WHERE status='OPEN'")]
    lg = [dict(x) for x in c.execute("SELECT * FROM log ORDER BY id DESC LIMIT 15")]
    c.close()
    return jsonify(summary=get_summary(), invoices=rows(), approvals=ap, log=lg)


@app.route("/api/approve/<int:aid>/<decision>", methods=["POST"])
def approve(aid, decision):
    c = db()
    a = c.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    if not a:
        return jsonify(ok=False), 404
    if decision == "yes":
        inv = rows("WHERE id=?", (a["invoice_id"],))[0]
        pct = json.loads(a["details"])["percent"]
        new_amt = round(inv["amount"] * (1 - pct / 100), 2)
        oid, link = make_order(inv["client"], inv["description"] + f" ({pct:g}% off)", new_amt, inv["currency"])
        c.execute("UPDATE invoices SET amount=?, order_id=?, link=?, status='PENDING' WHERE id=?",
                  (new_amt, oid, link, inv["id"]))
        log("approved", f"Discount {pct:g}% on #{inv['id']}, new amount {new_amt}")
    c.execute("UPDATE approvals SET status=? WHERE id=?", ("DONE" if decision == "yes" else "REJECTED", aid))
    c.commit()
    c.close()
    return jsonify(ok=True)


def verify_webhook(event):
    """Ask PayPal to verify the signature of an incoming webhook."""
    wid = os.getenv("PAYPAL_WEBHOOK_ID")
    if not wid:
        return os.getenv("ALLOW_UNVERIFIED_WEBHOOKS") == "1"  # local testing only
    h = request.headers
    try:
        r = pp("POST", "/v1/notifications/verify-webhook-signature", json={
            "auth_algo": h.get("PAYPAL-AUTH-ALGO"),
            "cert_url": h.get("PAYPAL-CERT-URL"),
            "transmission_id": h.get("PAYPAL-TRANSMISSION-ID"),
            "transmission_sig": h.get("PAYPAL-TRANSMISSION-SIG"),
            "transmission_time": h.get("PAYPAL-TRANSMISSION-TIME"),
            "webhook_id": wid,
            "webhook_event": event})
        return r.get("verification_status") == "SUCCESS"
    except Exception as e:
        log("webhook_verify_error", e)
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    ev = request.get_json(silent=True) or {}
    if not verify_webhook(ev):
        log("webhook_rejected", "signature check failed")
        return "invalid signature", 400
    c = db()
    try:  # idempotency: process each event id only once
        c.execute("INSERT INTO events(event_id,ts) VALUES(?,?)", (ev.get("id"), datetime.now().isoformat()))
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        return "", 200
    c.close()
    log("webhook_verified", ev.get("event_type"))
    if ev.get("event_type") == "CHECKOUT.ORDER.APPROVED":
        for inv in rows("WHERE order_id=?", (ev["resource"]["id"],)):
            refresh(inv)
    return "", 200


@app.route("/api/seed", methods=["POST"])
def seed():
    """Demo data (no PayPal call) so your video never depends on the live API."""
    c = db()
    demo = [("Rahul", "Logo design x2", 50, "2026-10-20", "PENDING"),
            ("Priya Store", "Website banner", 120, "2026-11-20", "PENDING"),
            ("Amit", "Python tutoring", 80, "2026-10-01", "PAID")]
    for d in demo:
        c.execute("INSERT INTO invoices(client,description,amount,due_date,status) VALUES(?,?,?,?,?)", d)
    c.commit()
    c.close()
    return jsonify(ok=True)


init()
if __name__ == "__main__":
    app.run(debug=True, port=5000)
