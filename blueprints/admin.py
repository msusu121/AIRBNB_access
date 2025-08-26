# blueprints/admin.py
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import asc
from models import db, User, Property, Room, Checkpoint, ROLE_ADMIN, ROLE_HOST, ROLE_GUARD

bp = Blueprint("admin", __name__, url_prefix="/admin")

# -------- Permissions helpers ----------
def _can_view():
    # Admin OR Host can view lists
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

def _host_only():
    # Only Host can create/edit/delete
    return current_user.is_authenticated and current_user.role == ROLE_HOST

def _admin_only():
    return current_user.is_authenticated and current_user.role == ROLE_ADMIN

# ---------- Properties ----------
@bp.get("/properties")
@login_required
def properties_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    props = Property.query.order_by(asc(Property.name)).all()
    owners = {u.id: u.name for u in User.query.order_by(asc(User.name)).all()}
    return render_template("admin_properties_list.html", properties=props, owners=owners)

@bp.get("/properties/new")
@login_required
def properties_new():
    if not _host_only():
        flash("Only hosts can create properties.", "error")
        return redirect(url_for("admin.properties_index"))

    owners = User.query.order_by(User.name.asc()).all()
    return render_template("admin_property_form.html", owners=owners, prop=None)

@bp.post("/properties/new")
@login_required
def properties_create():
    if not _host_only():
        flash("Only hosts can create properties.", "error")
        return redirect(url_for("admin.properties_index"))

    name = (request.form.get("name") or "").strip()
    address = (request.form.get("address") or "").strip()
    owner_id = int(request.form.get("owner_id"))
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.properties_new"))

    prop = Property(name=name, address=address, owner_id=owner_id)
    db.session.add(prop)
    db.session.commit()
    flash("Property created.", "success")
    return redirect(url_for("admin.properties_index"))

