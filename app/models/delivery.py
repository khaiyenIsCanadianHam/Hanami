"""Evidence-based delivery and aftercare records; credentials never belong here."""

from app.extensions import db
from app.models.base import BaseModel, utcnow


class Meeting(BaseModel):
    __tablename__ = "meeting"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    participants = db.Column(db.Text, nullable=False)
    agenda = db.Column(db.Text, default="")
    summary = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="scheduled", nullable=False)
    project = db.relationship("Project", backref="meetings")
    notes = db.relationship(
        "MeetingNote", backref="meeting", cascade="all, delete-orphan"
    )


class MeetingNote(BaseModel):
    __tablename__ = "meeting_note"
    meeting_id = db.Column(
        db.Integer, db.ForeignKey("meeting.id"), nullable=False, index=True
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    category = db.Column(db.String(30), default="note", nullable=False)
    body = db.Column(db.Text, nullable=False)
    action_owner = db.Column(db.String(200), default="")
    due_at = db.Column(db.DateTime)
    resolved = db.Column(db.Boolean, default=False, nullable=False)


class DesignSubmission(BaseModel):
    __tablename__ = "design_submission"
    __table_args__ = (
        db.UniqueConstraint("project_id", "version", name="uq_design_project_version"),
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    category = db.Column(db.String(40), default="mockup", nullable=False)
    reference_url = db.Column(db.String(2000), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="submitted", nullable=False)
    submitted_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.String(200))
    approval_evidence = db.Column(db.Text)
    project = db.relationship("Project", backref="design_submissions")


class RevisionRequest(BaseModel):
    __tablename__ = "revision_request"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    design_id = db.Column(
        db.Integer, db.ForeignKey("design_submission.id"), nullable=False, index=True
    )
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), nullable=False)
    included = db.Column(db.Boolean, default=True, nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="requested", nullable=False)
    resolution = db.Column(db.Text, default="")
    completed_at = db.Column(db.DateTime)
    design = db.relationship("DesignSubmission", backref="revisions")


class ChangeRequest(BaseModel):
    __tablename__ = "change_request"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    revision_id = db.Column(
        db.Integer, db.ForeignKey("revision_request.id"), unique=True
    )
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    impact = db.Column(db.Text, default="")
    estimated_cost = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    estimated_hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    status = db.Column(db.String(30), default="draft", nullable=False)
    decision_person = db.Column(db.String(200))
    decision_evidence = db.Column(db.Text)
    decided_at = db.Column(db.DateTime)
    revision = db.relationship(
        "RevisionRequest", backref=db.backref("change_request", uselist=False)
    )
    project = db.relationship("Project", backref="change_requests")


class TestCase(BaseModel):
    __tablename__ = "test_case"
    __table_args__ = (
        db.UniqueConstraint("project_id", "name", name="uq_test_project_name"),
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="functional")
    description = db.Column(db.Text, default="")
    preconditions = db.Column(db.Text, default="")
    steps = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text, nullable=False)
    required = db.Column(db.Boolean, nullable=False, default=True)
    severity = db.Column(db.String(20), default="medium", nullable=False)
    project = db.relationship("Project", backref="test_cases")
    executions = db.relationship(
        "TestExecution", backref="test_case", order_by="TestExecution.id"
    )

    @property
    def latest_execution(self):
        return self.executions[-1] if self.executions else None


class TestExecution(BaseModel):
    __tablename__ = "test_execution"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    test_case_id = db.Column(
        db.Integer, db.ForeignKey("test_case.id"), nullable=False, index=True
    )
    result = db.Column(db.String(20), nullable=False)
    actual_result = db.Column(db.Text, nullable=False)
    tester = db.Column(db.String(200), nullable=False)
    evidence = db.Column(db.Text, nullable=False)
    executed_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class BugReport(BaseModel):
    __tablename__ = "bug_report"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    test_execution_id = db.Column(
        db.Integer, db.ForeignKey("test_execution.id"), unique=True
    )
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    feature = db.Column(db.String(200), default="")
    severity = db.Column(db.String(20), default="medium", nullable=False)
    priority = db.Column(db.String(20), default="normal", nullable=False)
    reproduction_steps = db.Column(db.Text, default="")
    expected_behavior = db.Column(db.Text, default="")
    actual_behavior = db.Column(db.Text, default="")
    assigned_to = db.Column(db.String(200), default="")
    status = db.Column(db.String(30), nullable=False, default="open")
    release_blocking = db.Column(db.Boolean, default=False, nullable=False)
    resolution = db.Column(db.Text, default="")
    resolved_at = db.Column(db.DateTime)
    project = db.relationship("Project", backref="bugs")
    test_execution = db.relationship(
        "TestExecution", backref=db.backref("bug", uselist=False)
    )


