# blueprints/bookings.py
import os
import io
import smtplib
import secrets
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from mimetypes import guess_type

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, current_app, send_file, send_from_directory
)
from flask_login import login_required, current_user
from sqlalchemy import and_, or_

from models import db, Room, Booking, Guest, Property, ROLE_ADMIN, ROLE_HOST
from utils.plan_gate import require_plan, require_paid  # optional gates

# ----- QR REQUIRED -----
try:
    import qrcode
    from qrcode.image.pil import PilImage
except Exception as e:
    raise RuntimeError("QR generation is required. pip install 'qrcode[pil]'") from e


bp = Blueprint("bookings", __name__, url_prefix="/bookings")


# ---------------- Helpers ----------------
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


def _can_view():
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)


def _can_create():
    return current_user.is_authenticated and current_user.role == ROLE_HOST


def _ensure_booking_qr(booking: Booking) -> str:
    """
    Generate and save PNG QR for the booking. Returns absolute file path.
    Sets booking.qr_token and booking.qr_path (WEB path).
    """
    if not booking.qr_token:
        booking.qr_token = secrets.token_urlsafe(16)

    upload_dir = os.path.join(current_app.root_path, "uploads", "bookings")
    os.makedirs(upload_dir, exist_ok=True)

    fname = f"booking_{booking.id}.png"
    abs_path = os.path.join(upload_dir, fname)

    img = qrcode.make(booking.qr_token, image_factory=PilImage, box_size=8, border=2)
    img.save(abs_path)

    booking.qr_path = f"/uploads/bookings/{fname}"
    return abs_path


