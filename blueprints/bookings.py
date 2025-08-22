from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import db, Room, Booking, Guest, ROLE_ADMIN, ROLE_HOST

bp = Blueprint("bookings", __name__, url_prefix="/bookings")

def _can_manage():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

@bp.get("/")
@login_required
def index():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    bookings = Booking.query.order_by(Booking.id.desc()).limit(100).all()
    return render_template("bookings_list.html", bookings=bookings)

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
