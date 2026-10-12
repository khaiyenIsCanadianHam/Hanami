"""CRM, workflow, identity, settings, and audit entities."""

from decimal import Decimal
from flask_login import UserMixin
from sqlalchemy import event
from sqlalchemy.ext.mutable import MutableDict
from werkzeug.security import check_password_hash, generate_password_hash
from app.extensions import db
from .base import BaseModel, reference, utcnow


class User(UserMixin, BaseModel):
    __tablename__ = "user"
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="admin")
    active = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
            raise ValueError("Password must contain between 12 and 256 characters.")
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password):
        return bool(
            self.password_hash and check_password_hash(self.password_hash, password)
        )


class Lead(BaseModel):
    __tablename__ = "lead"
    reference = db.Column(
        db.String(32), default=lambda: reference("LEAD"), unique=True, nullable=False
    )
    name = db.Column(db.String(120), nullable=False)
    business_name = db.Column(db.String(200), default="", nullable=False)
    email = db.Column(db.String(254), default="", nullable=False, index=True)
    phone = db.Column(db.String(50), default="", nullable=False)
    website = db.Column(db.String(500), default="", nullable=False)
    industry = db.Column(db.String(120), default="", nullable=False)
    location = db.Column(db.String(200), default="", nullable=False)
    source = db.Column(db.String(100), default="Referral", nullable=False)
    service = db.Column(db.String(200), default="Website development", nullable=False)
    budget = db.Column(db.Numeric(14, 2), default=Decimal("0"), nullable=False)
    desired_date = db.Column(db.DateTime)
    notes = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(40), default="new", nullable=False, index=True)
    follow_up_at = db.Column(db.DateTime, index=True)
    last_contacted_at = db.Column(db.DateTime)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    client = db.relationship("Client", foreign_keys=[client_id], back_populates="leads")


class Client(BaseModel):
    __tablename__ = "client"
    reference = db.Column(
        db.String(32), default=lambda: reference("CLI"), unique=True, nullable=False
    )
    name = db.Column(db.String(120), nullable=False)
    business_name = db.Column(db.String(200), default="", nullable=False)
    email = db.Column(db.String(254), default="", nullable=False, index=True)
    phone = db.Column(db.String(50), default="", nullable=False)
    website = db.Column(db.String(500), default="", nullable=False)
    industry = db.Column(db.String(120), default="", nullable=False)
    location = db.Column(db.String(200), default="", nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(30), default="active", nullable=False, index=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("lead.id", use_alter=True), index=True
    )
    lead = db.relationship("Lead", foreign_keys=[lead_id], post_update=True)
    leads = db.relationship(
        "Lead", foreign_keys="Lead.client_id", back_populates="client"
    )
    projects = db.relationship("Project", back_populates="client", lazy="select")
    contacts = db.relationship("Contact", back_populates="client")


class Contact(BaseModel):
    __tablename__ = "contact"
    client_id = db.Column(
        db.Integer, db.ForeignKey("client.id"), nullable=False, index=True
    )
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), default="", nullable=False)
    phone = db.Column(db.String(50), default="", nullable=False)
    role = db.Column(db.String(120), default="Contact", nullable=False)
    client = db.relationship("Client", back_populates="contacts")


