"""Run: python check.py   Tests your keys one by one. Never prints secrets."""
import os, requests
from dotenv import load_dotenv
load_dotenv()

print("LLM_ORDER      :", os.getenv("LLM_ORDER", "(not set -> default ollama,gemini)"))
print("GEMINI_MODEL   :", os.getenv("GEMINI_MODEL", "(not set -> default)"))
print("GEMINI_API_KEY :", "found" if os.getenv("GEMINI_API_KEY") else "MISSING")
print("PAYPAL keys    :", "found" if os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_SECRET") else "MISSING")
print()

key = os.getenv("GEMINI_API_KEY")
if key:
    models = [os.getenv("GEMINI_MODEL")] if os.getenv("GEMINI_MODEL") else []
    models += [m for m in ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite"] if m not in models]
    for m in models:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                              params={"key": key}, json={"contents": [{"parts": [{"text": "say hi"}]}]}, timeout=30)
            print(f"Gemini {m}: HTTP {r.status_code}", "WORKS" if r.status_code == 200 else r.text[:120].replace(key, "***"))
            if r.status_code == 200:
                print(f"  -> put GEMINI_MODEL={m} in .env")
                break
        except Exception as e:
            print(f"Gemini {m}: error", str(e).replace(key, "***")[:120])
else:
    print("Gemini: skipped (no key)")

print()
try:
    r = requests.post("https://api-m.sandbox.paypal.com/v1/oauth2/token",
                      auth=(os.getenv("PAYPAL_CLIENT_ID", ""), os.getenv("PAYPAL_SECRET", "")),
                      data={"grant_type": "client_credentials"}, timeout=20)
    print("PayPal sandbox login: HTTP", r.status_code, "WORKS" if r.status_code == 200 else "FAILED (check Sandbox keys)")
except Exception as e:
    print("PayPal: error", str(e)[:120])
