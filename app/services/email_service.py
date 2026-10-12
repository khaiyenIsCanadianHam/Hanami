"""Review-first email queue with durable claims and conservative SMTP recovery."""

import re
import smtplib
import ssl
from datetime import timedelta

import bleach
from flask import current_app

from app.extensions import db
from app.models.base import utcnow
from app.models.communications import (
    EmailDraft,
    EmailMessage,
    EmailQueue,
    EmailTemplate,
    FileAttachment,
)
from app.services.common import audit, log_activity, setting
from app.services.document_service import (
    attachment_path,
    project_context,
    render_literal,
)


def is_paused():
    return (
        bool(current_app.config.get("AUTOMATIONS_PAUSED", False))
        or str(setting("automations_paused", "false")).lower() == "true"
    )


def is_test_mode():
    return (
        bool(current_app.config.get("EMAIL_TEST_MODE", True))
        or str(setting("email_test_mode", "true")).lower() != "false"
    )


def validate_recipient(address):
    address = (address or "").strip()
    if len(address) > 254 or not re.fullmatch(
        r"[^\s@,;<>\r\n]+@[^\s@,;<>\r\n]+\.[^\s@,;<>\r\n]+", address
    ):
        raise ValueError("Enter one valid recipient email address.")
    return address


def sanitize_html(value):
    return bleach.clean(
        value or "",
        tags={
            "p",
            "br",
            "strong",
            "em",
            "b",
            "i",
            "ul",
            "ol",
            "li",
            "a",
            "h1",
            "h2",
            "h3",
            "blockquote",
        },
        attributes={"a": ["href", "title"]},
        protocols={"https", "http", "mailto"},
        strip=True,
    )


def suppressed(address):
    entries = re.split(r"[,;\s]+", setting("email_suppression_list", "").lower())
    return address.lower() in entries


def draft_email(
    recipient,
    subject,
    body,
    project=None,
    client_id=None,
    template_id=None,
    html_body="",
    event_key=None,
    attachment_ids=None,
    scheduled_at=None,
):
    recipient = validate_recipient(recipient)
    if not subject.strip() or len(subject) > 300 or "\n" in subject or "\r" in subject:
        raise ValueError(
            "A subject of 1–300 characters without line breaks is required."
        )
    if not body.strip() or len(body) > 100_000 or len(html_body) > 100_000:
        raise ValueError("An email body of 1–100,000 characters is required.")
    if event_key:
        existing = EmailDraft.query.filter_by(event_key=event_key).first()
        if existing:
            return existing
    ids = list(dict.fromkeys(attachment_ids or []))
    for attachment_id in ids:
        file = db.session.get(FileAttachment, attachment_id)
        if file is None or (project and file.project_id not in {None, project.id}):
            raise ValueError("An attachment is missing or belongs to another project.")
    draft = EmailDraft(
        recipient=recipient,
        subject=subject.strip(),
        body=body,
        html_body=sanitize_html(html_body),
        project_id=project.id if project else None,
        client_id=project.client_id if project else client_id,
        template_id=template_id,
        event_key=event_key,
        attachment_ids=ids,
        scheduled_at=scheduled_at,
    )
    db.session.add(draft)
    log_activity(
        "email.drafted",
        "Prepared an email for administrator review.",
        client_id=draft.client_id,
        project_id=draft.project_id,
    )
    return draft


def prepare_email(project, template_key, context=None, recipient=None, event_key=None):
    template = (
        EmailTemplate.query.filter_by(key=template_key, archived=False)
        .order_by(EmailTemplate.version.desc())
        .first()
    )
    if template is None:
        raise ValueError("Choose an active email template.")
    values = project_context(project)
    values.update(context or {})
    return draft_email(
        recipient or values.get("client_email", ""),
        render_literal(template.subject, values),
        render_literal(template.body, values),
        project=project,
        template_id=template.id,
        html_body=render_literal(template.html_body, values, html=True),
        event_key=event_key,
    )


def approve_email(draft, actor_id=None):
    if draft.status != "draft":
        existing = EmailQueue.query.filter_by(draft_id=draft.id).first()
        if existing:
            return existing
        raise ValueError("Only an unapproved draft can be queued.")
    validate_recipient(draft.recipient)
    if suppressed(draft.recipient):
        raise ValueError(
            "Recipient is on the suppression list. Review consent before changing the list."
        )
    if "[missing:" in draft.subject + draft.body + draft.html_body:
        raise ValueError("Complete the missing template values before approval.")
    if not draft.subject.strip() or not draft.body.strip():
        raise ValueError("Subject and plain-text body are required.")
    draft.status, draft.approved_at, draft.approved_by = "queued", utcnow(), actor_id
    queue = EmailQueue(draft=draft, next_attempt_at=draft.scheduled_at or utcnow())
    db.session.add(queue)
    audit(
        "email.approved",
        "EmailDraft",
        draft.id,
        "Administrator approved immutable draft and queued delivery.",
    )
    return queue


def _record_attempt(queue, status, response="", error=""):
    draft = queue.draft
    db.session.add(
        EmailMessage(
            draft_id=draft.id,
            client_id=draft.client_id,
            project_id=draft.project_id,
            recipient=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            status=status,
            provider_response=response,
            failure_reason=error,
            sent_at=utcnow() if status == "submitted" else None,
        )
    )


def _finish(queue, status, error="", safe_retry=False):
    queue.last_error = error
    if safe_retry and queue.attempts < queue.max_attempts:
        queue.status = "pending"
        queue.next_attempt_at = utcnow() + timedelta(minutes=2**queue.attempts)
        queue.draft.status = "queued"
    else:
        queue.status = status
        queue.draft.status = status
    _record_attempt(queue, status, error=error)
    db.session.commit()


