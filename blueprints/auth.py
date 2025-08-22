from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
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
