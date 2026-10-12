"""Configuration contains references to secrets, never embedded credentials."""

import os
from datetime import timedelta
from dotenv import load_dotenv


def env_bool(key, default=False):
    return os.getenv(key, str(default)).strip().lower() in {"true", "1", "yes", "on"}


def settings():
    load_dotenv()
    production = os.getenv("APP_ENV", "development") == "production"
    return {
        "APP_ENV": os.getenv("APP_ENV", "development"),
        "SECRET_KEY": os.getenv("SECRET_KEY") or None,
        "SQLALCHEMY_DATABASE_URI": os.getenv(
            "DATABASE_URL", "sqlite:///webdev_crm.sqlite3"
        ),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True, "hide_parameters": True},
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": env_bool("SESSION_COOKIE_SECURE", production),
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SAMESITE": "Lax",
        "REMEMBER_COOKIE_SECURE": env_bool("SESSION_COOKIE_SECURE", production),
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "WTF_CSRF_TIME_LIMIT": 8 * 60 * 60,
        "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,
        "BUSINESS_TIMEZONE": os.getenv("BUSINESS_TIMEZONE", "Asia/Manila"),
        "DEFAULT_CURRENCY": os.getenv("DEFAULT_CURRENCY", "PHP"),
        "EMAIL_TEST_MODE": env_bool("EMAIL_TEST_MODE", True),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", "465")),
        "SMTP_USER": os.getenv("SMTP_USER", ""),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
        "SMTP_REPLY_TO": os.getenv("SMTP_REPLY_TO", ""),
        "SMTP_SENDER_NAME": os.getenv("SMTP_SENDER_NAME", "Hanami"),
        "AUTOMATIONS_PAUSED": env_bool("AUTOMATIONS_PAUSED", False),
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        "RATELIMIT_HEADERS_ENABLED": True,
        "PREFERRED_URL_SCHEME": "https" if production else "http",
    }
