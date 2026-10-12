from datetime import timedelta
from io import BytesIO
import smtplib
from unittest.mock import Mock

import pytest

from app.extensions import db
from app.models import (
    ApplicationSetting,
    Client,
    Document,
    DocumentTemplate,
    EmailAutomationRule,
    EmailDraft,
    EmailMessage,
    EmailQueue,
    EmailTemplate,
    FileAttachment,
    Task,
)
from app.models.base import utcnow
from app.services.automation_service import run_due_jobs, schedule_job, trigger_event
from app.services.document_service import (
    generate_document,
    render_literal,
    seed_templates,
    validate_template,
)
from app.services.email_service import (
    approve_email,
    draft_email,
    prepare_email,
    process_email_queue,
)
from app.services.lifecycle_service import create_project


def project_fixture():
    client = Client(
        name="Luna Owner", business_name="Luna Coffee", email="luna@example.com"
    )
    db.session.add(client)
    db.session.flush()
    project = create_project(client, "Luna website")
    seed_templates()
    db.session.commit()
    return project


def queued_email():
    draft = draft_email(
        "fictional@example.com", "Approved update", "Fictional project update"
    )
    db.session.flush()
    queue = approve_email(draft)
    db.session.commit()
    return draft, queue


def live_config(app):
    app.config.update(
        EMAIL_TEST_MODE=False, SMTP_USER="sender@example.com", SMTP_PASSWORD="mock-only"
    )
    db.session.add(ApplicationSetting(key="email_test_mode", value="false"))
    db.session.commit()


def test_literal_template_safety_and_missing_values(app):
    assert (
        render_literal("Hello {{client_name}}", {"client_name": "<script>x</script>"})
        == "Hello <script>x</script>"
    )
    assert (
        render_literal("{{client_name}}", {"client_name": "<b>Luna</b>"}, html=True)
        == "&lt;b&gt;Luna&lt;/b&gt;"
    )
    assert render_literal("{{invoice_amount}}", {}) == "[missing:invoice_amount]"
    for unsafe in [
        "{{ 7*7 }}",
        "{{config}}",
        "{% include 'secret' %}",
        "{{client_name.__class__}}",
    ]:
        with pytest.raises(ValueError):
            validate_template(unsafe)


def test_template_versioning_and_seed_is_idempotent(auth_client):
    seed_templates()
    db.session.commit()
    before = EmailTemplate.query.count()
    seed_templates()
    db.session.commit()
    assert EmailTemplate.query.count() == before
    original = EmailTemplate.query.filter_by(key="introduction").one()
    original_body = original.body
    response = auth_client.post(
        f"/email/templates/{original.id}/edit",
        data={
            "name": "Updated introduction",
            "category": "Sales",
            "subject": "Hello {{client_name}}",
            "body": "Dear {{client_name}}",
        },
    )
    assert response.status_code == 302
    revised = EmailTemplate.query.filter_by(key=original.key, version=2).one()
    assert original.archived and original.body == original_body and not revised.archived
    assert (
        auth_client.post(
            f"/email/templates/{original.id}/edit",
            data={"name": "Unsafe", "subject": "Bad", "body": "{{config}}"},
        ).status_code
        == 400
    )


def test_generated_email_requires_review_and_queue_is_idempotent(app):
    project = project_fixture()
    draft = prepare_email(project, "onboarding", event_key="onboarding:first")
    db.session.commit()
    assert "Luna Owner" in draft.body and draft.status == "draft"
    assert EmailQueue.query.count() == 0
    assert (
        prepare_email(project, "onboarding", event_key="onboarding:first").id
        == draft.id
    )
    queue = approve_email(draft)
    db.session.commit()
    assert approve_email(draft).id == queue.id
    process_email_queue()
    process_email_queue()
    assert queue.status == "test_sent" and queue.attempts == 1
    assert EmailMessage.query.filter_by(draft_id=draft.id).count() == 1
    assert queue.sent_at is None