class DeploymentRecord(BaseModel):
    __tablename__ = "deployment_record"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    production_url = db.Column(db.String(2000), nullable=False)
    hosting_provider = db.Column(db.String(200), nullable=False)
    domain_registrar = db.Column(db.String(200), default="")
    method = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(200), nullable=False)
    rollback_plan = db.Column(db.Text, nullable=False)
    checklist = db.Column(db.JSON, nullable=False, default=dict)
    backup_evidence = db.Column(db.Text, nullable=False)
    verification_evidence = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="planned", nullable=False)
    deployed_at = db.Column(db.DateTime)
    recorded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    project = db.relationship("Project", backref="deployments")


class HandoverRecord(BaseModel):
    __tablename__ = "handover_record"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    recipient = db.Column(db.String(200), nullable=False)
    production_url = db.Column(db.String(2000), nullable=False)
    deliverables = db.Column(db.JSON, nullable=False, default=dict)
    documentation = db.Column(db.Text, nullable=False)
    outstanding_obligations = db.Column(db.Text, default="")
    evidence = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False)
    completed_at = db.Column(db.DateTime)
    warranty_expires_at = db.Column(db.DateTime)
    project = db.relationship("Project", backref="handovers")


class TrainingRecord(BaseModel):
    __tablename__ = "training_record"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    scheduled_at = db.Column(db.DateTime, nullable=False)
    participants = db.Column(db.Text, nullable=False)
    topics = db.Column(db.Text, nullable=False)
    resources = db.Column(db.Text, default="")
    follow_up_questions = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="scheduled", nullable=False)
    completion_evidence = db.Column(db.Text, default="")
    project = db.relationship("Project", backref="training_records")


class MaintenanceAgreement(BaseModel):
    __tablename__ = "maintenance_agreement"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    client_id = db.Column(
        db.Integer, db.ForeignKey("client.id"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    website = db.Column(db.String(2000), nullable=False)
    monthly_fee = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), default="PHP", nullable=False)
    billing_frequency = db.Column(db.String(20), default="monthly", nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    renewal_date = db.Column(db.Date, nullable=False)
    covered_services = db.Column(db.Text, nullable=False)
    excluded_services = db.Column(db.Text, default="")
    support_hours = db.Column(db.String(200), default="")
    response_expectations = db.Column(db.Text, default="")
    status = db.Column(db.String(30), default="draft", nullable=False)
    acceptance_evidence = db.Column(db.Text, default="")
    project = db.relationship("Project", backref="maintenance_agreements")
    client = db.relationship("Client", backref="maintenance_agreements")


class MaintenanceTask(BaseModel):
    __tablename__ = "maintenance_task"
    __table_args__ = (
        db.UniqueConstraint(
            "agreement_id", "period", "category", name="uq_maintenance_period_category"
        ),
    )
    agreement_id = db.Column(
        db.Integer,
        db.ForeignKey("maintenance_agreement.id"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    period = db.Column(db.String(10), nullable=False)
    due_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    evidence = db.Column(db.Text, default="")
    completed_at = db.Column(db.DateTime)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"))
    agreement = db.relationship("MaintenanceAgreement", backref="tasks")


class SupportTicket(BaseModel):
    __tablename__ = "support_ticket"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    client_id = db.Column(
        db.Integer, db.ForeignKey("client.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="general")
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default="normal", nullable=False)
    status = db.Column(db.String(30), default="open", nullable=False)
    assigned_to = db.Column(db.String(200), default="")
    resolution = db.Column(db.Text, default="")
    time_spent = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    resolved_at = db.Column(db.DateTime)
    project = db.relationship("Project", backref="support_tickets")
    client = db.relationship("Client", backref="support_tickets")

    @property
    def reference(self):
        return f"SUP-{self.id:05d}" if self.id else "New ticket"
