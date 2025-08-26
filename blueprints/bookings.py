# blueprints/bookings.py
import os, io, secrets
from datetime import datetime, date, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, current_app, send_file, send_from_directory
)
from flask_login import login_required, current_user
from sqlalchemy import and_

from models import db, Room, Booking, Guest, Property, ROLE_ADMIN, ROLE_HOST
from datetime import datetime
from utils.plan_gate import require_plan, require_paid


def _parse_dt(value: str) -> datetime:
    s = (value or "").strip().replace("T", " ")
    s = " ".join(s.split())  # collapse multiple spaces to single
    # Try the flexible ISO parser first
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    # Fallback common formats
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value!r}")

# Optional QR lib (PNG generation)
try:
    import qrcode
    from qrcode.image.pil import PilImage
except Exception:
    qrcode = None

bp = Blueprint("bookings", __name__, url_prefix="/bookings")

def _can_view():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

def _can_create():
    return current_user.is_authenticated and current_user.role == ROLE_HOST


@bp.get("/")
@login_required
def index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    # Scope rooms: host -> only their rooms; admin -> all rooms
    rooms_q = (
        db.session.query(Room)
        .join(Property, Room.property_id == Property.id)
        .filter(Property.owner_id == current_user.id)
        .order_by(Room.name.asc())
        .all()
        if current_user.role == ROLE_HOST
        else Room.query.order_by(Room.name.asc()).all()
    )
    rooms_data = [{"id": r.id, "name": r.name} for r in rooms_q]
    return render_template("bookings_calendar.html", rooms=rooms_data)


@bp.get("/data")
@login_required
def data():
    if not _can_view():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    # Parse incoming range (fallback to ~6-week grid if missing)
    start_s = request.args.get("start")
    end_s   = request.args.get("end")
    try:
        if not start_s or not end_s:
            today = date.today()
            month_first = today.replace(day=1)
            start = month_first - timedelta(days=(month_first.weekday() + 1) % 7)
            end = start + timedelta(days=41)
        else:
            start = datetime.fromisoformat(start_s).date()
            end   = datetime.fromisoformat(end_s).date()
    except Exception:
        return jsonify({"ok": False, "error": "Bad date range"}), 400

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt   = datetime.combine(end,   datetime.max.time())

    # Base query: overlap in range
    q = (
        db.session.query(Booking)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Room,  Booking.room_id  == Room.id)
        .join(Property, Room.property_id == Property.id)
        .filter(and_(Booking.check_in <= end_dt, Booking.check_out >= start_dt))
        .order_by(Booking.check_in.asc())
    )

    # Host scoping: only bookings for rooms in properties they own
    if current_user.role == ROLE_HOST:
        q = q.filter(Property.owner_id == current_user.id)

    bookings = q.all()

    events = [{
        "id": b.id,
        "guest": b.guest.full_name,
        "national_id": b.guest.national_id_number,
        "room_id": b.room_id,
        "room": b.room.name,
        "check_in": b.check_in.isoformat(),
        "check_out": b.check_out.isoformat(),
        "guests_count": b.guests_count,
        "owns_vehicle": bool(b.owns_vehicle),
        "vehicle_plate": b.vehicle_plate or "",
        "status": b.status,
        "qr_token": b.qr_token or "",
    } for b in bookings]

    # Rooms list also needs to be host-scoped
    rooms_q = (
        db.session.query(Room)
        .join(Property, Room.property_id == Property.id)
        .filter(Property.owner_id == current_user.id)
        .order_by(Room.name.asc())
        .all()
        if current_user.role == ROLE_HOST
        else Room.query.order_by(Room.name.asc()).all()
    )
    rooms_data = [{"id": r.id, "name": r.name} for r in rooms_q]

    return jsonify({"ok": True, "events": events, "rooms": rooms_data})


@bp.get("/new")
@login_required
@require_paid()  
def new_booking():
    if not _can_create():
        flash("Only hosts can add bookings", "error")
        return redirect(url_for("bookings.index"))

    # Admin sees all rooms. Host sees only their own rooms.
    if current_user.role == ROLE_HOST:
        rooms = (
            db.session.query(Room)
            .join(Property, Property.id == Room.property_id)
            .filter(Property.owner_id == current_user.id)
            .order_by(Room.name.asc())
            .all()
        )
        if not rooms:
            flash("You have no rooms yet. Create a room first.", "error")
            return redirect(url_for("admin.rooms_new"))
    else:
        rooms = Room.query.order_by(Room.name.asc()).all()

    return render_template("booking_new.html", rooms=rooms)