def test_suppression_missing_values_and_approval_confirmation(auth_client):
    draft = draft_email("test@example.com", "Subject", "[missing:client_name]")
    db.session.commit()
    assert (
        auth_client.post(
            f"/email/{draft.id}/approve", data={"confirm": "yes"}
        ).status_code
        == 400
    )
    draft.body = "Ready"
    db.session.commit()
    assert auth_client.post(f"/email/{draft.id}/approve", data={}).status_code == 400
    assert (
        auth_client.post(
            "/email/suppression", data={"addresses": "test@example.com"}
        ).status_code
        == 302
    )
    assert (
        auth_client.post(
            f"/email/{draft.id}/approve", data={"confirm": "yes"}
        ).status_code
        == 400
    )
    assert EmailQueue.query.count() == 0


def test_paused_and_future_queue_wait(app):
    draft, queue = queued_email()
    app.config["AUTOMATIONS_PAUSED"] = True
    assert process_email_queue()["paused"]
    assert queue.attempts == 0
    app.config["AUTOMATIONS_PAUSED"] = False
    queue.next_attempt_at = utcnow() + timedelta(days=1)
    db.session.commit()
    assert process_email_queue()["processed"] == 0


def test_mocked_smtp_submission_and_tls_verification(app, monkeypatch):
    live_config(app)
    smtp = Mock()
    constructor = Mock(return_value=smtp)
    monkeypatch.setattr("yagmail.SMTP", constructor)
    draft, queue = queued_email()
    process_email_queue()
    process_email_queue()
    assert queue.status == "submitted" and smtp.send.call_count == 1
    assert queue.sent_at is not None
    options = constructor.call_args.kwargs
    context = options.get("context") or options["smtp_starttls"]["context"]
    assert context.check_hostname and context.verify_mode == 2
    assert (
        "inbox delivery is not confirmed" in EmailMessage.query.one().provider_response
    )


def test_ambiguous_smtp_failure_never_retries(app, monkeypatch):
    live_config(app)
    smtp = Mock()
    smtp.send.side_effect = smtplib.SMTPServerDisconnected("lost response")
    monkeypatch.setattr("yagmail.SMTP", Mock(return_value=smtp))
    draft, queue = queued_email()
    process_email_queue()
    process_email_queue(now=utcnow() + timedelta(days=1))
    assert queue.status == "uncertain" and smtp.send.call_count == 1


def test_safe_connection_failure_has_bounded_retries(app, monkeypatch):
    live_config(app)
    smtp = Mock()
    smtp.login.side_effect = ConnectionRefusedError()
    monkeypatch.setattr("yagmail.SMTP", Mock(return_value=smtp))
    draft, queue = queued_email()
    for offset in [0, 10, 20, 30]:
        process_email_queue(now=utcnow() + timedelta(minutes=offset))
    assert queue.status == "failed" and queue.attempts == 3
    assert smtp.send.call_count == 0


def test_interrupted_submission_is_uncertain(app):
    draft, queue = queued_email()
    queue.status = "sending"
    queue.claimed_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    process_email_queue()
    assert (
        queue.status == "uncertain" and EmailMessage.query.one().status == "uncertain"
    )


def test_document_export_revision_and_finalized_immutability(auth_client):
    project = project_fixture()
    document = generate_document(project, "handover")
    db.session.commit()
    for endpoint in [
        f"/documents/{document.id}",
        f"/documents/{document.id}/export/md",
        f"/documents/{document.id}/export/pdf",
    ]:
        response = auth_client.get(endpoint)
        assert response.status_code == 200
        if endpoint.endswith("pdf"):
            assert response.data.startswith(b"%PDF")
    original = document.body
    assert (
        auth_client.post(
            f"/documents/{document.id}/finalize", data={"confirm": "yes"}
        ).status_code
        == 302
    )
    assert (
        auth_client.post(
            f"/documents/{document.id}",
            data={"title": "Changed", "body": "Overwritten"},
        ).status_code
        == 400
    )
    assert document.body == original
    assert auth_client.post(f"/documents/{document.id}/revise").status_code == 302
    revised = Document.query.filter_by(parent_id=document.id).one()
    assert revised.version == 2 and revised.status == "draft"


