"""Isolated application fixtures. All external mail is disabled in tests."""

import pytest

from app import create_app
from app.extensions import db
from app.models import User

TEST_PASSWORD = "fictional-test-password-2026"


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "SECRET_KEY": "test-only-secret-never-use-in-production",
            "INSTANCE_PATH": str(tmp_path / "instance"),
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "EMAIL_TEST_MODE": True,
            "RATELIMIT_ENABLED": False,
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.engine.dispose()  # A fresh in-memory engine is created for each test.


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    user = User(
        email="admin@example.com", name="Test administrator", role="admin", active=True
    )
    user.set_password(TEST_PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def auth_client(client, admin):
    response = client.post(
        "/login", data={"email": admin.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    return client
