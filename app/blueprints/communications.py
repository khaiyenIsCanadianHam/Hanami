"""Administrator communications workspace, private documents and automation controls."""

from datetime import datetime, timezone
from functools import wraps
import re
import uuid

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user

from app.extensions import db
from app.models.base import utcnow
from app.models.core import ApplicationSetting, Project
from app.models.communications import (
    Document,
    DocumentTemplate,
    EmailAutomationRule,
    EmailDraft,
    EmailMessage,
    EmailQueue,
    EmailTemplate,
    FileAttachment,
    ScheduledJob,
)
from app.services.common import admin_required, audit, setting
from app.services.document_service import (
    VARIABLES,
    attachment_path,
    export_pdf,
    generate_document,
    project_context,
    render_literal,
    save_attachment,
    validate_template,
)
from app.services.email_service import (
    approve_email,
    draft_email,
    is_paused,
    is_test_mode,
    process_email_queue,
    sanitize_html,
    validate_recipient,
)
from app.services.automation_service import run_due_jobs, schedule_job

bp = Blueprint("communications", __name__)


def action(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("communications/error.html", message=str(exc)), 400

    return wrapped


def _project(required=False):
    raw = request.form.get("project_id", "")
    if not raw:
        if required:
            raise ValueError("Choose a project.")
        return None
    return db.get_or_404(Project, int(raw))


def _when(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Enter a valid scheduled date and time in UTC.") from exc
    return (
        parsed.astimezone(timezone.utc).replace(tzinfo=None)
        if parsed.tzinfo
        else parsed
    )


def _save_setting(key, value):
    record = ApplicationSetting.query.filter_by(key=key).first()
    if record is None:
        record = ApplicationSetting(key=key)
        db.session.add(record)
    record.value = value


@bp.route("/email")
@admin_required
def email_center():
    query = EmailDraft.query
    if request.args.get("project_id"):
        query = query.filter_by(project_id=request.args["project_id"])
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return render_template(
        "communications/email.html",
        drafts=query.order_by(EmailDraft.created_at.desc()).all(),
        messages=EmailMessage.query.order_by(EmailMessage.created_at.desc())
        .limit(100)
        .all(),
        test_mode=is_test_mode(),
        paused=is_paused(),
        suppression=setting("email_suppression_list", ""),
    )


@bp.route("/email/new", methods=["GET", "POST"])
@admin_required
@action
def email_new():
    if request.method == "POST":
        project = _project()
        template_id = request.form.get("template_id")
        if template_id and not request.form.get("body", "").strip():
            template = db.get_or_404(EmailTemplate, int(template_id))
            if template.archived:
                raise ValueError("Choose an active template.")
            values = project_context(project)
            recipient = request.form.get("recipient") or values.get("client_email", "")
            draft = draft_email(
                recipient,
                render_literal(template.subject, values),
                render_literal(template.body, values),
                project=project,
                template_id=template.id,
                html_body=render_literal(template.html_body, values, html=True),
                scheduled_at=_when(request.form.get("scheduled_at")),
                attachment_ids=[
                    int(value) for value in request.form.getlist("attachment_ids")
                ],
            )
        else:
            draft = draft_email(
                request.form.get("recipient"),
                request.form.get("subject", ""),
                request.form.get("body", ""),
                project=project,
                html_body=request.form.get("html_body", ""),
                scheduled_at=_when(request.form.get("scheduled_at")),
                attachment_ids=[
                    int(value) for value in request.form.getlist("attachment_ids")
                ],
            )
        db.session.commit()
        flash("Draft saved. Review and approve before sending.", "success")
        return redirect(url_for("communications.email_detail", draft_id=draft.id))
    return render_template(
        "communications/composer.html",
        draft=None,
        projects=Project.query.order_by(Project.title).all(),
        templates=EmailTemplate.query.filter_by(archived=False)
        .order_by(EmailTemplate.category, EmailTemplate.name)
        .all(),
        files=FileAttachment.query.order_by(FileAttachment.created_at.desc())
        .limit(200)
        .all(),
    )


@bp.route("/email/<int:draft_id>", methods=["GET", "POST"])
@admin_required
@action
def email_detail(draft_id):
    draft = db.get_or_404(EmailDraft, draft_id)
    if request.method == "POST":
        if draft.status != "draft":
            raise ValueError(
                "Approved correspondence is immutable. Create a new draft to make changes."
            )
        subject, body = request.form.get("subject", ""), request.form.get("body", "")
        if (
            not subject.strip()
            or len(subject) > 300
            or "\n" in subject
            or "\r" in subject
            or not body.strip()
            or len(body) > 100_000
        ):
            raise ValueError(
                "Provide a subject (maximum 300 characters, one line) and body (maximum 100,000 characters)."
            )
        draft.recipient = validate_recipient(request.form.get("recipient"))
        draft.subject, draft.body = subject, body
        draft.html_body = sanitize_html(request.form.get("html_body", ""))
        if len(draft.html_body) > 100_000:
            raise ValueError("HTML email body is too large.")
        draft.scheduled_at = _when(request.form.get("scheduled_at"))
        ids = [int(value) for value in request.form.getlist("attachment_ids")]
        for file_id in ids:
            attachment = db.get_or_404(FileAttachment, file_id)
            if draft.project_id and attachment.project_id not in {
                None,
                draft.project_id,
            }:
                raise ValueError("Attachment belongs to a different project.")
        draft.attachment_ids = ids
        db.session.commit()
        flash("Draft updated.", "success")
        return redirect(url_for("communications.email_detail", draft_id=draft.id))
    files = FileAttachment.query
    if draft.project_id:
        files = files.filter(
            db.or_(
                FileAttachment.project_id == draft.project_id,
                FileAttachment.project_id.is_(None),
            )
        )
    return render_template(
        "communications/email_detail.html",
        draft=draft,
        files=files.all(),
        messages=EmailMessage.query.filter_by(draft_id=draft.id)
        .order_by(EmailMessage.created_at.desc())
        .all(),
        test_mode=is_test_mode(),
    )


@bp.post("/email/<int:draft_id>/approve")
@admin_required
@action
def email_approve(draft_id):
    draft = db.get_or_404(EmailDraft, draft_id)
    if request.form.get("confirm") != "yes":
        raise ValueError("Confirm that you reviewed the recipient and content.")
    approve_email(draft, actor_id=current_user.id)
    db.session.commit()
    flash(
        "Email approved and queued. The scheduler respects its scheduled time.",
        "success",
    )
    return redirect(url_for("communications.email_detail", draft_id=draft.id))


@bp.post("/email/<int:draft_id>/cancel")
@admin_required
@action
def email_cancel(draft_id):
    draft = db.get_or_404(EmailDraft, draft_id)
    if draft.status == "draft":
        draft.status = "cancelled"
    elif draft.status == "queued":
        result = db.session.execute(
            db.update(EmailQueue)
            .where(EmailQueue.draft_id == draft.id, EmailQueue.status == "pending")
            .values(status="cancelled")
        )
        if result.rowcount != 1:
            raise ValueError(
                "The worker already claimed this email. Inspect the delivery status."
            )
        draft.status = "cancelled"
    else:
        raise ValueError("Only draft or pending email can be cancelled.")
    audit("email.cancelled", "EmailDraft", draft.id)
    db.session.commit()
    return redirect(url_for("communications.email_detail", draft_id=draft.id))


@bp.post("/email/<int:draft_id>/retry")
@admin_required
@action
def email_retry(draft_id):
    draft = db.get_or_404(EmailDraft, draft_id)
    queue = EmailQueue.query.filter_by(draft_id=draft.id).first()
    if queue is None or queue.status != "failed":
        raise ValueError(
            "Only definitively failed submissions can be retried. Uncertain outcomes require provider investigation."
        )
    queue.status, queue.attempts, queue.next_attempt_at = "pending", 0, utcnow()
    draft.status = "queued"
    audit(
        "email.retry",
        "EmailDraft",
        draft.id,
        "Administrator requested retry after definitive failure.",
    )
    db.session.commit()
    return redirect(url_for("communications.email_detail", draft_id=draft.id))


@bp.post("/email/process")
@admin_required
@action
def email_process():
    result = process_email_queue()
    flash(
        "Automations are paused."
        if result["paused"]
        else f"Processed {result['processed']} queued email(s).",
        "info",
    )
    return redirect(url_for("communications.email_center"))


@bp.post("/email/incoming")
@admin_required
@action
def incoming_message():
    project = _project()
    subject, body = (
        request.form.get("subject", "").strip(),
        request.form.get("body", "").strip(),
    )
    if not subject or len(subject) > 300 or not body or len(body) > 100_000:
        raise ValueError("A subject and body are required within the supported limits.")
    db.session.add(
        EmailMessage(
            project_id=project.id if project else None,
            client_id=project.client_id if project else None,
            direction="incoming",
            recipient=validate_recipient(request.form.get("sender")),
            subject=subject,
            body=body,
            status="recorded",
            provider_response="Manually recorded by administrator; no inbox synchronization.",
        )
    )
    db.session.commit()
    flash("Incoming message recorded.", "success")
    return redirect(url_for("communications.email_center"))


@bp.post("/email/suppression")
@admin_required
@action
def email_suppression():
    values = sorted(
        {
            validate_recipient(value).lower()
            for value in re.split(r"[,;\s]+", request.form.get("addresses", ""))
            if value
        }
    )
    _save_setting("email_suppression_list", "\n".join(values))
    audit(
        "email.suppression_updated",
        "ApplicationSetting",
        None,
        "Administrator updated suppression controls.",
    )
    db.session.commit()
    flash(
        "Suppression list updated. It is checked again immediately before submission.",
        "success",
    )
    return redirect(url_for("communications.email_center"))


def _template_model(kind):
    if kind == "email":
        return EmailTemplate
    if kind == "documents":
        return DocumentTemplate
    abort(404)


@bp.get("/<kind>/templates")
@admin_required
def templates(kind):
    model = _template_model(kind)
    return render_template(
        "communications/templates.html",
        kind=kind,
        rows=model.query.order_by(
            model.category, model.key, model.version.desc()
        ).all(),
    )


@bp.route("/<kind>/templates/new", methods=["GET", "POST"])
@bp.route("/<kind>/templates/<int:template_id>/edit", methods=["GET", "POST"])
@admin_required
@action
def template_edit(kind, template_id=None):
    model = _template_model(kind)
    template = db.get_or_404(model, template_id) if template_id else None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        body = request.form.get("body", "").strip()
        category = request.form.get("category", "General").strip()
        if not name or len(name) > 200 or not body or len(category) > 100:
            raise ValueError(
                "Provide a template name, category and body within the supported limits."
            )
        validate_template(body)
        key = (
            template.key
            if template
            else re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:75]
            + "_"
            + uuid.uuid4().hex[:8]
        )
        latest = model.query.filter_by(key=key).order_by(model.version.desc()).first()
        values = dict(
            key=key,
            name=name,
            category=category,
            body=body,
            version=(latest.version + 1) if latest else 1,
        )
        if kind == "email":
            subject = request.form.get("subject", "").strip()
            if not subject or len(subject) > 300 or "\n" in subject or "\r" in subject:
                raise ValueError(
                    "Provide an email subject of at most 300 characters on one line."
                )
            validate_template(subject)
            html = request.form.get("html_body", "")
            validate_template(html)
            values.update(subject=subject, html_body=sanitize_html(html))
        if latest:
            latest.archived = True
        db.session.add(model(**values))
        db.session.commit()
        flash(
            "Template version saved. Existing documents and email retain their original content.",
            "success",
        )
        return redirect(url_for("communications.templates", kind=kind))
    return render_template(
        "communications/template_edit.html",
        kind=kind,
        template=template,
        variables=sorted(VARIABLES),
    )


@bp.post("/<kind>/templates/<int:template_id>/duplicate")
@admin_required
@action
def template_duplicate(kind, template_id):
    model = _template_model(kind)
    original = db.get_or_404(model, template_id)
    values = dict(
        key=f"copy_{uuid.uuid4().hex}",
        name=f"{original.name[:190]} (copy)",
        category=original.category,
        body=original.body,
    )
    if kind == "email":
        values.update(subject=original.subject, html_body=original.html_body)
    copy = model(**values)
    db.session.add(copy)
    db.session.commit()
    return redirect(
        url_for("communications.template_edit", kind=kind, template_id=copy.id)
    )


@bp.post("/<kind>/templates/<int:template_id>/archive")
@admin_required
def template_archive(kind, template_id):
    model = _template_model(kind)
    template = db.get_or_404(model, template_id)
    template.archived = True
    db.session.commit()
    flash("Template archived; existing records are retained.", "success")
    return redirect(url_for("communications.templates", kind=kind))


@bp.get("/<kind>/templates/<int:template_id>/preview")
@admin_required
@action
def template_preview(kind, template_id):
    template = db.get_or_404(_template_model(kind), template_id)
    project_id = request.args.get("project_id")
    project = db.get_or_404(Project, int(project_id)) if project_id else None
    values = project_context(project)
    return render_template(
        "communications/template_preview.html",
        kind=kind,
        template=template,
        body=render_literal(template.body, values),
        subject=render_literal(template.subject, values) if kind == "email" else "",
        projects=Project.query.order_by(Project.title).all(),
        selected_project=project,
    )


@bp.get("/<kind>/templates/<int:template_id>/export")
@admin_required
def template_export(kind, template_id):
    from io import BytesIO

    template = db.get_or_404(_template_model(kind), template_id)
    content = (template.subject + "\n\n" if kind == "email" else "") + template.body
    return send_file(
        BytesIO(content.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"{kind}-template-{template.id}-v{template.version}.{'txt' if kind == 'email' else 'md'}",
    )


@bp.get("/documents")
@admin_required
def documents():
    docs, files = Document.query, FileAttachment.query
    if request.args.get("project_id"):
        docs, files = (
            docs.filter_by(project_id=request.args["project_id"]),
            files.filter_by(project_id=request.args["project_id"]),
        )
    return render_template(
        "communications/documents.html",
        documents=docs.order_by(Document.created_at.desc()).all(),
        files=files.order_by(FileAttachment.created_at.desc()).all(),
        projects=Project.query.order_by(Project.title).all(),
    )


@bp.route("/documents/new", methods=["GET", "POST"])
@admin_required
@action
def document_new():
    if request.method == "POST":
        project = _project(required=True)
        template = db.get_or_404(
            DocumentTemplate, int(request.form.get("template_id", "0"))
        )
        document = generate_document(
            project, template.key, title=request.form.get("title") or None
        )
        if len(document.title) > 200:
            raise ValueError("Document title must be at most 200 characters.")
        db.session.commit()
        return redirect(
            url_for("communications.document_detail", document_id=document.id)
        )
    return render_template(
        "communications/document_new.html",
        projects=Project.query.order_by(Project.title).all(),
        templates=DocumentTemplate.query.filter_by(archived=False)
        .order_by(DocumentTemplate.category, DocumentTemplate.name)
        .all(),
    )


@bp.route("/documents/<int:document_id>", methods=["GET", "POST"])
@admin_required
@action
def document_detail(document_id):
    document = db.get_or_404(Document, document_id)
    if request.method == "POST":
        if document.status != "draft":
            raise ValueError(
                "Finalized documents are immutable. Create a new revision to edit."
            )
        title, body = (
            request.form.get("title", "").strip(),
            request.form.get("body", ""),
        )
        if not title or len(title) > 200 or not body.strip() or len(body) > 200_000:
            raise ValueError(
                "Provide a title (up to 200 characters) and body (up to 200,000 characters)."
            )
        document.title, document.body = title, body
        db.session.commit()
        flash("Document draft saved.", "success")
        return redirect(
            url_for("communications.document_detail", document_id=document.id)
        )
    root_id = document.parent_id or document.id
    versions = (
        Document.query.filter(
            db.or_(Document.id == root_id, Document.parent_id == root_id)
        )
        .order_by(Document.version.desc())
        .all()
    )
    return render_template(
        "communications/document_detail.html", document=document, versions=versions
    )


@bp.post("/documents/<int:document_id>/finalize")
@admin_required
@action
def document_finalize(document_id):
    document = db.get_or_404(Document, document_id)
    if document.status != "draft" or request.form.get("confirm") != "yes":
        raise ValueError("Confirm review of a draft before finalizing it.")
    if "[missing:" in document.body:
        raise ValueError("Resolve missing template values before finalizing.")
    document.status, document.finalized_at = "finalized", utcnow()
    audit(
        "document.finalized",
        "Document",
        document.id,
        "Document frozen after administrator review; this does not imply client approval.",
    )
    db.session.commit()
    return redirect(url_for("communications.document_detail", document_id=document.id))


@bp.post("/documents/<int:document_id>/revise")
@admin_required
def document_revise(document_id):
    document = db.get_or_404(Document, document_id)
    root_id = document.parent_id or document.id
    latest = (
        Document.query.filter(
            db.or_(Document.id == root_id, Document.parent_id == root_id)
        )
        .order_by(Document.version.desc())
        .first()
    )
    revision = Document(
        title=document.title,
        body=document.body,
        project_id=document.project_id,
        client_id=document.client_id,
        template_id=document.template_id,
        parent_id=root_id,
        version=latest.version + 1,
    )
    db.session.add(revision)
    db.session.commit()
    return redirect(url_for("communications.document_detail", document_id=revision.id))


@bp.get("/documents/<int:document_id>/export/<format>")
@admin_required
@action
def document_export(document_id, format):
    document = db.get_or_404(Document, document_id)
    if format == "pdf":
        return send_file(
            export_pdf(document),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"document-{document.id}-v{document.version}.pdf",
        )
    if format == "md":
        from io import BytesIO

        return send_file(
            BytesIO(document.body.encode("utf-8")),
            mimetype="text/markdown",
            as_attachment=True,
            download_name=f"document-{document.id}-v{document.version}.md",
        )
    abort(404)


@bp.post("/documents/upload")
@admin_required
@action
def file_upload():
    file = request.files.get("file")
    if file is None:
        raise ValueError("Select a file to upload.")
    attachment = save_attachment(file, project=_project(), uploaded_by=current_user.id)
    try:
        db.session.commit()
    except Exception:
        attachment_path(attachment).unlink(missing_ok=True)
        raise
    flash("Private attachment stored.", "success")
    return redirect(url_for("communications.documents"))


@bp.get("/files/<int:file_id>/download")
@admin_required
@action
def file_download(file_id):
    attachment = db.get_or_404(FileAttachment, file_id)
    path = attachment_path(attachment)
    if not path.is_file():
        abort(404)
    response = send_file(
        path,
        mimetype=attachment.content_type,
        as_attachment=True,
        download_name=attachment.original_name,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/settings/automations", methods=["GET", "POST"])
@admin_required
@action
def automations():
    if request.method == "POST":
        _save_setting(
            "automations_paused",
            "true" if request.form.get("paused") == "yes" else "false",
        )
        db.session.commit()
        flash("Automation pause setting saved.", "success")
        return redirect(url_for("communications.automations"))
    return render_template(
        "communications/automations.html",
        paused=is_paused(),
        rules=EmailAutomationRule.query.order_by(EmailAutomationRule.id).all(),
        jobs=ScheduledJob.query.order_by(ScheduledJob.created_at.desc())
        .limit(100)
        .all(),
        templates=EmailTemplate.query.filter_by(archived=False).all(),
        projects=Project.query.order_by(Project.title).all(),
    )


@bp.post("/settings/automations/rules")
@admin_required
@action
def automation_rule():
    name, trigger = (
        request.form.get("name", "").strip(),
        request.form.get("trigger_event", "").strip(),
    )
    action_name = request.form.get("action", "create_task")
    if not name or len(name) > 200 or not re.fullmatch(r"[a-z0-9_.-]{1,100}", trigger):
        raise ValueError(
            "Provide a rule name and a trigger containing lowercase letters, numbers, dot, underscore or dash."
        )
    if action_name not in {"create_task", "create_draft"}:
        raise ValueError("Choose a supported action.")
    template_key = request.form.get("template_key") or None
    if (
        action_name == "create_draft"
        and not EmailTemplate.query.filter_by(key=template_key, archived=False).first()
    ):
        raise ValueError("Choose an active email template.")
    conditions = {}
    if request.form.get("project_status"):
        conditions["project_status"] = request.form["project_status"][:30]
    if request.form.get("stage"):
        stage = int(request.form["stage"])
        if not 1 <= stage <= 14:
            raise ValueError("Stage must be between 1 and 14.")
        conditions["stage"] = stage
    db.session.add(
        EmailAutomationRule(
            name=name,
            description=request.form.get("description", "")[:5000],
            trigger_event=trigger,
            action=action_name,
            template_key=template_key,
            conditions=conditions,
            requires_approval=True,
        )
    )
    db.session.commit()
    flash("Rule created. Email actions always produce drafts for approval.", "success")
    return redirect(url_for("communications.automations"))


@bp.post("/settings/automations/rules/<int:rule_id>/toggle")
@admin_required
def automation_toggle(rule_id):
    rule = db.get_or_404(EmailAutomationRule, rule_id)
    rule.enabled = not rule.enabled
    db.session.commit()
    return redirect(url_for("communications.automations"))


@bp.post("/settings/automations/jobs/<int:job_id>/retry")
@admin_required
@action
def automation_retry(job_id):
    job = db.get_or_404(ScheduledJob, job_id)
    if job.status != "failed":
        raise ValueError("Only a failed job can be retried manually.")
    job.status, job.attempts, job.due_at = "pending", 0, utcnow()
    audit(
        "automation.retry",
        "ScheduledJob",
        job.id,
        "Administrator requested a retry after reviewing job failure.",
    )
    db.session.commit()
    flash(
        "Job queued for retry. Existing actions retain their duplicate protection.",
        "success",
    )
    return redirect(url_for("communications.automations"))


@bp.post("/settings/automations/run")
@admin_required
@action
def automation_run():
    schedule_job("reminder_scan", f"manual-reminder-scan:{uuid.uuid4().hex}")
    db.session.commit()
    result = run_due_jobs()
    flash(
        "Automations are paused."
        if result["paused"]
        else f"Completed {result['processed']} jobs; {result['failed']} failed. Review the job log.",
        "info",
    )
    return redirect(url_for("communications.automations"))