# ---------------- Email helpers ----------------
def _smtp_settings():
    """Read SMTP config from env; minimal validation."""
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    use_tls = (os.getenv("SMTP_USE_TLS", "true").lower() != "false")
    sender = os.getenv("MAIL_FROM") or user
    if not (host and port and user and pwd and sender):
        raise RuntimeError(
            "Missing SMTP config. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, and optionally MAIL_FROM."
        )
    return host, port, user, pwd, use_tls, sender


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _send_booking_email(guest: Guest, booking: Booking, room: Room, prop: Property | None, qr_abs_path: str):
    """
    Compose and send a booking confirmation email with inline QR (cid) and the PNG attached.
    Does nothing if guest.email is empty.
    """
    if not guest or not guest.email:
        return  # nothing to send

    host, port, user, pwd, use_tls, sender = _smtp_settings()

    # Prepare inline CID for QR
    qr_cid = make_msgid(domain="qr.local")  # e.g. "<...@qr.local>"
    qr_cid_clean = qr_cid.strip("<>")

    # Read QR bytes
    qr_bytes = _read_bytes(qr_abs_path)
    mime_type, _ = guess_type(qr_abs_path)
    if not mime_type:
        mime_type = "image/png"
    maintype, subtype = mime_type.split("/", 1)

    # Human text
    prop_name = prop.name if prop else "—"
    room_name = room.name if room else "—"

    html = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="x-apple-disable-message-reformatting">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Booking Confirmed</title>
  </head>
  <body style="margin:0;padding:0;background:#f6f7fb;color:#0f172a;">
    <!-- Preheader (hidden in most clients) -->
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Your booking is confirmed. Show the QR at the gate.
    </div>

    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f6f7fb;">
      <tr>
        <td align="center" style="padding:24px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:640px;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;">
            <!-- Header -->
            <tr>
              <td style="padding:18px 22px;border-bottom:1px solid #e5e7eb;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                  <tr>
                    <td style="vertical-align:middle;">
                      <div style="display:inline-block;width:28px;height:28px;background:#0f172a;border-radius:9px;"></div>
                      <span style="font:600 18px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;margin-left:10px;color:#0f172a;">
                        Airbnb Gate Access
                      </span>
                    </td>
                    <td align="right" style="vertical-align:middle;">
                      <span style="font:600 14px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#0f172a;">
                        Booking Confirmed
                      </span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

            <!-- Body -->
            <tr>
              <td style="padding:22px;">
                <!-- Greeting -->
                <div style="font:600 18px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;line-height:1.35;color:#0f172a;">
                  Hi {guest.full_name.split()[0] if guest.full_name else 'there'},
                </div>
                <div style="margin-top:6px;font:400 13px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#475569;">
                  Your visit has been scheduled successfully. Please present the QR code below at the gate for a quick check-in.
                </div>

                <!-- Card -->
                <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-top:16px;border:1px solid #e5e7eb;border-radius:14px;">
                  <tr>
                    <td style="padding:16px 18px;">

                      <!-- Two columns on desktop, stacked on mobile (table layout is naturally fluid) -->
                      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                          <!-- Details -->
                          <td style="vertical-align:top;padding-right:8px;">
                            <div style="font:700 14px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#0f172a;margin-bottom:8px;">
                              Booking Details
                            </div>

                            <table role="presentation" cellpadding="0" cellspacing="0" style="font:400 13px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#0f172a;">
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">Guest</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{guest.full_name}</td>
                              </tr>
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">National ID</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{guest.national_id_number}</td>
                              </tr>
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">Property / Room</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{prop_name or '—'} &nbsp;·&nbsp; {room_name or '—'}</td>
                              </tr>
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">Check-in</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{booking.check_in.strftime('%Y-%m-%d %H:%M')}</td>
                              </tr>
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">Check-out</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{booking.check_out.strftime('%Y-%m-%d %H:%M')}</td>
                              </tr>
                              <tr>
                                <td style="padding:3px 0;white-space:nowrap;color:#475569;">Guests</td>
                                <td style="padding:3px 8px;color:#94a3b8;">•</td>
                                <td style="padding:3px 0;">{booking.guests_count}</td>
                              </tr>
                              {"".join([
                                f"<tr><td style='padding:3px 0;white-space:nowrap;color:#475569;'>Vehicle</td>",
                                "<td style='padding:3px 8px;color:#94a3b8;'>•</td>",
                                f"<td style='padding:3px 0;'>{(booking.vehicle_plate or '—')}</td></tr>"
                              ]) if booking.owns_vehicle else "" }
                            </table>
                          </td>

                          <!-- QR -->
                          <td align="right" style="vertical-align:top;padding-left:8px;">
                            <div style="font:700 13px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#0f172a;margin:0 0 8px;">
                              Entry QR
                            </div>
                            <div style="padding:8px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;display:inline-block;">
                              <img src="cid:{qr_cid_clean}" alt="Booking QR code"
                                   width="180" height="180"
                                   style="display:block;width:180px;height:180px;border:0;outline:0;text-decoration:none;" />
                            </div>
                            <div style="font:400 11px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#64748b;margin-top:6px;max-width:220px;">
                              Present this code at the gate for faster entry.
                            </div>
                          </td>
                        </tr>
                      </table>

                    </td>
                  </tr>
                </table>

                <!-- CTA -->
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:18px 0 4px 0;">
                  <tr>
                    <td align="left">
                      <a href="{url_for('bookings.detail', booking_id=booking.id, _external=True)}"
                         style="background:#0f172a;color:#ffffff;text-decoration:none;font:600 14px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;padding:10px 16px;border-radius:10px;display:inline-block;">
                        View Booking
                      </a>
                    </td>
                  </tr>
                </table>

                <!-- Note -->
                <div style="margin-top:8px;font:400 12px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#64748b;">
                  Keep this email for your records. If any details are incorrect, reply to this message.
                </div>
              </td>
            </tr>

            <!-- Footer -->
            <tr>
              <td style="padding:14px 22px;background:#f8fafc;border-top:1px solid #e5e7eb;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="font:400 12px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#64748b;">
                      Booking #{booking.id} · Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
                    </td>
                    <td align="right" style="font:400 12px ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#94a3b8;">
                      © {datetime.utcnow().strftime('%Y')} Airbnb Gate Access
                    </td>
                  </tr>
                </table>
              </td>
            </tr>

          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


    # Plaintext fallback
    text = (
        f"Booking Confirmed\n"
        f"Guest: {guest.full_name}\n"
        f"ID: {guest.national_id_number}\n"
        f"Property/Room: {prop_name} / {room_name}\n"
        f"Check-in: {booking.check_in}\n"
        f"Check-out: {booking.check_out}\n"
        f"Guests: {booking.guests_count}\n"
        f"Vehicle: {booking.vehicle_plate or '-'}\n\n"
        f"Present the attached QR at the gate."
    )

    msg = EmailMessage()
    msg["Subject"] = f"Booking Confirmation #{booking.id}"
    msg["From"] = sender
    msg["To"] = guest.email
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)

    # Add HTML alternative
    msg.add_alternative(html, subtype="html")

    # Attach inline QR (cid)
    msg.get_payload()[-1].add_related(qr_bytes, maintype=maintype, subtype=subtype, cid=qr_cid)

    # Also attach as file
    msg.add_attachment(qr_bytes, maintype=maintype, subtype=subtype, filename=f"booking_{booking.id}.png")

    # Send
    try:
        if use_tls:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls()
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        current_app.logger.info("Booking email sent to %s (#%s)", guest.email, booking.id)
    except Exception as e:
        current_app.logger.warning("Failed to send booking email: %s", e)


# ---------------- Pages ----------------
@bp.get("/")
@login_required
def index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    if current_user.role == ROLE_HOST:
        rooms_q = (
            db.session.query(Room)
            .outerjoin(Property, Room.property_id == Property.id)
            .filter(or_(Property.owner_id == current_user.id, Room.property_id.is_(None)))
            .order_by(Room.name.asc())
            .all()
        )
    else:
        rooms_q = Room.query.order_by(Room.name.asc()).all()

    rooms_data = [{"id": r.id, "name": (r.name or f"Room #{r.id}")} for r in rooms_q]
    return render_template("bookings_calendar.html", rooms=rooms_data)


