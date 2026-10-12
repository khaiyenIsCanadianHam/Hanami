"""Secure administrator sessions, with no registration or default password."""

import hashlib
from urllib.parse import urlsplit
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db, limiter
from app.models import User
from app.services.common import audit

bp = Blueprint("auth", __name__)
_DUMMY_HASH = generate_password_hash(
    "unusable-timing-equalization-password", method="scrypt"
)


class LoginForm(FlaskForm):
    email = StringField(
        "Email address", validators=[DataRequired(), Email(), Length(max=254)]
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(max=256)])


def safe_next(value):
    parsed = urlsplit(value or "")
    if (
        not parsed.scheme
        and not parsed.netloc
        and value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
    ):
        return value
    return "/dashboard"


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute; 30 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/dashboard")
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(db.select(User).where(User.email == email))
        valid = check_password_hash(
            user.password_hash if user else _DUMMY_HASH, form.password.data
        )
        if user and valid and user.active and user.role == "admin":
            session.clear()
            login_user(user, remember=False)
            session["auth_version"] = hashlib.sha256(
                user.password_hash.encode()
            ).hexdigest()
            session.permanent = True
            audit("login", "user", user.id, "Administrator signed in.")
            db.session.commit()
            return redirect(safe_next(request.args.get("next", "")))
        flash(
            "Email or password is incorrect, or this account is unavailable.", "error"
        )
        return render_template("auth/login.html", form=form), 401
    return render_template(
        "auth/login.html", form=form
    ), 400 if request.method == "POST" else 200


@bp.post("/logout")
@login_required
def logout():
    audit("logout", "user", current_user.id, "Administrator signed out.")
    db.session.commit()
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))