@bp.post("/new")
@login_required
@require_paid() 
def create_booking():
    if not _can_create():
        flash("Only hosts can add bookings", "error")
        return redirect(url_for("bookings.index"))

    # --- robust date parser (handles '2025-08-25  16:00', '2025-08-25T16:00', '2025-08-25') ---
    def _parse_dt(value: str) -> datetime:
        s = (value or "").strip().replace("T", " ")
        s = " ".join(s.split())
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Invalid datetime: {value!r}")

    guest_name  = (request.form.get("guest_name") or "").strip()
    national_id = (request.form.get("national_id") or "").strip()
    phone       = (request.form.get("phone") or "").strip()
    email       = (request.form.get("email") or "").strip()

    try:
        room_id   = int(request.form.get("room_id") or 0)
    except ValueError:
        room_id = 0

    try:
        check_in  = _parse_dt(request.form.get("check_in"))
        check_out = _parse_dt(request.form.get("check_out"))
    except ValueError:
        flash("Please enter valid dates/times for check-in and check-out.", "error")
        return redirect(url_for("bookings.new_booking"))

    guests_count  = int(request.form.get("guests_count") or 1)
    owns_vehicle  = request.form.get("owns_vehicle") == "on"
    vehicle_plate = (request.form.get("vehicle_plate") or "").strip() or None

    if owns_vehicle and not vehicle_plate:
        flash("Vehicle plate required when 'Owns vehicle' is checked.", "error")
        return redirect(url_for("bookings.new_booking"))

    # Validate the room and host ownership
    room_q = (
        db.session.query(Room)
        .filter(Room.id == room_id)
    )
    if current_user.role == ROLE_HOST:
        room_q = room_q.join(Property, Property.id == Room.property_id)\
                       .filter(Property.owner_id == current_user.id)

    room = room_q.first()
    if not room:
        flash("Invalid room selection.", "error")
        return redirect(url_for("bookings.new_booking"))

    # Create guest (simple create per your flow)
    guest = Guest(full_name=guest_name, national_id_number=national_id, phone=phone, email=email)
    db.session.add(guest); db.session.flush()

    # Create booking
    booking = Booking(
        guest_id=guest.id, room_id=room.id,
        check_in=check_in, check_out=check_out,
        status="booked", guests_count=guests_count,
        owns_vehicle=owns_vehicle, vehicle_plate=vehicle_plate
    )

    # Generate QR token
    booking.qr_token = secrets.token_urlsafe(16)
    db.session.add(booking); db.session.flush()

    # Save QR PNG (if qrcode is available)
    if qrcode is not None:
        upload_dir = os.path.join(current_app.root_path, "uploads", "bookings")
        os.makedirs(upload_dir, exist_ok=True)
        fname = f"booking_{booking.id}.png"
        full_path = os.path.join(upload_dir, fname)
        img = qrcode.make(booking.qr_token, image_factory=PilImage, box_size=8, border=2)
        img.save(full_path)
        booking.qr_path = f"/uploads/bookings/{fname}"

    db.session.commit()

    flash("Booking created (QR generated).", "success")
    return redirect(url_for("bookings.detail", booking_id=booking.id))


@bp.get("/<int:booking_id>")
@login_required
@require_paid() 
def detail(booking_id: int):
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    b = Booking.query.get_or_404(booking_id)

    # Host can only open their own booking detail
    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("bookings.index"))

    room = Room.query.get(b.room_id)
    guest = Guest.query.get(b.guest_id)
    return render_template("booking_detail.html", booking=b, guest=guest, room=room)


# ------------ Serve booking QR from token (PNG on-the-fly) ------------
@bp.get("/qr/<token>.png")
@login_required
def booking_qr_png(token: str):
    if qrcode is None:
        return "qrcode library not installed. pip install qrcode[pil]", 500
    b = Booking.query.filter_by(qr_token=token).first_or_404()

    # Host guard: only allow if the QR belongs to their room
    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("home"))

    img = qrcode.make(token, image_factory=PilImage, box_size=8, border=2)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png", download_name=f"booking_{b.id}.png")


@bp.get("/qr/<token>/download")
@login_required
def booking_qr_download(token: str):
    if qrcode is None:
        return "qrcode library not installed. pip install qrcode[pil]", 500
    b = Booking.query.filter_by(qr_token=token).first_or_404()

    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("home"))

    img = qrcode.make(token, image_factory=PilImage, box_size=10, border=2)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png", as_attachment=True, download_name=f"booking_{b.id}.png")


# ------------ Serve saved PNG (if you used booking.qr_path) ------------
@bp.get("/uploads/bookings/<path:fname>")
@login_required
def booking_qr_uploads(fname: str):
    folder = os.path.join(current_app.root_path, "uploads", "bookings")
    return send_from_directory(folder, fname)
