"""Exercise administrator recovery workflows against disposable databases."""

import json
from pathlib import Path
import zipfile

import pytest

from app import create_app
from app.extensions import db
from app.models import Client, User


@pytest.fixture
def disk_app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "local-cli-test-secret",
            "APP_ENV": "development",
            "INSTANCE_PATH": str(tmp_path / "instance"),
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'crm.sqlite3'}",
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "BACKUP_FOLDER": str(tmp_path / "backups"),
            "RATELIMIT_ENABLED": False,
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.engine.dispose()


def test_backup_restores_database_and_uploads(disk_app, tmp_path):
    db.session.add(Client(name="Original client"))
    db.session.commit()
    upload = Path(disk_app.config["UPLOAD_FOLDER"]) / "evidence.txt"
    upload.write_text("Original evidence")
    runner = disk_app.test_cli_runner()
    archive = tmp_path / "backup.zip"
    result = runner.invoke(args=["backup", "--output", str(archive)])
    assert result.exit_code == 0, result.output
    db.session.add(Client(name="Later client"))
    db.session.commit()
    upload.write_text("Later evidence")
    result = runner.invoke(args=["restore", str(archive), "--yes"])
    assert result.exit_code == 0, result.output
    assert [client.name for client in Client.query.all()] == ["Original client"]
    assert upload.read_text() == "Original evidence"
    assert list((tmp_path / "backups").glob("before-restore-*.zip"))


def test_restore_rejects_tampered_archive_without_touching_data(disk_app, tmp_path):
    db.session.add(Client(name="Preserve me"))
    db.session.commit()
    archive = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr(
            "manifest.json",
            json.dumps({"format": 1, "files": {"database.sqlite3": "wrong"}}),
        )
        target.writestr("database.sqlite3", "not a database")
    result = disk_app.test_cli_runner().invoke(args=["restore", str(archive), "--yes"])
    assert result.exit_code != 0
    assert "checksum" in result.output
    assert Client.query.one().name == "Preserve me"


def test_export_excludes_user_credentials_and_settings(disk_app, tmp_path):
    user = User(email="admin@example.com", name="Administrator")
    user.set_password("test-only-password-1234")
    db.session.add_all([user, Client(name="Exported client")])
    db.session.commit()
    destination = tmp_path / "business.json"
    result = disk_app.test_cli_runner().invoke(
        args=["export-data", "--output", str(destination)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(destination.read_text())
    assert data["records"]["client"][0]["name"] == "Exported client"
    assert "user" not in data["records"]
    assert "application_setting" not in data["records"]
    assert user.password_hash not in destination.read_text()


def test_seed_cannot_mix_demonstration_with_business_records(disk_app):
    db.session.add(Client(name="Real business record"))
    db.session.commit()
    result = disk_app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code != 0
    assert "empty business database" in result.output
    assert Client.query.count() == 1


def test_create_admin_requires_strong_password_and_preserves_existing(
    disk_app, monkeypatch
):
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    runner = disk_app.test_cli_runner()
    options = ["create-admin", "--email", "owner@example.com", "--name", "Owner"]
    result = runner.invoke(args=options)
    assert result.exit_code != 0
    assert User.query.count() == 0
    monkeypatch.setenv("ADMIN_PASSWORD", "valid-long-passphrase-1234")
    assert runner.invoke(args=options).exit_code == 0
    assert runner.invoke(args=options).exit_code != 0
    assert User.query.count() == 1


def test_demo_seed_is_repeatable_and_requires_development(disk_app):
    from app.models import EmailDraft, Invoice, Project

    administrator = User(email="admin@example.com", name="Demo administrator")
    administrator.set_password("test-only-password-1234")
    db.session.add(administrator)
    db.session.commit()
    runner = disk_app.test_cli_runner()
    seeded = runner.invoke(args=["seed-demo"])
    assert seeded.exit_code == 0, seeded.output
    before = (
        Client.query.count(),
        Project.query.count(),
        Invoice.query.count(),
        EmailDraft.query.count(),
    )
    assert before == (3, 3, 3, 2)
    assert runner.invoke(args=["seed-demo"]).exit_code == 0
    assert before == (
        Client.query.count(),
        Project.query.count(),
        Invoice.query.count(),
        EmailDraft.query.count(),
    )
    disk_app.config["APP_ENV"] = "production"
    rejected = runner.invoke(args=["seed-demo"])
    assert rejected.exit_code != 0
    assert "development" in rejected.output


def test_anonymization_requires_archival_age_and_preserves_history(disk_app):
    from datetime import timedelta
    from app.models import ActivityLog, Contact
    from app.models.base import utcnow

    person = Client(
        name="Fictional person", email="person@example.com", status="active"
    )
    db.session.add(person)
    db.session.flush()
    db.session.add_all(
        [
            Contact(
                client_id=person.id, name="Other contact", email="other@example.com"
            ),
            ActivityLog(
                client_id=person.id,
                action="created",
                description="Historical business record",
            ),
        ]
    )
    db.session.commit()
    runner = disk_app.test_cli_runner()
    args = ["anonymize-client", str(person.id), "--yes"]
    assert runner.invoke(args=args).exit_code != 0
    person.status = "archived"
    db.session.commit()
    assert runner.invoke(args=args).exit_code != 0
    person.updated_at = utcnow() - timedelta(days=400)
    db.session.commit()
    result = runner.invoke(args=args)
    assert result.exit_code == 0, result.output
    assert person.email == ""
    assert Contact.query.one().email == ""
    assert ActivityLog.query.one().description == "Historical business record"


def test_account_offboarding_retains_last_admin_and_password_reset(
    disk_app, monkeypatch
):
    from app.models import AuditLog

    owner = User(email="owner@example.com", name="Owner")
    owner.set_password("original-owner-password-1234")
    db.session.add(owner)
    db.session.commit()
    runner = disk_app.test_cli_runner()
    disable = ["set-user-active", "--email", owner.email, "--inactive"]
    assert runner.invoke(args=disable).exit_code != 0
    assert owner.active
    other = User(email="other@example.com", name="Other administrator")
    other.set_password("other-original-password-1234")
    db.session.add(other)
    db.session.commit()
    assert runner.invoke(args=disable).exit_code == 0
    assert not owner.active
    monkeypatch.setenv("ADMIN_PASSWORD", "replacement-long-password-1234")
    assert runner.invoke(args=["reset-password", "--email", owner.email]).exit_code == 0
    assert owner.check_password("replacement-long-password-1234")
    assert not owner.check_password("original-owner-password-1234")
    assert AuditLog.query.filter_by(entity_id=owner.id).count() == 2


def test_password_reset_revokes_existing_web_session(
    app, auth_client, admin, monkeypatch
):
    assert auth_client.get("/clients").status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD", "replacement-secure-password-1234")
    result = app.test_cli_runner().invoke(
        args=["reset-password", "--email", admin.email]
    )
    assert result.exit_code == 0, result.output
    response = auth_client.get("/clients")
    assert response.status_code == 302
    assert "/login" in response.location
