from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import db, Room, Booking, Guest, ROLE_ADMIN, ROLE_HOST
from datetime import datetime
from models import User

bp = Blueprint("auth", __name__)

@bp.get("/login")
def login_page():
    return render_template("login.html")

@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Invalid credentials", "error")
        return redirect(url_for("auth.login_page"))
    login_user(user)
    flash(f"Welcome back, {user.name}!", "success")
    return redirect(url_for("home"))

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login_page"))


# ---------- Register ADMIN ----------
# Only allowed if there are NO admins yet.
@bp.get("/register-admin")
def register_admin_page():
    if User.query.filter_by(role=ROLE_ADMIN).count() > 0:
        flash("Admin already exists. Ask an existing admin to add users.", "error")
        return redirect(url_for("auth.login_page"))
    return render_template("auth_register_admin.html")

@bp.post("/register-admin")
def register_admin_post():
    if User.query.filter_by(role=ROLE_ADMIN).count() > 0:
        flash("Admin already exists.", "error")
        return redirect(url_for("auth.login_page"))

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not name or not email or not password:
        flash("All fields are required.", "error")
        return redirect(url_for("auth.register_admin_page"))

    if User.query.filter_by(email=email).first():
        flash("Email already in use.", "error")
        return redirect(url_for("auth.register_admin_page"))

    u = User(name=name, email=email, role=ROLE_ADMIN, created_at=datetime.utcnow())
    u.set_password(password)
    db.session.add(u)
    db.session.commit()

    flash("Admin account created. You can log in now.", "success")
    return redirect(url_for("auth.login_page"))

# ---------- Register HOST ----------
# If you want *open signup* for hosts, leave this enabled.
# If you want *admin-approved only*, protect this route similarly to register-admin.
@bp.get("/register-host")
def register_host_page():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return render_template("auth_register_host.html")

@bp.post("/register-host")
def register_host_post():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not name or not email or not password:
        flash("All fields are required.", "error")
        return redirect(url_for("auth.register_host_page"))

    if User.query.filter_by(email=email).first():
        flash("Email already in use.", "error")
        return redirect(url_for("auth.register_host_page"))

    u = User(name=name, email=email, role=ROLE_HOST, created_at=datetime.utcnow())
    u.set_password(password)
    db.session.add(u)
    db.session.commit()

    flash("Host account created. You can log in now.", "success")
    return redirect(url_for("auth.login_page"))    
