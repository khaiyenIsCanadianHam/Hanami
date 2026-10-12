"""Application factory for the WebDev CRM local web application."""

import os
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException
from .config import settings
from .extensions import csrf, db, limiter, login_manager, migrate


@event.listens_for(Engine, "connect")
def sqlite_foreign_keys(connection, record):
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")


def create_app(config=None):
    overrides = dict(config or {})
    instance_path = overrides.pop("INSTANCE_PATH", None)
    app = Flask(
        __name__,
        instance_relative_config=True,
        **({"instance_path": instance_path} if instance_path else {}),
    )
    app.config.from_mapping(settings())
    app.config.update(overrides)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    if (
        app.config["APP_ENV"] == "production"
        and len(app.config.get("SECRET_KEY") or "") < 32
    ):
        raise RuntimeError(
            "Production requires SECRET_KEY with at least 32 random characters."
        )
    if not app.config.get("SECRET_KEY"):
        secret_file = instance / ".secret-key"
        if not secret_file.exists():
            try:
                descriptor = os.open(
                    secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "w") as target:
                    target.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        app.config["SECRET_KEY"] = secret_file.read_text().strip()
    app.config.setdefault("UPLOAD_FOLDER", str(instance / "storage" / "uploads"))
    app.config.setdefault("BACKUP_FOLDER", str(instance / "storage" / "backups"))
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Sign in to continue."
    login_manager.session_protection = "strong"
    csrf.init_app(app)
    limiter.init_app(app)
    from . import models  # noqa: F401

    migrate.init_app(app, db)

    @login_manager.user_loader
    def load_user(user_id):
        from .models import User

        if not user_id.isdigit():
            return None
        user = db.session.get(User, int(user_id))
        if not user or not user.active:
            return None
        expected = hashlib.sha256(user.password_hash.encode()).hexdigest()
        if not hmac.compare_digest(session.get("auth_version", ""), expected):
            return None
        return user

    @app.before_request
    def validate_current_session():
        # Recheck every request, including when an enclosing application context
        # or a long-lived ORM identity map retains a previously loaded user.
        from flask_login import logout_user
        from .models import User

        user_id = session.get("_user_id")
        if not user_id:
            return
        user = (
            db.session.get(User, int(user_id), populate_existing=True)
            if str(user_id).isdigit()
            else None
        )
        valid = bool(user and user.active)
        expected = (
            hashlib.sha256(user.password_hash.encode()).hexdigest() if user else ""
        )
        if not valid or not hmac.compare_digest(
            session.get("auth_version", ""), expected
        ):
            logout_user()
            session.clear()

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify(error="Authentication required."), 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    from .blueprints import auth, crm, finance, communications, delivery, dashboard

    for module in (auth, crm, finance, communications, delivery, dashboard):
        app.register_blueprint(module.bp)

    @app.get("/")
    def index():
        return redirect(
            "/dashboard" if current_user.is_authenticated else url_for("auth.login")
        )

    @app.get("/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok")

    @app.context_processor
    def common_context():
        from .services.common import setting

        # Login and error pages can render before migrations have been applied.
        demo = False
        if current_user.is_authenticated:
            demo = setting("demo_mode", "false") == "true"
        return {"setting": setting, "demo_mode": demo}

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        if request.path != "/health" and not request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if request.is_json:
            return jsonify(
                error="The form expired. Reload the page and try again."
            ), 400
        return render_template(
            "auth/error.html",
            code=400,
            message="The form expired. Reload the page and try again.",
        ), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = error.description
        if request.is_json:
            return jsonify(error=message), error.code
        return render_template(
            "auth/error.html", code=error.code, message=message
        ), error.code

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.is_json:
            return jsonify(
                error="The operation could not be completed. Please try again."
            ), 500
        return render_template(
            "auth/error.html",
            code=500,
            message="The operation could not be completed. Please try again.",
        ), 500

    from .cli import register_commands

    register_commands(app)
    return app
