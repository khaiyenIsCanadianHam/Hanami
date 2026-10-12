"""Adversarial checks for sessions, authorization, uploads, and templates."""

from io import BytesIO

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app import create_app
from app.extensions import db
from app.models import Approval, Client, Project
from app.services.document_service import (
    attachment_path,
    render_literal,
    save_attachment,
)

PASSWORD = "fictional-test-password-2026"


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/clients",
        "/leads",
        "/projects",
        "/invoices",
        "/documents",
        "/email",
        "/settings",
    ],
)
def test_administrator_pages_require_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.location


def test_login_hashes_password_and_rejects_invalid_credentials(client, admin):
    assert admin.password_hash != PASSWORD
    assert admin.password_hash.startswith("scrypt:")
    response = client.post(
        "/login", data={"email": admin.email, "password": "incorrect-password"}
    )
    assert response.status_code == 401
    assert client.get("/clients").status_code == 302
    response = client.post("/login", data={"email": admin.email, "password": PASSWORD})
    assert response.status_code == 302
    assert client.get("/clients").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/clients").status_code == 302


@pytest.mark.parametrize(
    "target",
    [
        "https://attacker.example/",
        "//attacker.example/",
        "/\\attacker.example/",
        "javascript:alert(1)",
    ],
)
def test_login_next_cannot_redirect_offsite(client, admin, target):
    response = client.post(
        "/login",
        query_string={"next": target},
        data={"email": admin.email, "password": PASSWORD},
    )
    assert response.status_code == 302
    assert response.location == "/dashboard"


def test_disabled_and_nonadmin_accounts_cannot_login(client, admin):
    admin.active = False
    db.session.commit()
    assert (
        client.post(
            "/login", data={"email": admin.email, "password": PASSWORD}
        ).status_code
        == 401
    )
    admin.active, admin.role = True, "viewer"
    db.session.commit()
    assert (
        client.post(
            "/login", data={"email": admin.email, "password": PASSWORD}
        ).status_code
        == 401
    )


def test_role_revocation_blocks_an_existing_session(auth_client, admin):
    admin.role = "viewer"
    db.session.commit()
    assert auth_client.get("/clients").status_code == 403


def test_csrf_rejects_login_and_authenticated_mutations(app, client, admin):
    app.config["WTF_CSRF_ENABLED"] = True
    assert (
        client.post(
            "/login", data={"email": admin.email, "password": PASSWORD}
        ).status_code
        == 400
    )
    app.config["WTF_CSRF_ENABLED"] = False
    client.post("/login", data={"email": admin.email, "password": PASSWORD})
    app.config["WTF_CSRF_ENABLED"] = True
    assert (
        client.post("/clients/new", data={"name": "Untrusted form"}).status_code == 400
    )
    assert (
        client.post("/clients/new", json={"name": "Untrusted JSON"}).status_code == 400
    )
    assert Client.query.count() == 0


def test_security_headers_and_session_cookie(client, admin):
    response = client.post("/login", data={"email": admin.email, "password": PASSWORD})
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_client_data_escapes_html(auth_client):
    malicious = '<script>alert("stored-xss")</script>'
    row = Client(name=malicious, business_name="Example", email="fiction@example.com")
    db.session.add(row)
    db.session.commit()
    response = auth_client.get(f"/clients/{row.id}")
    assert response.status_code == 200
    assert malicious.encode() not in response.data
    assert b"&lt;script&gt;" in response.data


