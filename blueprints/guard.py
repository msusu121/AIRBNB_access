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
    # Manual or client-detected ID takes priority and requires NO image
    detected_id = (request.form.get("detected_id") or "").strip()

    upload_dir = os.path.join(current_app.root_path, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    image_path = None
    ocr_text = ""
    national_id = None

    if detected_id:
        # Manual/Client OCR path (no image required)
        national_id = detected_id
        ocr_text = "[client_or_manual]"
        current_app.logger.info("[SCAN] client/manual national_id=%s", national_id)
    else:
        # Server OCR path requires an image
        file = request.files.get("image")
        if not file or not file.filename:
            return jsonify({"ok": False, "error": "No image received and no ID entered"}), 400

        fname = datetime.utcnow().strftime("%Y%m%d%H%M%S_") + secure_filename(file.filename)
        image_path = os.path.join(upload_dir, fname)
        file.save(image_path)

        # OCR on server
        ocr_text, extracted = extract_id_text(image_path)
        national_id = (extracted or "").strip()
        current_app.logger.info("[OCR] extracted_national_id=%s image=%s", national_id, image_path)

        if not national_id:
            # Log attempt even if OCR failed
            log = AccessLog(
                guard_id=current_user.id,
                checkpoint_id=checkpoint_id,
                national_id_number=None,
                decision="deny",
                image_path=image_path.replace(current_app.root_path, ""),
                ocr_text=ocr_text
            )
            db.session.add(log); db.session.commit()
            return jsonify({
                "ok": True,
                "decision": "deny",
                "reason": "ocr_no_id_detected",
                "message": "No ID number detected. Please rescan.",
                "debug": {"extracted_national_id": extracted}
            })

    # ---------- Access decision ----------
    # Keep your original “point-in-time” logic because you said OCR path works for you.
    # (If you later want whole-day inclusive logic, I can switch it, but leaving as-is.)
    tz = pytz.timezone('Africa/Nairobi')
    now = datetime.now(tz).replace(tzinfo=None)  # make naive to match typical MySQL DATETIME

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
                Booking.status != "cancelled"
            )
            .order_by(Booking.check_out.desc())
            .first()
        )
        if booking:
            decision = "allow"

    # ---------- Log every attempt ----------
    log = AccessLog(
        guard_id=current_user.id,
        checkpoint_id=checkpoint_id,
        guest_id=(guest.id if guest else None),
        booking_id=(booking.id if booking else None),
        national_id_number=national_id,
        decision=decision,
        image_path=(image_path.replace(current_app.root_path, "") if image_path else None),
        ocr_text=ocr_text
    )
    db.session.add(log); db.session.commit()

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
            "vehicle_plate": booking.vehicle_plate
        }
        return jsonify({"ok": True, "decision": "allow", "info": info, "debug": {"extracted_national_id": national_id}})

    # No active booking for this ID
    return jsonify({
        "ok": True,
        "decision": "deny",
        "reason": "no_active_booking",
        "message": "No active booking for this ID at the current time.",
        "debug": {"extracted_national_id": national_id}
    })