@bp.get("/properties/<int:prop_id>/edit")
@login_required
def properties_edit(prop_id):
    if not _host_only():
        flash("Only hosts can edit properties.", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    owners = User.query.order_by(User.name.asc()).all()
    return render_template("admin_property_form.html", owners=owners, prop=prop)

@bp.post("/properties/<int:prop_id>/edit")
@login_required
def properties_update(prop_id):
    if not _host_only():
        flash("Only hosts can edit properties.", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    prop.name = (request.form.get("name") or "").strip()
    prop.address = (request.form.get("address") or "").strip()
    prop.owner_id = int(request.form.get("owner_id"))
    if not prop.name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.properties_edit", prop_id=prop.id))

    db.session.commit()
    flash("Property updated.", "success")
    return redirect(url_for("admin.properties_index"))

@bp.post("/properties/<int:prop_id>/delete")
@login_required
def properties_delete(prop_id):
    if not _host_only():
        flash("Only hosts can delete properties.", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    db.session.delete(prop)
    db.session.commit()
    flash("Property deleted.", "success")
    return redirect(url_for("admin.properties_index"))


# ---------- Rooms ----------
@bp.get("/rooms")
@login_required
def rooms_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    prop_id = request.args.get("property_id", type=int)
    props = Property.query.order_by(Property.name.asc()).all()
    q = Room.query
    if prop_id:
        q = q.filter(Room.property_id == prop_id)
    rooms = q.order_by(Room.property_id.asc(), Room.name.asc()).all()
    return render_template("admin_rooms_list.html", rooms=rooms, properties=props, current_property_id=prop_id)

@bp.get("/rooms/new")
@login_required
def rooms_new():
    if not _host_only():
        flash("Only hosts can create rooms.", "error")
        return redirect(url_for("admin.rooms_index"))

    props = Property.query.order_by(Property.name.asc()).all()
    return render_template("admin_room_form.html", props=props, room=None)

@bp.post("/rooms/new")
@login_required
def rooms_create():
    if not _host_only():
        flash("Only hosts can create rooms.", "error")
        return redirect(url_for("admin.rooms_index"))

    name = (request.form.get("name") or "").strip()
    desc = (request.form.get("desc") or "").strip()
    property_id = int(request.form.get("property_id"))
    if not name:
        flash("Room name is required.", "error")
        return redirect(url_for("admin.rooms_new"))

    room = Room(name=name, desc=desc, property_id=property_id)
    db.session.add(room)
    db.session.commit()
    flash("Room created.", "success")
    return redirect(url_for("admin.rooms_index", property_id=property_id))

@bp.get("/rooms/<int:room_id>/edit")
@login_required
def rooms_edit(room_id):
    if not _host_only():
        flash("Only hosts can edit rooms.", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)
    props = Property.query.order_by(Property.name.asc()).all()
    return render_template("admin_room_form.html", props=props, room=room)

@bp.post("/rooms/<int:room_id>/edit")
@login_required
def rooms_update(room_id):
    if not _host_only():
        flash("Only hosts can edit rooms.", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)
    room.name = (request.form.get("name") or "").strip()
    room.desc = (request.form.get("desc") or "").strip()
    room.property_id = int(request.form.get("property_id"))
    if not room.name:
        flash("Room name is required.", "error")
        return redirect(url_for("admin.rooms_edit", room_id=room.id))

    db.session.commit()
    flash("Room updated.", "success")
    return redirect(url_for("admin.rooms_index", property_id=room.property_id))

@bp.post("/rooms/<int:room_id>/delete")
@login_required
def rooms_delete(room_id):
    if not _host_only():
        flash("Only hosts can delete rooms.", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)
    prop_id = room.property_id
    db.session.delete(room)
    db.session.commit()
    flash("Room deleted.", "success")
    return redirect(url_for("admin.rooms_index", property_id=prop_id))


# ---------- Checkpoints ----------
@bp.get("/checkpoints")
@login_required
def checkpoints_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    props = Property.query.order_by(Property.name.asc()).all()
    cps = Checkpoint.query.order_by(Checkpoint.property_id.asc(), Checkpoint.name.asc()).all()
    return render_template("admin_checkpoints_list.html", checkpoints=cps, properties=props)

@bp.get("/checkpoints/new")
@login_required
def checkpoints_new():
    if not _host_only():
        flash("Only hosts can create checkpoints.", "error")
        return redirect(url_for("admin.checkpoints_index"))

    props = Property.query.order_by(Property.name.asc()).all()
    return render_template("admin_checkpoint_form.html", props=props, cp=None)

@bp.post("/checkpoints/new")
@login_required
def checkpoints_create():
    if not _host_only():
        flash("Only hosts can create checkpoints.", "error")
        return redirect(url_for("admin.checkpoints_index"))

    name = (request.form.get("name") or "").strip()
    property_id = int(request.form.get("property_id"))
    if not name:
        flash("Checkpoint name is required.", "error")
        return redirect(url_for("admin.checkpoints_new"))

    cp = Checkpoint(name=name, property_id=property_id)
    db.session.add(cp)
    db.session.commit()
    flash("Checkpoint created.", "success")
    return redirect(url_for("admin.checkpoints_index"))

@bp.get("/checkpoints/<int:cp_id>/edit")
@login_required
def checkpoints_edit(cp_id):
    if not _host_only():
        flash("Only hosts can edit checkpoints.", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    props = Property.query.order_by(Property.name.asc()).all()
    return render_template("admin_checkpoint_form.html", props=props, cp=cp)

@bp.post("/checkpoints/<int:cp_id>/edit")
@login_required
def checkpoints_update(cp_id):
    if not _host_only():
        flash("Only hosts can edit checkpoints.", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    cp.name = (request.form.get("name") or "").strip()
    cp.property_id = int(request.form.get("property_id"))
    if not cp.name:
        flash("Checkpoint name is required.", "error")
        return redirect(url_for("admin.checkpoints_edit", cp_id=cp.id))

    db.session.commit()
    flash("Checkpoint updated.", "success")
    return redirect(url_for("admin.checkpoints_index"))

@bp.post("/checkpoints/<int:cp_id>/delete")
@login_required
def checkpoints_delete(cp_id):
    if not _host_only():
        flash("Only hosts can delete checkpoints.", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    db.session.delete(cp)
    db.session.commit()
    flash("Checkpoint deleted.", "success")
    return redirect(url_for("admin.checkpoints_index"))


@bp.get("/users")
@login_required
def users_index():
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    users = User.query.order_by(User.role.asc(), User.name.asc()).all()
    return render_template("admin_users_list.html", users=users)

@bp.get("/users/new")
@login_required
def users_new():
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    roles = [(ROLE_HOST, "Host"), (ROLE_GUARD, "Guard"), (ROLE_ADMIN, "Admin")]
    return render_template("admin_user_form.html", user=None, roles=roles, mode="create")

@bp.post("/users/new")
@login_required
def users_create():
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    role = (request.form.get("role") or ROLE_GUARD).strip()
    password = request.form.get("password") or ""

    if not name or not email or not password:
        flash("Name, email, password required.", "error")
        return redirect(url_for("admin.users_new"))

    if role not in (ROLE_ADMIN, ROLE_HOST, ROLE_GUARD):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.users_new"))

    if User.query.filter_by(email=email).first():
        flash("Email already exists.", "error")
        return redirect(url_for("admin.users_new"))

    u = User(name=name, email=email, role=role)
    u.set_password(password)
    db.session.add(u); db.session.commit()
    flash("User created.", "success")
    return redirect(url_for("admin.users_index"))

@bp.get("/users/<int:user_id>/edit")
@login_required
def users_edit(user_id):
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    u = User.query.get_or_404(user_id)
    roles = [(ROLE_HOST, "Host"), (ROLE_GUARD, "Guard"), (ROLE_ADMIN, "Admin")]
    return render_template("admin_user_form.html", user=u, roles=roles, mode="edit")

@bp.post("/users/<int:user_id>/edit")
@login_required
def users_update(user_id):
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    u = User.query.get_or_404(user_id)
    u.name = (request.form.get("name") or "").strip()
    u.email = (request.form.get("email") or "").strip().lower()
    role = (request.form.get("role") or u.role).strip()
    if role not in (ROLE_ADMIN, ROLE_HOST, ROLE_GUARD):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.users_edit", user_id=u.id))
    u.role = role
    new_password = request.form.get("password") or ""
    if new_password:
        u.set_password(new_password)
    db.session.commit()
    flash("User updated.", "success")
    return redirect(url_for("admin.users_index"))

@bp.post("/users/<int:user_id>/delete")
@login_required
def users_delete(user_id):
    if not _admin_only():
        flash("Unauthorized", "error"); return redirect(url_for("home"))
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("You cannot delete yourself.", "error")
        return redirect(url_for("admin.users_index"))
    db.session.delete(u); db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin.users_index"))    