def test_foreign_keys_are_enforced(app):
    db.session.add(Project(client_id=99999, title="Orphan record"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize(
    "payload",
    [
        "{{7*7}}",
        "{{config}}",
        "{% for x in [] %}x{% endfor %}",
        "{{client_name.__class__}}",
    ],
)
def test_document_templates_reject_expressions(app, payload):
    with pytest.raises(ValueError):
        render_literal(payload, {})


def test_literal_template_html_escapes_values(app):
    assert (
        render_literal(
            "Hello {{client_name}}",
            {"client_name": "<script>bad()</script>"},
            html=True,
        )
        == "Hello &lt;script&gt;bad()&lt;/script&gt;"
    )


@pytest.mark.parametrize(
    "filename,content",
    [
        ("script.html", b"<script>alert(1)</script>"),
        ("fake.pdf", b"This is not a PDF"),
        ("fake.png", b"not a picture"),
        ("binary.txt", b"hello\x00world"),
        ("empty.txt", b""),
    ],
)
def test_uploads_reject_unsafe_or_mismatched_content(app, filename, content):
    with pytest.raises(ValueError):
        save_attachment(
            FileStorage(
                stream=BytesIO(content),
                filename=filename,
                content_type="application/pdf",
            )
        )


def test_upload_storage_randomizes_name_and_blocks_traversal(app, admin):
    attachment = save_attachment(
        FileStorage(
            stream=BytesIO(b"Fictional handover notes"), filename="../../handover.txt"
        ),
        uploaded_by=admin.id,
    )
    db.session.commit()
    assert attachment.original_name == "handover.txt"
    assert attachment.stored_name != attachment.original_name
    assert attachment_path(attachment).read_bytes() == b"Fictional handover notes"
    attachment.stored_name = "../outside.txt"
    with pytest.raises(ValueError):
        attachment_path(attachment)
    db.session.rollback()


def test_approval_evidence_is_immutable(app, admin):
    person = Client(name="Fictional client")
    db.session.add(person)
    db.session.flush()
    project = Project(client_id=person.id, title="Fictional site")
    db.session.add(project)
    db.session.flush()
    record = Approval(
        project_id=project.id,
        stage_number=1,
        kind="stage",
        decision="approved",
        person=person.name,
        evidence="Fictional written decision",
        actor_id=admin.id,
    )
    db.session.add(record)
    db.session.commit()
    record.evidence = "Overwritten evidence"
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()


def test_production_requires_an_explicit_strong_secret(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "",
                "INSTANCE_PATH": str(tmp_path / "production"),
            }
        )


def test_private_attachment_download_requires_an_administrator(
    app, client, auth_client, admin
):
    attachment = save_attachment(
        FileStorage(
            stream=BytesIO(b"Private fictional document"), filename="notes.txt"
        ),
        uploaded_by=admin.id,
    )
    db.session.commit()
    response = auth_client.get(f"/files/{attachment.id}/download")
    assert response.status_code == 200
    assert response.data == b"Private fictional document"
    assert "attachment" in response.headers["Content-Disposition"]
    auth_client.post("/logout")
    assert client.get(f"/files/{attachment.id}/download").status_code == 302


def test_login_attempts_are_rate_limited(tmp_path):
    limited_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "rate-limit-test-only-secret",
            "APP_ENV": "development",
            "INSTANCE_PATH": str(tmp_path / "rate-limited"),
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "EMAIL_TEST_MODE": True,
            "RATELIMIT_ENABLED": True,
            "RATELIMIT_STORAGE_URI": "memory://",
        }
    )
    with limited_app.app_context():
        db.create_all()
        web = limited_app.test_client()
        responses = [
            web.post(
                "/login",
                data={"email": "missing@example.com", "password": "invalid-password"},
            )
            for _ in range(6)
        ]
        assert responses[0].status_code == 401
        assert responses[-1].status_code == 429
        db.session.remove()
        db.engine.dispose()


def test_valid_csrf_token_allows_real_login(app, client, admin):
    import re

    app.config["WTF_CSRF_ENABLED"] = True
    response = client.get("/login")
    token = re.search(
        r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True)
    )
    assert token is not None
    response = client.post(
        "/login",
        data={"email": admin.email, "password": PASSWORD, "csrf_token": token.group(1)},
    )
    assert response.status_code == 302
    assert response.location == "/dashboard"