class Inquiry(BaseModel):
    __tablename__ = "inquiry"
    reference = db.Column(
        db.String(32), default=lambda: reference("INQ"), unique=True, nullable=False
    )
    lead_id = db.Column(db.Integer, db.ForeignKey("lead.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    website_type = db.Column(db.String(120), default="Business website", nullable=False)
    business_description = db.Column(db.Text, default="", nullable=False)
    features = db.Column(db.Text, default="", nullable=False)
    budget = db.Column(db.Numeric(14, 2), default=Decimal("0"), nullable=False)
    desired_date = db.Column(db.DateTime)
    communication = db.Column(db.String(50), default="email", nullable=False)
    answers = db.Column(MutableDict.as_mutable(db.JSON), default=dict, nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(30), default="new", nullable=False, index=True)
    lead = db.relationship("Lead")
    client = db.relationship("Client")
    project = db.relationship("Project")


class Project(BaseModel):
    __tablename__ = "project"
    __table_args__ = (
        db.CheckConstraint(
            "current_stage BETWEEN 1 AND 14", name="valid_current_stage"
        ),
    )
    reference = db.Column(
        db.String(32), default=lambda: reference("PRJ"), unique=True, nullable=False
    )
    client_id = db.Column(
        db.Integer, db.ForeignKey("client.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(30), default="active", nullable=False, index=True)
    current_stage = db.Column(db.Integer, default=1, nullable=False)
    contract_value = db.Column(db.Numeric(14, 2), default=Decimal("0"), nullable=False)
    currency = db.Column(db.String(3), default="PHP", nullable=False)
    deadline = db.Column(db.DateTime, index=True)
    revision_allowance = db.Column(db.Integer, default=2, nullable=False)
    repository_url = db.Column(db.String(500), default="", nullable=False)
    staging_url = db.Column(db.String(500), default="", nullable=False)
    client = db.relationship("Client", back_populates="projects")
    stages = db.relationship(
        "ProjectStage", back_populates="project", order_by="ProjectStage.number"
    )
    requirements = db.relationship("Requirement", back_populates="project")
    scope_items = db.relationship("ScopeItem", back_populates="project")
    milestones = db.relationship("ProjectMilestone", back_populates="project")
    tasks = db.relationship("Task", back_populates="project")
    approvals = db.relationship("Approval", back_populates="project")
    transitions = db.relationship("StageTransition", back_populates="project")

    @property
    def progress(self):
        return round(sum(s.status == "completed" for s in self.stages) / 14 * 100)


class ProjectStage(BaseModel):
    __tablename__ = "project_stage"
    __table_args__ = (
        db.UniqueConstraint("project_id", "number"),
        db.CheckConstraint("number BETWEEN 1 AND 14", name="valid_number"),
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    data = db.Column(MutableDict.as_mutable(db.JSON), default=dict, nullable=False)
    completed_at = db.Column(db.DateTime)
    project = db.relationship("Project", back_populates="stages")


class StageTransition(BaseModel):
    __tablename__ = "stage_transition"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    from_stage = db.Column(db.Integer, nullable=False)
    to_stage = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, default="", nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    project = db.relationship("Project", back_populates="transitions")
    actor = db.relationship("User")


class Requirement(BaseModel):
    __tablename__ = "requirement"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    stage_number = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(250), nullable=False)
    required = db.Column(db.Boolean, default=True, nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    exception = db.Column(db.Text, default="", nullable=False)
    project = db.relationship("Project", back_populates="requirements")


class ScopeItem(BaseModel):
    __tablename__ = "scope_item"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    hours = db.Column(db.Numeric(10, 2), default=Decimal("0"), nullable=False)
    rate = db.Column(db.Numeric(14, 2), default=Decimal("0"), nullable=False)
    complexity = db.Column(db.String(30), default="medium", nullable=False)
    priority = db.Column(db.String(30), default="medium", nullable=False)
    dependencies = db.Column(db.Text, default="", nullable=False)
    acceptance_criteria = db.Column(db.Text, default="", nullable=False)
    included = db.Column(db.Boolean, default=True, nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False)
    project = db.relationship("Project", back_populates="scope_items")


class ProjectMilestone(BaseModel):
    __tablename__ = "project_milestone"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    title = db.Column(db.String(200), nullable=False)
    due_at = db.Column(db.DateTime, index=True)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    project = db.relationship("Project", back_populates="milestones")


class Task(BaseModel):
    __tablename__ = "task"
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    stage_number = db.Column(db.Integer)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(30), default="backlog", nullable=False, index=True)
    priority = db.Column(db.String(30), default="normal", nullable=False)
    due_at = db.Column(db.DateTime, index=True)
    estimated_hours = db.Column(db.Numeric(10, 2), default=Decimal("0"), nullable=False)
    actual_hours = db.Column(db.Numeric(10, 2), default=Decimal("0"), nullable=False)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    completed_at = db.Column(db.DateTime)
    event_key = db.Column(db.String(255), unique=True)
    project = db.relationship("Project", back_populates="tasks")
    client = db.relationship("Client")
    assigned_user = db.relationship("User")
    dependencies = db.relationship(
        "TaskDependency", foreign_keys="TaskDependency.task_id", back_populates="task"
    )

    @property
    def is_overdue(self):
        return bool(
            self.due_at
            and self.due_at < utcnow()
            and self.status not in {"completed", "done", "canceled"}
        )


class TaskDependency(BaseModel):
    __tablename__ = "task_dependency"
    __table_args__ = (
        db.UniqueConstraint("task_id", "depends_on_id"),
        db.CheckConstraint("task_id != depends_on_id", name="no_self_dependency"),
    )
    task_id = db.Column(
        db.Integer, db.ForeignKey("task.id"), nullable=False, index=True
    )
    depends_on_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    task = db.relationship(
        "Task", foreign_keys=[task_id], back_populates="dependencies"
    )
    depends_on = db.relationship("Task", foreign_keys=[depends_on_id])


class Approval(BaseModel):
    __tablename__ = "approval"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    stage_number = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(100), nullable=False, index=True)
    decision = db.Column(db.String(30), nullable=False, default="approved")
    person = db.Column(db.String(200), nullable=False)
    evidence = db.Column(db.Text, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    project = db.relationship("Project", back_populates="approvals")
    actor = db.relationship("User")


class ActivityLog(BaseModel):
    __tablename__ = "activity_log"
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    action = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    client = db.relationship("Client")
    project = db.relationship("Project")


class AuditLog(BaseModel):
    __tablename__ = "audit_log"
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(120), nullable=False)
    entity = db.Column(db.String(100), nullable=False)
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text, default="", nullable=False)
    actor = db.relationship("User")


class ApplicationSetting(BaseModel):
    __tablename__ = "application_setting"
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.Text, default="", nullable=False)


class Notification(BaseModel):
    __tablename__ = "notification"
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="", nullable=False)
    read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), index=True)
    project = db.relationship("Project")


@event.listens_for(Approval, "before_update")
@event.listens_for(Approval, "before_delete")
def protect_approval(mapper, connection, target):
    raise ValueError("Approval records are immutable. Record a new decision instead.")


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def protect_audit(mapper, connection, target):
    raise ValueError("Audit records are immutable.")
