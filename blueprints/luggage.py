
# blueprints/luggage.py
import os
import io
import secrets
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, current_app, send_file
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from models import (
    db, ROLE_ADMIN, ROLE_HOST, ROLE_GUARD,
    Booking, Luggage, LuggageScanLog, Checkpoint, Room, Guest, Property
)

# Optional QR lib (PNG generation)
try:
    import qrcode
    from qrcode.image.pil import PilImage
except Exception:
    qrcode = None

bp = Blueprint("luggage", __name__, url_prefix="/luggage")


# ---------------- Permissions ----------------

def _can_view():
    """Admin or Host can view lists."""
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

def _host_only():
    """Only Host can create/edit/delete luggage."""
    return current_user.is_authenticated and current_user.role == ROLE_HOST

def _guard_only():
    """Only Guard can use the guard scan UI/API."""
    return current_user.is_authenticated and current_user.role == ROLE_GUARD


# ---------------- Admin/Host: list & detail ----------------

@bp.get("/")
@login_required
def list_():
    """List recent luggage (Admin = read-only, Host = manages)."""
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    items = (
        db.session.query(Luggage, Booking, Room, Guest, Property)
        .join(Booking, Luggage.booking_id == Booking.id)
        .join(Room, Booking.room_id == Room.id)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Property, Room.property_id == Property.id)
        .order_by(Luggage.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template("admin_luggage_list.html", items=items)


@bp.get("/<int:lug_id>")
@login_required
def detail(lug_id: int):
    """View a luggage item (Admin read-only, Host can act)."""
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    data = (
        db.session.query(Luggage, Booking, Room, Guest, Property)
        .join(Booking, Luggage.booking_id == Booking.id)
        .join(Room, Booking.room_id == Room.id)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Property, Room.property_id == Property.id)
        .filter(Luggage.id == lug_id)
        .first_or_404()
    )

    # fetch recent scans for this luggage
    scans = (
        LuggageScanLog.query
        .filter(LuggageScanLog.luggage_id == lug_id)
        .order_by(LuggageScanLog.id.desc())
        .limit(50).all()
    )

    luggage, booking, room, guest, prop = data
    return render_template(
        "admin_luggage_detail.html",
        luggage=luggage, booking=booking, room=room, guest=guest, prop=prop, scans=scans
    )


# ---------------- Host: create / update / delete ----------------

@bp.get("/new")
@login_required
def new():
    if not _host_only():
        flash("Only hosts can register luggage.", "error")
        return redirect(url_for("luggage.list_"))

    # Show recent/upcoming bookings to attach luggage to
    bookings = (
        db.session.query(Booking, Room, Guest, Property)
        .join(Room, Booking.room_id == Room.id)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Property, Room.property_id == Property.id)
        .order_by(Booking.check_in.desc())
        .limit(300)
        .all()
    )
    return render_template("admin_luggage_new.html", bookings=bookings)


@bp.post("/new")
@login_required
def create():
    if not _host_only():
        flash("Only hosts can register luggage.", "error")
        return redirect(url_for("luggage.list_"))

    booking_id = int(request.form.get("booking_id") or 0)
    label = (request.form.get("label") or "").strip()
    size = (request.form.get("size") or "medium").strip().lower()
    photo = request.files.get("photo")

    if not booking_id:
        flash("Booking is required.", "error")
        return redirect(url_for("luggage.new"))
    if not label:
        flash("Label is required.", "error")
        return redirect(url_for("luggage.new"))

    # ensure booking exists
    booking = Booking.query.get_or_404(booking_id)

    # generate QR token
    qr_token = secrets.token_urlsafe(16)

    # optional photo upload
    photo_path = None
    if photo and photo.filename:
        upload_dir = os.path.join(current_app.root_path, "uploads", "luggage")
        os.makedirs(upload_dir, exist_ok=True)
        fname = datetime.utcnow().strftime("%Y%m%d%H%M%S_") + secure_filename(photo.filename)
        full = os.path.join(upload_dir, fname)
        photo.save(full)
        # store path relative to app root for portability
        photo_path = full.replace(current_app.root_path, "")

    lug = Luggage(
        booking_id=booking.id,
        label=label,
        size=size,
        photo_path=photo_path,
        qr_token=qr_token,
        status="pending"
    )
    db.session.add(lug)
    db.session.commit()

    flash("Luggage registered and QR generated.", "success")
    return redirect(url_for("luggage.detail", lug_id=lug.id))


