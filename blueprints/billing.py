import base64
import datetime as dt
import os
import requests

from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models import db, User  # noqa: F401

bp = Blueprint("billing", __name__, url_prefix="/billing")

# ---------- Config helpers ----------
def _mpesa_base_url() -> str:
    env = (os.getenv("MPESA_ENV") or "sandbox").strip().lower()
    return "https://api.safaricom.co.ke" if env == "live" else "https://sandbox.safaricom.co.ke"

def _get_access_token() -> str:
    """Daraja OAuth token via Consumer Key/Secret."""
    consumer_key = os.getenv("MPESA_CONSUMER_KEY")
    consumer_secret = os.getenv("MPESA_CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        raise RuntimeError("Missing MPESA_CONSUMER_KEY / MPESA_CONSUMER_SECRET")
    url = f"{_mpesa_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    resp = requests.get(url, auth=(consumer_key, consumer_secret), timeout=30)
    resp.raise_for_status()
    return resp.json().get("access_token")

def _lnmo_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")

def _timestamp_ke() -> str:
    """YYYYMMDDHHMMSS in Africa/Nairobi (common for examples; works in sandbox & live)."""
    try:
        tz = ZoneInfo("Africa/Nairobi")
    except Exception:
        tz = None
    now = dt.datetime.now(tz) if tz else dt.datetime.utcnow()
    return now.strftime("%Y%m%d%H%M%S")

def _normalize_msisdn(msisdn: str) -> str:
    s = (msisdn or "").strip().replace(" ", "").replace("+", "")
    return s

# ---------- STK push ----------
def _stk_push(phone: str, amount: int, account_ref: str, trans_desc: str) -> dict:
    """Perform STK Push. Returns Daraja JSON or raises with readable error."""
    shortcode = (os.getenv("MPESA_SHORTCODE") or "174379").strip()  # sandbox LNMO default
    passkey = (os.getenv("MPESA_PASSKEY") or
               # Public sandbox LNMO passkey for 174379 (from Daraja docs)
               "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b37e92f6e314b2c4f7f0d9")
    callback_url = os.getenv("MPESA_CALLBACK_URL")
    if not passkey or not callback_url:
        raise RuntimeError("Missing MPESA_PASSKEY / MPESA_CALLBACK_URL")

    phone = _normalize_msisdn(phone)
    if not (phone.startswith("2547") and len(phone) == 12 and phone.isdigit()):
        raise RuntimeError("Phone must be 2547XXXXXXXX")

    timestamp = _timestamp_ke()
    password = _lnmo_password(shortcode, passkey, timestamp)
    token = _get_access_token()

    url = f"{_mpesa_base_url()}/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "BusinessShortCode": int(shortcode),
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,             # customer MSISDN
        "PartyB": int(shortcode),    # your paybill/till
        "PhoneNumber": phone,        # MSISDN to receive the STK prompt
        "CallBackURL": callback_url, # must be public HTTPS in sandbox
        "AccountReference": (account_ref or "AIRBNB-GATE")[:12],
        "TransactionDesc": (trans_desc or "Subscription")[:20],
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=45)

    # Try to parse JSON content either way (even for 4xx)
    text = resp.text
    try:
        data = resp.json()
    except Exception:
        data = {"_raw": text}

    # If HTTP not OK, surface exact Daraja body for debugging
    if resp.status_code != 200:
        raise RuntimeError(f"Daraja HTTP {resp.status_code}: {data}")

    return data

# ---------- Views ----------
@bp.get("/pricing")
@login_required
def pricing():
    return render_template(
        "billing_pricing.html",
        current_plan=(current_user.plan or "").lower(),
        basic_price=int(current_app.config.get("BASIC_PRICE_KES", 1)),
        premium_price=int(current_app.config.get("PREMIUM_PRICE_KES", 2)),
    )

@bp.post("/checkout")
@login_required
def checkout():
    plan = (request.form.get("plan") or "basic").strip().lower()
    phone = _normalize_msisdn(request.form.get("phone") or "")

    if not (phone.startswith("2547") and len(phone) == 12 and phone.isdigit()):
        flash("Enter phone as 2547XXXXXXXX (use 254708374149 for sandbox tests).", "error")
        return redirect(url_for("billing.pricing"))

    amount = int(
        current_app.config.get("PREMIUM_PRICE_KES", 1)
        if plan == "premium" else
        current_app.config.get("BASIC_PRICE_KES", 1)
    )

    try:
        resp = _stk_push(
            phone=phone,
            amount=amount,
            account_ref=f"{plan}-plan",
            trans_desc=f"{plan} subscription"
        )
    except Exception as e:
        current_app.logger.exception("STK push failed")
        flash(f"M-Pesa request failed: {e}", "error")
        return redirect(url_for("billing.pricing"))

    # Daraja success to initiate STK push is ResponseCode == "0"
    rc = str(resp.get("ResponseCode", ""))
    print("RC CODE", rc)
    if rc != "0":
        msg = resp.get("errorMessage") or resp.get("ResponseDescription") or str(resp)
        flash(f"STK not initiated: {msg}", "error")
        return redirect(url_for("billing.pricing"))

   
    try:
        if hasattr(current_user, "plan"):
            current_user.plan = plan
            db.session.commit()
    except Exception:
        db.session.rollback()

    return render_template(
        "billing_success.html",
        plan=plan,
        checkout_id=resp.get("CheckoutRequestID", ""),
        message=resp.get("CustomerMessage", "STK Push initiated.")
    )