@bp.get("/data")
@login_required
def data():
    if not _can_view():
        return jsonify({"ok": False, "error": "Unauthorized"}), 403

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

    q = (
        db.session.query(Booking)
        .join(Guest, Booking.guest_id == Guest.id)
        .join(Room,  Booking.room_id  == Room.id)
        .outerjoin(Property, Room.property_id == Property.id)
        .filter(and_(Booking.check_in <= end_dt, Booking.check_out >= start_dt))
        .order_by(Booking.check_in.asc())
    )
    if current_user.role == ROLE_HOST:
        q = q.filter(or_(Property.owner_id == current_user.id, Room.property_id.is_(None)))

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

    if current_user.role == ROLE_HOST:
        rooms_q = (
            db.session.query(Room)
            .outerjoin(Property, Room.property_id == Property.id)
            .filter(or_(Property.owner_id == current_user.id, Room.property_id.is_(None)))
            .order_by(Room.name.asc())
            .all()
        )
    else:
        rooms_q = Room.query.order_by(Room.name.asc()).all()

    rooms_data = [{"id": r.id, "name": (r.name or f"Room #{r.id}")} for r in rooms_q]
    return jsonify({"ok": True, "events": events, "rooms": rooms_data})


@bp.get("/new")
@login_required
def new_booking():
    if not _can_create():
        flash("Only hosts can add bookings", "error")
        return redirect(url_for("bookings.index"))

    if current_user.role == ROLE_HOST:
        rooms = (
            db.session.query(Room)
            .outerjoin(Property, Property.id == Room.property_id)
            .filter(or_(Property.owner_id == current_user.id, Room.property_id.is_(None)))
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
def create_booking():
    if not _can_create():
        flash("Only hosts can add bookings", "error")
        return redirect(url_for("bookings.index"))

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

    # Validate room (include NULL-property rooms for hosts)
    room_q = db.session.query(Room).filter(Room.id == room_id)
    if current_user.role == ROLE_HOST:
        room_q = (
            room_q.outerjoin(Property, Property.id == Room.property_id)
                  .filter(or_(Property.owner_id == current_user.id, Room.property_id.is_(None)))
        )
    room = room_q.first()
    if not room:
        flash("Invalid room selection.", "error")
        return redirect(url_for("bookings.new_booking"))

    # Create guest
    guest = Guest(full_name=guest_name, national_id_number=national_id, phone=phone, email=email)
    db.session.add(guest); db.session.flush()

    # Create booking
    booking = Booking(
        guest_id=guest.id,
        room_id=room.id,
        check_in=check_in,
        check_out=check_out,
        status="booked",
        guests_count=guests_count,
        owns_vehicle=owns_vehicle,
        vehicle_plate=vehicle_plate
    )
    db.session.add(booking); db.session.flush()  # get booking.id

    # QR required
    qr_abs_path = _ensure_booking_qr(booking)

    db.session.commit()

    # Send email (best-effort; won't block UX)
    try:
        _send_booking_email(guest, booking, room, Property.query.get(room.property_id) if room.property_id else None, qr_abs_path)
    except Exception as e:
        current_app.logger.warning("Email send failed: %s", e)

    flash("Booking created (QR generated & emailed).", "success")
    return redirect(url_for("bookings.detail", booking_id=booking.id))


@bp.get("/<int:booking_id>")
@login_required
def detail(booking_id: int):
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    b = Booking.query.get_or_404(booking_id)

    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id, isouter=True)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id is not None and owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("bookings.index"))

    room = Room.query.get(b.room_id)
    guest = Guest.query.get(b.guest_id)
    return render_template("booking_detail.html", booking=b, guest=guest, room=room)


@bp.get("/qr/<token>.png")
@login_required
def booking_qr_png(token: str):
    b = Booking.query.filter_by(qr_token=token).first_or_404()

    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id, isouter=True)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id is not None and owner_id != current_user.id:
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
    b = Booking.query.filter_by(qr_token=token).first_or_404()

    if current_user.role == ROLE_HOST:
        owner_id = (
            db.session.query(Property.owner_id)
            .join(Room, Room.property_id == Property.id, isouter=True)
            .filter(Room.id == b.room_id)
            .scalar()
        )
        if owner_id is not None and owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("home"))

    img = qrcode.make(token, image_factory=PilImage, box_size=10, border=2)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png", as_attachment=True, download_name=f"booking_{b.id}.png")


@bp.get("/uploads/bookings/<path:fname>")
@login_required
def booking_qr_uploads(fname: str):
    folder = os.path.join(current_app.root_path, "uploads", "bookings")
    return send_from_directory(folder, fname)
