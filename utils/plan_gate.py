# utils/plan_gate.py
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

# Usage:
# @require_plan('premium')                      -> only premium (e.g., luggage scanner)
# @require_plan(any_of={'basic', 'premium'})    -> any paid plan (e.g., create booking)
def require_plan(required: str | None = None, any_of: set[str] | list[str] | None = None):
    if not required and not any_of:
        # default to premium if nothing specified
        required = "premium"

    # normalize any_of to a set
    allowed_set = set(any_of) if any_of else ( {required} if required else set() )

    def _wrap(f):
        @wraps(f)
        def _inner(*args, **kwargs):
            # must be logged in
            if not current_user.is_authenticated:
                flash("Please login.", "error")
                return redirect(url_for("auth.login_page"))

            # admin bypass
            if getattr(current_user, "role", "") == "admin":
                return f(*args, **kwargs)

            # fetch user's plan (default to 'FREE' if missing)
            user_plan = (getattr(current_user, "plan", None) or "FREE").upper()
            allowed_upper = {p.upper() for p in allowed_set}

            if user_plan not in allowed_upper:
                # choose a friendly message
                if "PREMIUM" in allowed_upper and allowed_upper == {"PREMIUM"}:
                    flash("Upgrade to Premium to use this feature.", "error")
                elif allowed_upper:
                    # generic “upgrade” when multiple plans allowed and user is FREE
                    if user_plan == "FREE":
                        flash("Upgrade your plan to use this feature.", "error")
                    else:
                        flash("Your current plan doesn’t include this feature.", "error")
                else:
                    flash("Your plan doesn’t allow this action.", "error")
                return redirect(url_for("billing.pricing"))

            return f(*args, **kwargs)
        return _inner
    return _wrap


# Convenience: require any paid plan (BASIC or PREMIUM)
def require_paid():
    return require_plan(any_of={"basic", "premium"})
