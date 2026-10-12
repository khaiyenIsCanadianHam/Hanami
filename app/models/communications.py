"""Versioned correspondence, private files and durable automation records."""

from app.extensions import db
from app.models.base import BaseModel
from sqlalchemy import event, inspect, select


class EmailTemplate(BaseModel):
    __tablename__ = "email_templates"
    key = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default="General", nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    html_body = db.Column(db.Text, default="", nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False)
    __table_args__ = (db.UniqueConstraint("key", "version"),)


class EmailDraft(BaseModel):
    __tablename__ = "email_drafts"
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"))
    recipient = db.Column(db.String(254), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    html_body = db.Column(db.Text, default="", nullable=False)
    attachment_ids = db.Column(db.JSON, default=list, nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False, index=True)
    scheduled_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    event_key = db.Column(db.String(200), unique=True)
    client = db.relationship("Client", foreign_keys=[client_id])
    project = db.relationship("Project", foreign_keys=[project_id])


class EmailQueue(BaseModel):
    __tablename__ = "email_queue"
    draft_id = db.Column(
        db.Integer, db.ForeignKey("email_drafts.id"), nullable=False, unique=True
    )
    status = db.Column(db.String(30), default="pending", nullable=False, index=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    next_attempt_at = db.Column(db.DateTime, nullable=False, index=True)
    claimed_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500), default="", nullable=False)
    draft = db.relationship("EmailDraft", backref=db.backref("queue", uselist=False))


class EmailMessage(BaseModel):
    __tablename__ = "email_messages"
    draft_id = db.Column(db.Integer, db.ForeignKey("email_drafts.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    direction = db.Column(db.String(20), default="outgoing", nullable=False)
    recipient = db.Column(db.String(254), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False)
    provider_response = db.Column(db.String(500), default="", nullable=False)
    failure_reason = db.Column(db.String(500), default="", nullable=False)
    sent_at = db.Column(db.DateTime)


class EmailAutomationRule(BaseModel):
    __tablename__ = "email_automation_rules"
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    trigger_event = db.Column(db.String(100), nullable=False, index=True)
    conditions = db.Column(db.JSON, default=dict, nullable=False)
    action = db.Column(db.String(60), default="create_task", nullable=False)
    template_key = db.Column(db.String(100))
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    requires_approval = db.Column(db.Boolean, default=True, nullable=False)
    last_executed_at = db.Column(db.DateTime)
    execution_result = db.Column(db.String(500), default="", nullable=False)


class ScheduledJob(BaseModel):
    __tablename__ = "scheduled_jobs"
    event_key = db.Column(db.String(200), unique=True, nullable=False)
    kind = db.Column(db.String(100), nullable=False)
    payload = db.Column(db.JSON, default=dict, nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False, index=True)
    due_at = db.Column(db.DateTime, nullable=False, index=True)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    max_attempts = db.Column(db.Integer, default=3, nullable=False)
    claimed_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500), default="", nullable=False)


class DocumentTemplate(BaseModel):
    __tablename__ = "document_templates"
    key = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), default="General", nullable=False)
    body = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    archived = db.Column(db.Boolean, default=False, nullable=False)
    __table_args__ = (db.UniqueConstraint("key", "version"),)


class Document(BaseModel):
    __tablename__ = "documents"
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("document_templates.id"))
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("documents.id"))
    finalized_at = db.Column(db.DateTime)
    project = db.relationship("Project", foreign_keys=[project_id])


class FileAttachment(BaseModel):
    __tablename__ = "file_attachments"
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(100), nullable=False, unique=True)
    content_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))


@event.listens_for(Document, "before_update")
def preserve_finalized_document(mapper, connection, target):
    previous = connection.scalar(
        select(Document.__table__.c.status).where(Document.__table__.c.id == target.id)
    )
    if previous == "finalized":
        changed = {
            attribute.key
            for attribute in inspect(target).attrs
            if attribute.history.has_changes()
        }
        if changed - {"updated_at"}:
            raise ValueError("Finalized documents are immutable; create a revision.")


@event.listens_for(EmailDraft, "before_update")
def preserve_approved_email(mapper, connection, target):
    approved = connection.scalar(
        select(EmailDraft.__table__.c.approved_at).where(
            EmailDraft.__table__.c.id == target.id
        )
    )
    if approved is not None:
        changed = {
            attribute.key
            for attribute in inspect(target).attrs
            if attribute.history.has_changes()
        }
        if changed - {"status", "updated_at", "queue"}:
            raise ValueError(
                "Approved email content is immutable; compose a new draft."
            )


@event.listens_for(EmailTemplate, "before_update")
@event.listens_for(DocumentTemplate, "before_update")
def preserve_template_versions(mapper, connection, target):
    changed = {
        attribute.key
        for attribute in inspect(target).attrs
        if attribute.history.has_changes()
    }
    if changed - {"archived", "updated_at"}:
        raise ValueError("Template versions are immutable; save a new version.")
