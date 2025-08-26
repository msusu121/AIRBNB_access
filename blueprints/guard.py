import os
from datetime import datetime, time as dt_time
import pytz

from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import db, Booking, Guest, Room, Property, AccessLog, Checkpoint, ROLE_GUARD
from ocr import extract_id_text

bp = Blueprint("guard", __name__, url_prefix="/guard")

def _guard_only():
    return current_user.is_authenticated and current_user.role == ROLE_GUARD

@bp.get("/scan")
@login_required
def scan_page():
    if not _guard_only():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    checkpoints = Checkpoint.query.all()
    return render_template("guard_scan.html", checkpoints=checkpoints)

@bp.post("/scan")
@login_required
def scan_post():
    if not _guard_only():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    checkpoint_id = int(request.form.get("checkpoint_id") or 0)
    national_id = (request.form.get("detected_id") or "").strip()

    if not national_id:
        # no manual and client didn’t OCR anything
        return jsonify({
            "ok": True,
            "decision": "deny",
            "reason": "no_id",
            "message": "No ID number provided."
        })

    # --- decision window (same logic you had) ---
    tz = pytz.timezone('Africa/Nairobi')
    now = datetime.now(tz).replace(tzinfo=None)  # naive to match typical MySQL DATETIME

    guest = Guest.query.filter_by(national_id_number=national_id).first()
    booking = None
    decision = "deny"
    if guest:
        booking = (
            Booking.query
            .filter(
                Booking.guest_id == guest.id,
                Booking.check_in <= now,
                Booking.check_out >= now,
                Booking.status != "cancelled",
            )
            .order_by(Booking.check_out.desc())
            .first()
        )
        if booking:
            decision = "allow"

    # log every attempt
    log = AccessLog(
        guard_id=current_user.id,
        checkpoint_id=checkpoint_id,
        guest_id=(guest.id if guest else None),
        booking_id=(booking.id if booking else None),
        national_id_number=national_id,
        decision=decision,
        image_path=None,
        ocr_text="[client_or_manual]"
    )
    db.session.add(log)
    db.session.commit()

    if booking:
        room = Room.query.get(booking.room_id)
        prop = Property.query.get(room.property_id)
        info = {
            "guest_name": guest.full_name,
            "national_id": guest.national_id_number,
            "property": prop.name,
            "room": room.name,
            "check_in": booking.check_in.isoformat(),
            "check_out": booking.check_out.isoformat(),
            "booking_id": booking.id,
            "guests_count": booking.guests_count,
            "owns_vehicle": booking.owns_vehicle,
            "vehicle_plate": booking.vehicle_plate,
        }
        return jsonify({"ok": True, "decision": "allow", "info": info, "debug": {"extracted_national_id": national_id}})

    return jsonify({
        "ok": True,
        "decision": "deny",
        "reason": "no_active_booking",
        "message": "No active booking for this ID at the current time.",
        "debug": {"extracted_national_id": national_id}
    })


# --- New: Guard page to scan BOOKING QR ---
@bp.get("/booking-scan")
@login_required
def booking_scan_page():
    if not _guard_only():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    checkpoints = Checkpoint.query.all()
    return render_template("guard_booking_scan.html", checkpoints=checkpoints)

# --- New: Guard scans booking QR token ---
@bp.post("/booking-scan")
@login_required
def booking_scan_post():
    if not _guard_only():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    checkpoint_id = int(request.form.get("checkpoint_id") or 0)
    token = (request.form.get("qr_token") or "").strip()

    if not token:
        return jsonify({"ok": True, "decision": "deny", "reason": "no_qr", "message": "No QR token provided."})

    # Find booking by token
    booking = Booking.query.filter_by(qr_token=token).first()
    if not booking:
        db.session.add(AccessLog(
            guard_id=current_user.id,
            checkpoint_id=checkpoint_id,
            guest_id=None,
            booking_id=None,
            national_id_number=None,
            decision="deny",
            image_path=None,
            ocr_text="[booking_qr_not_found]"
        ))
        db.session.commit()
        return jsonify({"ok": True, "decision": "deny", "message": "QR not recognized."})

    # Check current window
    now = datetime.utcnow()
    decision = "deny"
    if booking.status != "cancelled" and (booking.check_in <= now <= booking.check_out):
        decision = "allow"

    guest = Guest.query.get(booking.guest_id)
    room  = Room.query.get(booking.room_id)
    prop  = Property.query.get(room.property_id)

    db.session.add(AccessLog(
        guard_id=current_user.id,
        checkpoint_id=checkpoint_id,
        guest_id=guest.id if guest else None,
        booking_id=booking.id,
        national_id_number=guest.national_id_number if guest else None,
        decision=decision,
        image_path=None,
        ocr_text="[booking_qr]"
    ))
    db.session.commit()

    info = {
        "guest_name": guest.full_name if guest else "",
        "national_id": guest.national_id_number if guest else "",
        "property": prop.name if prop else "",
        "room": room.name if room else "",
        "check_in": booking.check_in.isoformat(),
        "check_out": booking.check_out.isoformat(),
        "booking_id": booking.id,
        "guests_count": booking.guests_count,
        "owns_vehicle": booking.owns_vehicle,
        "vehicle_plate": booking.vehicle_plate,
    }
    return jsonify({"ok": True, "decision": decision, "info": info})