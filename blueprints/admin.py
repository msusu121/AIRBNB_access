# blueprints/admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import asc
from sqlalchemy import or_
from models import (
    db, User, Property, Room, Checkpoint,
    ROLE_ADMIN, ROLE_HOST, ROLE_GUARD
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- Role helpers ----------
def _is_admin():
    return current_user.is_authenticated and current_user.role == ROLE_ADMIN

def _is_host():
    return current_user.is_authenticated and current_user.role == ROLE_HOST

def _can_view():
    # Admin OR Host can view lists
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)

def _can_manage():
    # Admin or Host can create/edit/delete (with host scoped to own data)
    return current_user.is_authenticated and current_user.role in (ROLE_ADMIN, ROLE_HOST)


# ========== PROPERTIES ==========
@bp.get("/properties")
@login_required
def properties_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    if _is_admin():
        props = Property.query.order_by(asc(Property.name)).all()
        owners = {u.id: u.name for u in User.query.order_by(asc(User.name)).all()}
    else:
        props = Property.query.filter(Property.owner_id == current_user.id)\
                              .order_by(asc(Property.name)).all()
        owners = {current_user.id: current_user.name}

    return render_template("admin_properties_list.html", properties=props, owners=owners)


@bp.get("/properties/new")
@login_required
def properties_new():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    if _is_admin():
        # Show hosts to assign ownership (you can include admins if you want)
        owners = User.query.filter(User.role == ROLE_HOST).order_by(User.name.asc()).all()
    else:
        owners = [current_user]

    return render_template("admin_property_form.html", owners=owners, prop=None)


@bp.post("/properties/new")
@login_required
def properties_create():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    name = (request.form.get("name") or "").strip()
    address = (request.form.get("address") or "").strip()

    if _is_admin():
        owner_id = int(request.form.get("owner_id", 0) or 0)
        owner = User.query.get(owner_id)
        if not owner or owner.role not in (ROLE_HOST, ROLE_ADMIN):
            flash("Select a valid owner.", "error")
            return redirect(url_for("admin.properties_new"))
    else:
        owner_id = current_user.id

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
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    if _is_admin():
        owners = User.query.filter(User.role == ROLE_HOST).order_by(User.name.asc()).all()
    else:
        owners = [current_user]

    return render_template("admin_property_form.html", owners=owners, prop=prop)


