from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, Room, Booking, Guest, ROLE_ADMIN, ROLE_HOST
from sqlalchemy import and_

bp = Blueprint("bookings", __name__, url_prefix="/bookings")

def _can_manage():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

@bp.get("/")
@login_required
def index():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    # >>> Build a JSON-serializable list for the template
    rooms_q = Room.query.order_by(Room.name.asc()).all()
    rooms_data = [{"id": r.id, "name": r.name} for r in rooms_q]

    # Render the calendar shell; events are fetched via /bookings/data
    return render_template("bookings_calendar.html", rooms=rooms_data)

@bp.get("/data")
@login_required
def data():
    if not _can_manage():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

    # Parse range
    start_s = request.args.get("start")
    end_s   = request.args.get("end")
    try:
        if not start_s or not end_s:
            today = date.today()
            month_first = today.replace(day=1)
            # start on Sunday before/at month start (adjust if you want Monday start)
            start = month_first - timedelta(days=(month_first.weekday() + 1) % 7)
            end = start + timedelta(days=41)  # 6-week grid
        else:
            start = datetime.fromisoformat(start_s).date()
            end   = datetime.fromisoformat(end_s).date()
    except Exception:
        return jsonify({"ok": False, "error": "Bad date range"}), 400

    start_dt = datetime.combine(start, datetime.min.time())
    end_dt   = datetime.combine(end,   datetime.max.time())

    bookings = (
        db.session.query(Booking)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Room, Booking.room_id == Room.id)
        .filter(
            and_(
                Booking.check_in <= end_dt,
                Booking.check_out >= start_dt
            )
        )
        .order_by(Booking.check_in.asc())
        .all()
    )

    events = []
    for b in bookings:
        events.append({
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
        })

    rooms_data = [{"id": r.id, "name": r.name} for r in Room.query.order_by(Room.name.asc()).all()]
    return jsonify({"ok": True, "events": events, "rooms": rooms_data})

@bp.get("/new")
@login_required
def new_booking():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    rooms = Room.query.all()
    return render_template("booking_new.html", rooms=rooms)

@bp.post("/new")
@login_required
def create_booking():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    # Required guest fields
    guest_name = request.form.get("guest_name", "").strip()
    national_id = request.form.get("national_id", "").strip()

    # Optional contact
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()

    # Booking + stay
    room_id = int(request.form.get("room_id"))
    check_in = datetime.fromisoformat(request.form.get("check_in"))
    check_out = datetime.fromisoformat(request.form.get("check_out"))

    # Your requested fields
    guests_count = int(request.form.get("guests_count", 1))
    owns_vehicle = request.form.get("owns_vehicle") == "on"
    vehicle_plate = (request.form.get("vehicle_plate") or "").strip() or None

    if owns_vehicle and not vehicle_plate:
        flash("Vehicle plate is required when 'Owns vehicle' is checked.", "error")
        return redirect(url_for("bookings.new_booking"))

    guest = Guest(full_name=guest_name, national_id_number=national_id, phone=phone, email=email)
    db.session.add(guest)
    db.session.flush()

    booking = Booking(
        guest_id=guest.id,
        room_id=room_id,
        check_in=check_in,
        check_out=check_out,
        status="booked",
        guests_count=guests_count,
        owns_vehicle=owns_vehicle,
        vehicle_plate=vehicle_plate
    )
    db.session.add(booking)
    db.session.commit()
    flash("Booking created", "success")
    return redirect(url_for("bookings.index"))