@bp.post("/<int:lug_id>/block")
@login_required
def block(lug_id: int):
    if not _host_only():
        flash("Only hosts can manage luggage status.", "error")
        return redirect(url_for("luggage.list_"))

    lug = Luggage.query.get_or_404(lug_id)
    lug.status = "blocked"
    db.session.commit()
    flash("Luggage blocked.", "success")
    return redirect(url_for("luggage.detail", lug_id=lug.id))


@bp.post("/<int:lug_id>/unblock")
@login_required
def unblock(lug_id: int):
    if not _host_only():
        flash("Only hosts can manage luggage status.", "error")
        return redirect(url_for("luggage.list_"))

    lug = Luggage.query.get_or_404(lug_id)
    # if it hasn't exited yet, put back to pending; otherwise keep exited
    lug.status = "pending" if lug.status != "exited" else "exited"
    db.session.commit()
    flash("Luggage unblocked.", "success")
    return redirect(url_for("luggage.detail", lug_id=lug.id))


@bp.post("/<int:lug_id>/delete")
@login_required
def delete(lug_id: int):
    if not _host_only():
        flash("Only hosts can delete luggage.", "error")
        return redirect(url_for("luggage.list_"))

    lug = Luggage.query.get_or_404(lug_id)
    db.session.delete(lug)
    db.session.commit()
    flash("Luggage deleted.", "success")
    return redirect(url_for("luggage.list_"))


# ---------------- QR image (PNG) ----------------

@bp.get("/qr/<token>.png")
@login_required
def qr_png(token: str):
    """Serve a QR image for a luggage token (Hosts/Admins can print)."""
    if qrcode is None:
        return "qrcode library not installed. pip install qrcode[pil]", 500

    lug = Luggage.query.filter_by(qr_token=token).first_or_404()
    img = qrcode.make(token, image_factory=PilImage, box_size=6, border=2)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png", download_name=f"luggage_{lug.id}.png")


# ---------------- Guard: scanner page & scan API ----------------

@bp.get("/scan")
@login_required
def guard_scan_page():
    if not _guard_only():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    checkpoints = Checkpoint.query.order_by(Checkpoint.name.asc()).all()
    return render_template("guard_luggage_scan.html", checkpoints=checkpoints)


@bp.post("/scan")
@login_required
def guard_scan_post():
    if not _guard_only():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    checkpoint_id = int(request.form.get("checkpoint_id") or 0)
    token = (request.form.get("qr_token") or "").strip()

    if not token:
        return jsonify({
            "ok": True,
            "decision": "deny",
            "reason": "no_qr",
            "message": "No QR token detected."
        })

    lug_join = (
        db.session.query(Luggage, Booking, Room, Guest, Property)
        .join(Booking, Luggage.booking_id == Booking.id)
        .join(Room, Booking.room_id == Room.id)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Property, Room.property_id == Property.id)
        .filter(Luggage.qr_token == token)
        .first()
    )

    if not lug_join:
        db.session.add(LuggageScanLog(
            guard_id=current_user.id,
            checkpoint_id=checkpoint_id,
            luggage_id=0,
            decision="deny",
            note="QR not found"
        ))
        db.session.commit()
        return jsonify({"ok": True, "decision": "deny", "message": "QR not recognized."})

    luggage, booking, room, guest, prop = lug_join

    # Business rules
    decision = "allow"
    message = "Authorized to exit."
    if luggage.status == "exited":
        decision, message = "deny", "Already exited."
    elif luggage.status == "blocked":
        decision, message = "deny", "Blocked item."

    # Log the scan
    db.session.add(LuggageScanLog(
        guard_id=current_user.id,
        checkpoint_id=checkpoint_id,
        luggage_id=luggage.id,
        decision=decision,
        note=message
    ))

    if decision == "allow":
        luggage.status = "exited"
        db.session.add(luggage)

    db.session.commit()

    info = {
        "luggage_id": luggage.id,
        "label": luggage.label,
        "size": luggage.size,
        "photo": luggage.photo_path,
        "status": luggage.status,
        "booking_id": booking.id,
        "guest_name": guest.full_name,
        "room": room.name,
        "property": prop.name,
        "check_in": booking.check_in.isoformat(),
        "check_out": booking.check_out.isoformat(),
    }
    return jsonify({"ok": True, "decision": decision, "info": info})