@bp.post("/properties/<int:prop_id>/edit")
@login_required
def properties_update(prop_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    prop.name = (request.form.get("name") or "").strip()
    prop.address = (request.form.get("address") or "").strip()

    if _is_admin():
        try:
            new_owner_id = int(request.form.get("owner_id", prop.owner_id) or prop.owner_id)
        except ValueError:
            new_owner_id = prop.owner_id
        owner = User.query.get(new_owner_id)
        if owner and owner.role in (ROLE_HOST, ROLE_ADMIN):
            prop.owner_id = new_owner_id
    else:
        # Host may not reassign ownership
        prop.owner_id = current_user.id

    if not prop.name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.properties_edit", prop_id=prop.id))

    db.session.commit()
    flash("Property updated.", "success")
    return redirect(url_for("admin.properties_index"))


@bp.post("/properties/<int:prop_id>/delete")
@login_required
def properties_delete(prop_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    prop = Property.query.get_or_404(prop_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.properties_index"))

    db.session.delete(prop)
    db.session.commit()
    flash("Property deleted.", "success")
    return redirect(url_for("admin.properties_index"))


# ========== ROOMS (Property optional) ==========
@bp.get("/rooms")
@login_required
def rooms_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    # optional legacy filter (safe even if your UI doesn't show it)
    prop_id = request.args.get("property_id", type=int)

    # OUTER JOIN so rooms with property_id == NULL are included
    q = db.session.query(Room).outerjoin(Property, Property.id == Room.property_id)

    if _is_admin():
        # Admin sees everything; optional filter by property if provided
        if prop_id:
            q = q.filter(Room.property_id == prop_id)
    else:
        # Host: see (a) rooms in their properties OR (b) rooms with no property
        q = q.filter(
            or_(
                Property.owner_id == current_user.id,   # rooms under host’s properties
                Room.property_id.is_(None)              # property-less rooms (include them!)
            )
        )
        if prop_id:
            q = q.filter(Room.property_id == prop_id)

    rooms = q.order_by(Room.id.desc()).all()

    # If your template no longer needs properties, passing [] is fine
    return render_template(
        "admin_rooms_list.html",
        rooms=rooms,
        properties=[],              # keeps old templates happy
        current_property_id=prop_id
    )

@bp.get("/rooms/new")
@login_required
def rooms_new():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.rooms_index"))
    # No property selection needed
    return render_template("admin_room_form.html", room=None)


@bp.post("/rooms/new")
@login_required
def rooms_create():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.rooms_index"))

    name = (request.form.get("name") or "").strip()
    desc = (request.form.get("desc") or "").strip()

    if not name:
        flash("Room name is required.", "error")
        return redirect(url_for("admin.rooms_new"))

    # Property is optional now; if you later add a UI to attach, handle it there.
    room = Room(name=name, desc=desc, property_id=None)
    db.session.add(room)
    db.session.commit()
    flash("Room created.", "success")
    return redirect(url_for("admin.rooms_index"))


@bp.get("/rooms/<int:room_id>/edit")
@login_required
def rooms_edit(room_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)

    # If room is attached to a property, enforce host ownership
    if _is_host() and room.property_id:
        prop = Property.query.get(room.property_id)
        if not prop or prop.owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("admin.rooms_index"))

    return render_template("admin_room_form.html", room=room)


@bp.post("/rooms/<int:room_id>/edit")
@login_required
def rooms_update(room_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)

    # If attached, enforce host ownership
    if _is_host() and room.property_id:
        prop = Property.query.get(room.property_id)
        if not prop or prop.owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("admin.rooms_index"))

    room.name = (request.form.get("name") or "").strip()
    room.desc = (request.form.get("desc") or "").strip()

    if not room.name:
        flash("Room name is required.", "error")
        return redirect(url_for("admin.rooms_edit", room_id=room.id))

    db.session.commit()
    flash("Room updated.", "success")
    return redirect(url_for("admin.rooms_index"))


@bp.post("/rooms/<int:room_id>/delete")
@login_required
def rooms_delete(room_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.rooms_index"))

    room = Room.query.get_or_404(room_id)

    # If attached, enforce host ownership
    if _is_host() and room.property_id:
        prop = Property.query.get(room.property_id)
        if not prop or prop.owner_id != current_user.id:
            flash("Unauthorized", "error")
            return redirect(url_for("admin.rooms_index"))

    db.session.delete(room)
    db.session.commit()
    flash("Room deleted.", "success")
    return redirect(url_for("admin.rooms_index"))



# ========== CHECKPOINTS ==========
@bp.get("/checkpoints")
@login_required
def checkpoints_index():
    if not _can_view():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    if _is_admin():
        props = Property.query.order_by(Property.name.asc()).all()
        cps = Checkpoint.query.order_by(Checkpoint.property_id.asc(), Checkpoint.name.asc()).all()
    else:
        props = Property.query.filter(Property.owner_id == current_user.id)\
                              .order_by(Property.name.asc()).all()
        cps = (Checkpoint.query.join(Property, Property.id == Checkpoint.property_id)
               .filter(Property.owner_id == current_user.id)
               .order_by(Checkpoint.property_id.asc(), Checkpoint.name.asc())
               .all())

    return render_template("admin_checkpoints_list.html", checkpoints=cps, properties=props)


@bp.get("/checkpoints/new")
@login_required
def checkpoints_new():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    if _is_admin():
        props = Property.query.order_by(Property.name.asc()).all()
    else:
        props = Property.query.filter(Property.owner_id == current_user.id)\
                              .order_by(Property.name.asc()).all()
        if not props:
            flash("Create a property first.", "error")
            return redirect(url_for("admin.properties_new"))

    return render_template("admin_checkpoint_form.html", props=props, cp=None)


@bp.post("/checkpoints/new")
@login_required
def checkpoints_create():
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    name = (request.form.get("name") or "").strip()
    try:
        property_id = int(request.form.get("property_id", 0) or 0)
    except ValueError:
        property_id = 0

    if not name:
        flash("Checkpoint name is required.", "error")
        return redirect(url_for("admin.checkpoints_new"))

    prop = Property.query.get_or_404(property_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized property selection.", "error")
        return redirect(url_for("admin.checkpoints_new"))

    cp = Checkpoint(name=name, property_id=property_id)
    db.session.add(cp)
    db.session.commit()
    flash("Checkpoint created.", "success")
    return redirect(url_for("admin.checkpoints_index"))


@bp.get("/checkpoints/<int:cp_id>/edit")
@login_required
def checkpoints_edit(cp_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    prop = Property.query.get(cp.property_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    if _is_admin():
        props = Property.query.order_by(Property.name.asc()).all()
    else:
        props = Property.query.filter(Property.owner_id == current_user.id)\
                              .order_by(Property.name.asc()).all()

    return render_template("admin_checkpoint_form.html", props=props, cp=cp)


@bp.post("/checkpoints/<int:cp_id>/edit")
@login_required
def checkpoints_update(cp_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    current_prop = Property.query.get(cp.property_id)
    if _is_host() and current_prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp.name = (request.form.get("name") or "").strip()

    try:
        new_prop_id = int(request.form.get("property_id", cp.property_id) or cp.property_id)
    except ValueError:
        new_prop_id = cp.property_id

    new_prop = Property.query.get(new_prop_id)
    if not new_prop:
        flash("Invalid property.", "error")
        return redirect(url_for("admin.checkpoints_edit", cp_id=cp.id))

    if _is_host() and new_prop.owner_id != current_user.id:
        flash("Unauthorized property selection.", "error")
        return redirect(url_for("admin.checkpoints_edit", cp_id=cp.id))

    cp.property_id = new_prop_id

    if not cp.name:
        flash("Checkpoint name is required.", "error")
        return redirect(url_for("admin.checkpoints_edit", cp_id=cp.id))

    db.session.commit()
    flash("Checkpoint updated.", "success")
    return redirect(url_for("admin.checkpoints_index"))


@bp.post("/checkpoints/<int:cp_id>/delete")
@login_required
def checkpoints_delete(cp_id):
    if not _can_manage():
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    cp = Checkpoint.query.get_or_404(cp_id)
    prop = Property.query.get(cp.property_id)
    if _is_host() and prop.owner_id != current_user.id:
        flash("Unauthorized", "error")
        return redirect(url_for("admin.checkpoints_index"))

    db.session.delete(cp)
    db.session.commit()
    flash("Checkpoint deleted.", "success")
    return redirect(url_for("admin.checkpoints_index"))


# ========== USERS (Admin only) ==========
@bp.get("/users")
@login_required
def users_index():
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    users = User.query.order_by(User.role.asc(), User.name.asc()).all()
    return render_template("admin_users_list.html", users=users)


@bp.get("/users/new")
@login_required
def users_new():
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    roles = [(ROLE_HOST, "Host"), (ROLE_GUARD, "Guard"), (ROLE_ADMIN, "Admin")]
    return render_template("admin_user_form.html", user=None, roles=roles, mode="create")


@bp.post("/users/new")
@login_required
def users_create():
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

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
    db.session.add(u)
    db.session.commit()
    flash("User created.", "success")
    return redirect(url_for("admin.users_index"))


@bp.get("/users/<int:user_id>/edit")
@login_required
def users_edit(user_id):
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))
    u = User.query.get_or_404(user_id)
    roles = [(ROLE_HOST, "Host"), (ROLE_GUARD, "Guard"), (ROLE_ADMIN, "Admin")]
    return render_template("admin_user_form.html", user=u, roles=roles, mode="edit")


@bp.post("/users/<int:user_id>/edit")
@login_required
def users_update(user_id):
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

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
    if not _is_admin():
        flash("Unauthorized", "error")
        return redirect(url_for("home"))

    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("You cannot delete yourself.", "error")
        return redirect(url_for("admin.users_index"))

    db.session.delete(u)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("admin.users_index"))
