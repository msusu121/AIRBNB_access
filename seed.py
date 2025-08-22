from datetime import datetime, timedelta
from app import app, db
from models import User, Property, Room, Guest, Booking, Checkpoint, ROLE_ADMIN, ROLE_GUARD, ROLE_HOST

with app.app_context():
    # Users
    if not User.query.filter_by(email="admin@example.com").first():
        u = User(email="admin@example.com", name="Admin", role=ROLE_ADMIN); u.set_password("admin123"); db.session.add(u)
    if not User.query.filter_by(email="guard@example.com").first():
        u = User(email="guard@example.com", name="Gate Guard", role=ROLE_GUARD); u.set_password("guard123"); db.session.add(u)
    if not User.query.filter_by(email="host@example.com").first():
        u = User(email="host@example.com", name="Host One", role=ROLE_HOST); u.set_password("host123"); db.session.add(u)
    db.session.commit()

    host = User.query.filter_by(email="host@example.com").first()

    # Property/Room
    prop = Property.query.filter_by(name="Seafront Suites").first()
    if not prop:
        prop = Property(owner_id=host.id, name="Seafront Suites", address="Old Town, Mombasa"); db.session.add(prop); db.session.commit()

    room = Room.query.filter_by(property_id=prop.id, name="Room 1A").first()
    if not room:
        room = Room(property_id=prop.id, name="Room 1A", desc="Queen bed, ocean view"); db.session.add(room); db.session.commit()

    # Checkpoint
    gate = Checkpoint.query.filter_by(property_id=prop.id, name="Main Gate").first()
    if not gate:
        gate = Checkpoint(property_id=prop.id, name="Main Gate"); db.session.add(gate); db.session.commit()

    # Guest + Booking (sample)
    guest = Guest.query.filter_by(national_id_number="12345678").first()
    if not guest:
        guest = Guest(full_name="Sample Guest", national_id_number="12345678", phone="+254700000000", email="guest@example.com")
        db.session.add(guest); db.session.commit()

    now = datetime.utcnow()
    if not Booking.query.filter_by(guest_id=guest.id, room_id=room.id).first():
        bk = Booking(
            guest_id=guest.id, room_id=room.id,
            check_in=now - timedelta(hours=2),
            check_out=now + timedelta(days=3),
            status="booked",
            guests_count=3,
            owns_vehicle=True,
            vehicle_plate="KDA 123A"
        )
        db.session.add(bk); db.session.commit()

    print("Seed complete. Admin/Guard/Host users created, property/room/checkpoint & booking ready.")
