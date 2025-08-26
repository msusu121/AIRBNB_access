import base64
import datetime as dt
import os
import requests

from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify, current_app
from urllib.parse import urlparse

bp = Blueprint("mpesa", __name__, url_prefix="/mpesa")

# ---------- Shared helpers ----------
def _mpesa_base_url() -> str:
    env = (os.getenv("MPESA_ENV") or "sandbox").strip().lower()
    return "https://api.safaricom.co.ke" if env == "live" else "https://sandbox.safaricom.co.ke"

def _get_access_token():
    key = os.getenv("MPESA_CONSUMER_KEY")
    sec = os.getenv("MPESA_CONSUMER_SECRET")
    if not key or not sec:
        raise RuntimeError("Missing MPESA_CONSUMER_KEY / MPESA_CONSUMER_SECRET")
    resp = requests.get(
        f"{_mpesa_base_url()}/oauth/v1/generate?grant_type=client_credentials",
        auth=(key, sec), timeout=15
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def _timestamp_ke():
    try:
        tz = ZoneInfo("Africa/Nairobi")
    except Exception:
        tz = None
    now = dt.datetime.now(tz) if tz else dt.datetime.utcnow()
    return now.strftime("%Y%m%d%H%M%S")

def _stk_password(shortcode, passkey, timestamp):
    raw = f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")

def _normalize_msisdn(msisdn: str) -> str:
    return (msisdn or "").strip().replace(" ", "").replace("+", "")

# ---------- Testable STK endpoint (optional) ----------
@bp.post("/stk-push")
def stk_push():
    """
    JSON body:
      { "phone": "254708374149", "amount": 10 }
    """
    data = request.get_json(force=True, silent=True) or {}
    phone  = _normalize_msisdn(str(data.get("phone", "")))
    amount = int(data.get("amount", 1) or 1)

    if not (phone.startswith("2547") and len(phone) == 12 and phone.isdigit()):
        return jsonify({"ok": False, "error": "Use MSISDN like 2547XXXXXXXX"}), 400

    shortcode = (os.getenv("MPESA_SHORTCODE") or "174379").strip()
    passkey   = (os.getenv("MPESA_PASSKEY") or
                 "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b37e92f6e314b2c4f7f0d9")
    cb_url    = os.getenv("MPESA_CALLBACK_URL")

    if not cb_url or not urlparse(cb_url).scheme.startswith("http"):
        return jsonify({"ok": False, "error": "Set MPESA_CALLBACK_URL (public https)"}), 400

    ts = _timestamp_ke()
    password = _stk_password(shortcode, passkey, ts)
    token = _get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "BusinessShortCode": int(shortcode),
        "Password": password,
        "Timestamp": ts,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": int(shortcode),
        "PhoneNumber": phone,
        "CallBackURL": cb_url,
        "AccountReference": "AIRBNB-GATE",
        "TransactionDesc": "SaaS subscription"
    }

    r = requests.post(f"{_mpesa_base_url()}/mpesa/stkpush/v1/processrequest",
                      json=payload, headers=headers, timeout=30)
    text = r.text
    try:
        data = r.json()
    except Exception:
        data = {"_raw": text}

    if r.status_code != 200:
        return jsonify({"ok": False, "status": r.status_code, "data": data}), 502

    return jsonify({"ok": True, "resp": data})

# ---------- Callback ----------
@bp.post("/callback")
def stk_callback():
    """
    Safaricom hits this URL with the payment result.
    Persist to DB, mark invoice/plan as paid, etc.
    """
    payload = request.get_json(force=True, silent=True) or {}
    current_app.logger.info("[MPESA CALLBACK] %s", payload)

    try:
        cb = payload["Body"]["stkCallback"]
        result_code = cb.get("ResultCode")
        result_desc = cb.get("ResultDesc", "")
        items = {it["Name"]: it.get("Value") for it in cb.get("CallbackMetadata", {}).get("Item", [])}

        # Example of what you'd do:
        # - find pending payment by CheckoutRequestID = cb["CheckoutRequestID"]
        # - if result_code == 0: mark as paid, upgrade plan for that user
        # - store MpesaReceiptNumber, Amount, PhoneNumber, TransactionDate, etc.
        current_app.logger.info("[MPESA RESULT] code=%s desc=%s items=%s", result_code, result_desc, items)
    except Exception as e:
        current_app.logger.exception("Bad callback payload: %s", e)

    # Daraja expects 200 OK
    return jsonify({"ok": True})
