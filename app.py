from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager, current_user
from config import Config
from models import db, User
from blueprints.auth import bp as auth_bp
from blueprints.bookings import bp as bookings_bp
from blueprints.guard import bp as guard_bp
from blueprints.admin import bp as admin_bp

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

    @app.get("/")
    def home():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login_page"))
        return render_template("dashboard.html", user=current_user)

    return app

app = create_app()