def recover_interrupted_sends(now=None):
    """A crash after SMTP acceptance has an unknown outcome: never retry automatically."""
    now = now or utcnow()
    stale = EmailQueue.query.filter(
        EmailQueue.status == "sending",
        EmailQueue.claimed_at < now - timedelta(minutes=15),
    ).all()
    for queue in stale:
        queue.status = queue.draft.status = "uncertain"
        queue.last_error = "Worker stopped during submission; inspect provider records before composing a new email."
        _record_attempt(queue, "uncertain", error=queue.last_error)
    db.session.commit()
    return len(stale)


def process_email_queue(limit=20, now=None):
    if is_paused():
        return {"processed": 0, "paused": True}
    now = now or utcnow()
    recover_interrupted_sends(now)
    ids = [
        row.id
        for row in EmailQueue.query.filter(
            EmailQueue.status == "pending", EmailQueue.next_attempt_at <= now
        )
        .order_by(EmailQueue.next_attempt_at)
        .limit(limit)
    ]
    processed = 0
    for queue_id in ids:
        # Compare-and-set is committed BEFORE network I/O; concurrent web/worker runners cannot duplicate submission.
        claim = db.session.execute(
            db.update(EmailQueue)
            .where(EmailQueue.id == queue_id, EmailQueue.status == "pending")
            .values(status="sending", claimed_at=now, attempts=EmailQueue.attempts + 1)
        )
        db.session.commit()
        if claim.rowcount != 1:
            continue
        queue = db.session.get(EmailQueue, queue_id)
        db.session.refresh(queue)
        draft = queue.draft
        processed += 1
        if draft.approved_at is None or suppressed(draft.recipient):
            _finish(
                queue, "suppressed", "Approval is missing or recipient is suppressed."
            )
            continue
        paths = []
        try:
            for file_id in draft.attachment_ids:
                attachment = db.session.get(FileAttachment, file_id)
                if attachment is None:
                    raise ValueError("A selected attachment no longer exists.")
                path = attachment_path(attachment)
                if not path.is_file():
                    raise ValueError("A selected attachment is unavailable.")
                paths.append(str(path))
        except ValueError as exc:
            _finish(queue, "failed", str(exc))
            continue
        if is_test_mode():
            queue.status = draft.status = "test_sent"
            queue.last_error = ""
            _record_attempt(
                queue,
                "test_sent",
                response="Test mode: rendered and validated locally; no email submitted.",
            )
            db.session.commit()
            continue
        config = current_app.config
        if not config.get("SMTP_USER") or not config.get("SMTP_PASSWORD"):
            _finish(
                queue,
                "failed",
                "SMTP credentials are not configured. Configure the environment, then retry manually.",
            )
            continue
        smtp = None
        try:
            import yagmail

            port = int(config.get("SMTP_PORT", 465))
            tls_context = ssl.create_default_context()
            tls_options = {"context": tls_context} if port == 465 else {}
            sender = {config["SMTP_USER"]: config.get("SMTP_SENDER_NAME", "WebDev CRM")}
            smtp = yagmail.SMTP(
                user=sender,
                password=config["SMTP_PASSWORD"],
                host=config.get("SMTP_HOST", "smtp.gmail.com"),
                port=port,
                smtp_ssl=port == 465,
                smtp_starttls=False if port == 465 else {"context": tls_context},
                timeout=30,
                **tls_options,
            )
            # Explicitly connect before send so pre-submission connection failures are safe to retry.
            smtp.login()
        except smtplib.SMTPAuthenticationError:
            _finish(
                queue,
                "failed",
                "SMTP authentication failed. Check environment credentials.",
            )
            continue
        except Exception as exc:
            _finish(
                queue,
                "failed",
                f"SMTP connection failed ({type(exc).__name__}); no message submitted.",
                safe_retry=True,
            )
            continue
        try:
            contents = [draft.body]
            if draft.html_body:
                contents.append(draft.html_body)
            headers = {}
            if config.get("SMTP_REPLY_TO"):
                headers["Reply-To"] = validate_recipient(config["SMTP_REPLY_TO"])
            smtp.send(
                to=draft.recipient,
                subject=draft.subject,
                contents=contents,
                attachments=paths or None,
                headers=headers,
                message_id=f"<webdev-crm-{draft.id}@local.invalid>",
            )
        except smtplib.SMTPRecipientsRefused:
            _finish(queue, "failed", "SMTP server rejected the recipient.")
        except smtplib.SMTPDataError as exc:
            _finish(
                queue,
                "failed",
                f"SMTP server rejected message data (code {exc.smtp_code}).",
                safe_retry=400 <= exc.smtp_code < 500,
            )
        except Exception as exc:
            _finish(
                queue,
                "uncertain",
                f"Submission outcome is uncertain ({type(exc).__name__}); inspect provider records. Automatic retry disabled.",
            )
        else:
            queue.status = draft.status = "submitted"
            queue.sent_at = utcnow()
            queue.last_error = ""
            _record_attempt(
                queue,
                "submitted",
                response="SMTP server accepted submission; inbox delivery is not confirmed.",
            )
            log_activity(
                "email.submitted",
                "Approved email submitted to SMTP.",
                client_id=draft.client_id,
                project_id=draft.project_id,
            )
            db.session.commit()
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass  # Closing an already submitted transport must not change delivery state.
    return {"processed": processed, "paused": False}
