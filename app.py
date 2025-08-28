from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager, current_user
from config import Config
from models import db, User
from blueprints.auth import bp as auth_bp
from blueprints.bookings import bp as bookings_bp
from blueprints.guard import bp as guard_bp
from blueprints.admin import bp as admin_bp
from blueprints.luggage import bp as luggage_bp
from blueprints.mpesa import bp as mpesa_bp
from blueprints.billing import bp as billing_bp
from sqlalchemy import and_, func, or_
from models import db, User, Booking, Room, Property, Luggage  
import pytz
from datetime import datetime, date, time as dt_time
NAIROBI_TZ = pytz.timezone("Africa/Nairobi")

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)

    db.init_app(app)
    with app.app_context():
        db.create_all()

    login_manager = LoginManager()
    login_manager.login_view = "auth.login_page"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id): return User.query.get(int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(guard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(luggage_bp)
    app.register_blueprint(mpesa_bp)
    app.register_blueprint(billing_bp)

    @app.get("/")
    def home():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login_page"))

        # --- Work in Nairobi-local *naive* time to match your DB values ---
        tz = pytz.timezone("Africa/Nairobi")
        now_naive = datetime.now(tz).replace(tzinfo=None)  # e.g. 2025-08-28 14:30:00
        today = now_naive.date()
        day_start = datetime.combine(today, dt_time.min)   # 2025-08-28 00:00:00
        day_end   = datetime.combine(today, dt_time.max)   # 2025-08-28 23:59:59.999999

        # Base filters
        active_filter = and_(
            Booking.check_in <= now_naive,
            Booking.check_out >= now_naive,
            Booking.status != "cancelled",
        )
        today_checkins_filter = and_(
            Booking.check_in >= day_start,
            Booking.check_in <= day_end,
            Booking.status != "cancelled",
        )

        # Scope by role:
        if current_user.role == "host":
            # host sees: rooms in properties they own OR rooms with no property
            # (rooms can be nullable property_id in your schema)
            active_q = (
                db.session.query(Booking)
                .join(Room, Room.id == Booking.room_id)
                .outerjoin(Property, Property.id == Room.property_id)
                .filter(
                    active_filter,
                    or_(Property.owner_id == current_user.id, Room.property_id.is_(None)),
                )
            )

            todays_q = (
                db.session.query(Booking)
                .join(Room, Room.id == Booking.room_id)
                .outerjoin(Property, Property.id == Room.property_id)
                .filter(
                    today_checkins_filter,
                    or_(Property.owner_id == current_user.id, Room.property_id.is_(None)),
                )
            )

            luggage_pending_q = (
                db.session.query(Luggage)
                .join(Booking, Booking.id == Luggage.booking_id)
                .join(Room, Room.id == Booking.room_id)
                .outerjoin(Property, Property.id == Room.property_id)
                .filter(
                    Luggage.status == "pending",
                    or_(Property.owner_id == current_user.id, Room.property_id.is_(None)),
                )
            )
        else:
            # admin sees all
            active_q = db.session.query(Booking).filter(active_filter)
            todays_q = db.session.query(Booking).filter(today_checkins_filter)
            luggage_pending_q = db.session.query(Luggage).filter(Luggage.status == "pending")

        active_stays = active_q.count()
        todays_checkins = todays_q.count()
        luggage_pending = luggage_pending_q.count()

        return render_template(
            "dashboard.html",
            user=current_user,
            active_stays=active_stays or 0,
            todays_checkins=todays_checkins or 0,
            luggage_pending=luggage_pending or 0,
        )


    return app

app = create_app()
