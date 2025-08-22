from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLE_ADMIN = "admin"
ROLE_HOST = "host"
ROLE_GUARD = "guard"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_HOST)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw): self.password_hash = generate_password_hash(raw)
    def check_password(self, raw): return check_password_hash(self.password_hash, raw)

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    address = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner = db.relationship("User")

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    desc = db.Column(db.Text)
    property = db.relationship("Property")

class Guest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    national_id_number = db.Column(db.String(100), index=True)  # OCR target
    phone = db.Column(db.String(50))
    email = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.Integer, db.ForeignKey("guest.id"), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), default="booked")  # booked|checked_in|checked_out|cancelled
    guests_count = db.Column(db.Integer, default=1)
    owns_vehicle = db.Column(db.Boolean, default=False)
    vehicle_plate = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    guest = db.relationship("Guest")
    room = db.relationship("Room")

class Checkpoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False)
    property = db.relationship("Property")

class AccessLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    guard_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    checkpoint_id = db.Column(db.Integer, db.ForeignKey("checkpoint.id"), nullable=False)
    guest_id = db.Column(db.Integer, db.ForeignKey("guest.id"))
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"))
    national_id_number = db.Column(db.String(100))  # from OCR or manual
    decision = db.Column(db.String(20))            # allow|deny
    image_path = db.Column(db.String(255))
    ocr_text = db.Column(db.Text)

    guard = db.relationship("User")
    checkpoint = db.relationship("Checkpoint")
    guest = db.relationship("Guest")
    booking = db.relationship("Booking")