def test_upload_signatures_and_protected_download(auth_client, client):
    assert (
        auth_client.post(
            "/documents/upload",
            data={"file": (BytesIO(b"<script>alert(1)</script>"), "fake.pdf")},
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            "/documents/upload", data={"file": (BytesIO(b"<svg></svg>"), "image.svg")}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            "/documents/upload",
            data={"file": (BytesIO(b"Private client note"), "../../private.txt")},
        ).status_code
        == 302
    )
    file = FileAttachment.query.one()
    assert file.original_name == "private.txt" and "/" not in file.stored_name
    response = auth_client.get(f"/files/{file.id}/download")
    assert response.status_code == 200 and response.data == b"Private client note"
    assert "attachment" in response.headers["Content-Disposition"]
    auth_client.post("/logout")
    assert client.get(f"/files/{file.id}/download").status_code == 302


def test_durable_jobs_and_rules_are_idempotent(app):
    project = project_fixture()
    rule = EmailAutomationRule(
        name="Prepare contract review",
        trigger_event="proposal.accepted",
        action="create_task",
    )
    db.session.add(rule)
    job = trigger_event(
        "proposal.accepted", project=project, event_key="proposal:1:accepted"
    )
    db.session.commit()
    assert (
        trigger_event(
            "proposal.accepted", project=project, event_key="proposal:1:accepted"
        ).id
        == job.id
    )
    run_due_jobs()
    run_due_jobs()
    assert (
        Task.query.filter_by(event_key=f"rule:{rule.id}:proposal:1:accepted").count()
        == 1
    )
    assert job.status == "completed" and job.attempts == 1


def test_job_retry_preserves_transaction_and_stops_after_limit(app):
    job = schedule_job(
        "create_draft",
        "bad-project-job",
        {"project_id": 99999, "template_key": "onboarding"},
    )
    db.session.commit()
    for offset in [0, 10, 20, 30]:
        run_due_jobs(now=utcnow() + timedelta(minutes=offset))
    assert job.status == "failed" and job.attempts == 3
    assert EmailDraft.query.count() == 0


def test_all_communication_screens_and_missing_ids(auth_client):
    project = project_fixture()
    draft = prepare_email(project, "onboarding")
    db.session.commit()
    for path in [
        "/email",
        "/email/new",
        f"/email/{draft.id}",
        "/email/templates",
        "/email/templates/new",
        "/documents",
        "/documents/new",
        "/documents/templates",
        "/documents/templates/new",
        "/settings/automations",
    ]:
        assert auth_client.get(path).status_code == 200
    for path in ["/email/99999", "/documents/99999", "/files/99999/download"]:
        assert auth_client.get(path).status_code == 404


def test_approved_models_cannot_be_rewritten(app):
    project = project_fixture()
    document = generate_document(project, "handover")
    document.status = "finalized"
    db.session.commit()
    document.body = "Rewritten"
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()
    draft, queue = queued_email()
    draft.recipient = "changed@example.com"
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()


def test_preview_and_export_do_not_generate_documents(auth_client):
    project = project_fixture()
    template = DocumentTemplate.query.filter_by(key="handover").one()
    response = auth_client.get(
        f"/documents/templates/{template.id}/preview?project_id={project.id}"
    )
    assert response.status_code == 200 and b"Luna Owner" in response.data
    response = auth_client.get(f"/documents/templates/{template.id}/export")
    assert response.status_code == 200 and b"{{client_name}}" in response.data
    assert Document.query.count() == 0
