"""CRM and lifecycle interfaces with shared forms and transactional services."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from uuid import uuid4
from flask import Blueprint, render_template, request, redirect, flash, abort, jsonify
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (
    User,
    Lead,
    Client,
    Contact,
    Inquiry,
    Project,
    ProjectStage,
    Requirement,
    ScopeItem,
    ProjectMilestone,
    Task,
    TaskDependency,
    Approval,
    ActivityLog,
)
from app.models.base import utcnow
from app.services.common import admin_required, log_activity, audit
from app.services.lifecycle_service import (
    STAGE_MAP,
    create_project,
    complete_stage,
    transition,
    blockers,
)

bp = Blueprint("crm", __name__)
LEAD_STATUSES = [
    "new",
    "contacted",
    "awaiting_response",
    "qualified",
    "consultation_scheduled",
    "proposal_requested",
    "converted",
    "lost",
    "archived",
]
TASK_STATUSES = [
    "backlog",
    "ready",
    "in_progress",
    "blocked",
    "in_review",
    "testing",
    "completed",
    "canceled",
]
QUESTIONNAIRE = [
    "Business name",
    "Products or services",
    "Website purpose",
    "Target audience",
    "Existing website",
    "Pages required",
    "Features required",
    "Customer accounts",
    "Online payments",
    "Appointment scheduling",
    "Brand identity",
    "Domain ownership",
    "Hosting",
    "Target budget",
    "Target completion date",
]


@bp.before_request
@login_required
@admin_required
def authorize():
    pass


def payload():
    data = request.get_json(silent=True) if request.is_json else request.form
    if not hasattr(data, "get"):
        raise ValueError("Supply an object containing the form fields.")
    return data


def field(name, label=None, type="text", required=False, options=None, value=""):
    return dict(
        name=name,
        label=label or name.replace("_", " ").title(),
        type=type,
        required=required,
        options=options,
        value=value,
    )


def text(data, key, required=False, limit=20000):
    value = str(data.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"{key.replace('_', ' ').title()} is required.")
    if len(value) > limit:
        raise ValueError(f"{key.replace('_', ' ').title()} is too long.")
    return value


def email_value(data):
    from email_validator import validate_email, EmailNotValidError

    value = text(data, "email")
    if value:
        try:
            return validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc
    return ""


def number_value(data, key, default="0"):
    try:
        value = Decimal(str(data.get(key, default) or default))
    except InvalidOperation as exc:
        raise ValueError(f"{key} must be a number.") from exc
    if not value.is_finite() or value < 0 or value > Decimal("9999999999"):
        raise ValueError(f"{key} must be a finite nonnegative number.")
    return value.quantize(Decimal(".01"))


def date_value(data, key):
    raw = str(data.get(key, "")).strip()
    if not raw:
        return None
    try:
        from app.services.reporting_service import business_timezone

        value = datetime.fromisoformat(raw)
        if value.tzinfo is None:
            value = value.replace(tzinfo=business_timezone())
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(f"{key.replace('_', ' ')} needs a valid date.") from exc


def local_input_date(value):
    from app.services.reporting_service import local_date

    return local_date(value).isoformat() if value else ""


def mutation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, InvalidOperation) as exc:
            db.session.rollback()
            if request.is_json:
                return jsonify(error=str(exc)), 400
            return render_template("crm/error.html", message=str(exc)), 400
        except IntegrityError:
            db.session.rollback()
            if request.is_json:
                return jsonify(
                    error="This operation conflicts with an existing record."
                ), 409
            return render_template(
                "crm/error.html",
                message="This operation conflicts with an existing record. Refresh and try again.",
            ), 409

    return wrapped


def save_redirect(path, message="Saved successfully."):
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, url=path)
    flash(message, "success")
    return redirect(path)


def options(model, attr="name"):
    return [
        (str(x.id), getattr(x, attr))
        for x in model.query.order_by(model.id.desc()).all()
    ]


def selected(data, key, model, required=True):
    raw = data.get(key)
    if not raw and not required:
        return None
    try:
        row = db.session.get(model, int(raw))
    except (ValueError, TypeError):
        row = None
    if row is None:
        raise ValueError(f"Select a valid {key.replace('_id', '')} record.")
    return row


def list_page(title, rows, columns, base, subtitle=""):
    return render_template(
        "list.html",
        title=title,
        subtitle=subtitle,
        rows=rows,
        columns=columns,
        new_url=base + "/new",
        detail_url=lambda row: f"{base}/{row.id}",
    )


@bp.route("/leads")
def leads():
    query = Lead.query
    if request.args.get("q"):
        term = "%" + request.args["q"][:100] + "%"
        query = query.filter(
            or_(
                Lead.name.ilike(term),
                Lead.business_name.ilike(term),
                Lead.email.ilike(term),
            )
        )
    if request.args.get("status") in LEAD_STATUSES:
        query = query.filter_by(status=request.args["status"])
    return list_page(
        "Lead pipeline",
        query.order_by(Lead.created_at.desc()).all(),
        [
            ("reference", "Reference"),
            ("business_name", "Business"),
            ("name", "Contact"),
            ("email", "Email"),
            ("source", "Source"),
            ("status", "Status"),
        ],
        "/leads",
        "Turn good conversations into lasting client relationships.",
    )


@bp.route("/leads/new", methods=["GET", "POST"])
@bp.route("/leads/<int:lead_id>/edit", methods=["GET", "POST"])
@mutation
def lead_form(lead_id=None):
    lead = (
        db.get_or_404(Lead, lead_id)
        if lead_id
        else Lead(reference="LEAD-" + uuid4().hex[:8].upper(), status="new")
    )
    if request.method == "POST":
        data = payload()
        if lead.client_id:
            raise ValueError(
                "This lead has been converted. Edit its client profile instead."
            )
        for key in [
            "name",
            "business_name",
            "phone",
            "website",
            "industry",
            "location",
            "source",
            "service",
            "notes",
        ]:
            setattr(lead, key, text(data, key, key in ["name", "business_name"]))
        lead.email = email_value(data)
        lead.budget = number_value(data, "budget")
        lead.follow_up_at, lead.desired_date = (
            date_value(data, "follow_up_at"),
            date_value(data, "desired_date"),
        )
        status = data.get("status", "new")
        if status not in LEAD_STATUSES or status == "converted":
            raise ValueError(
                "Choose a valid status. Use Confirm conversion to convert a lead."
            )
        lead.status = status
        db.session.add(lead)
        db.session.flush()
        if not lead_id:
            db.session.add(
                Task(
                    title=f"Qualify lead: {lead.business_name}",
                    status="backlog",
                    priority="normal",
                    event_key=f"lead:{lead.id}:qualify",
                )
            )
            from app.services.email_service import draft_email

            # Draft generation is local and never sends mail.
            if lead.email:
                try:
                    draft_email(
                        event_key=f"lead:{lead.id}:introduction",
                        recipient=lead.email,
                        subject=f"Website consultation for {lead.business_name}",
                        body=f"Hello {lead.name},\n\nThank you for your interest. Could you share your website goals and availability for a consultation?\n\nBest regards",
                    )
                except TypeError:
                    # Integration is finalized using the service signature during validation.
                    raise ValueError(
                        "Email draft creation could not be completed. Please retry after checking email configuration."
                    )
        log_activity("lead.saved", f"Saved {lead.reference}", client_id=lead.client_id)
        return save_redirect(f"/leads/{lead.id}")
    fields = [
        field(
            k,
            required=k in ("name", "business_name"),
            type="textarea" if k == "notes" else "email" if k == "email" else "text",
            value=getattr(lead, k, None) or "",
        )
        for k in [
            "name",
            "business_name",
            "email",
            "phone",
            "website",
            "industry",
            "location",
            "source",
            "service",
            "notes",
        ]
    ]
    fields += [
        field("budget", type="number", value=lead.budget or ""),
        field(
            "desired_date",
            type="date",
            value=local_input_date(lead.desired_date) if lead.desired_date else "",
        ),
        field(
            "follow_up_at",
            type="date",
            value=local_input_date(lead.follow_up_at) if lead.follow_up_at else "",
        ),
        field(
            "status",
            type="select",
            options=[
                (x, x.replace("_", " ").title())
                for x in LEAD_STATUSES
                if x != "converted"
            ],
            value=lead.status,
        ),
    ]
    return render_template(
        "form.html",
        title="Edit lead" if lead_id else "New opportunity",
        fields=fields,
        submit_label="Save lead",
    )


@bp.route("/leads/<int:lead_id>")
def lead_detail(lead_id):
    return render_template("crm/lead.html", lead=db.get_or_404(Lead, lead_id))


@bp.post("/leads/<int:lead_id>/convert")
@mutation
def convert_lead(lead_id):
    lead = db.get_or_404(Lead, lead_id)
    if lead.client_id:
        return redirect(f"/clients/{lead.client_id}")
    if payload().get("confirmed") != "yes":
        raise ValueError("Confirm the lead conversion deliberately.")
    if lead.status not in ("qualified", "consultation_scheduled", "proposal_requested"):
        raise ValueError("Qualify the lead before converting it.")
    client = Client(
        reference="CLI-" + uuid4().hex[:8].upper(),
        lead_id=lead.id,
        status="active",
        **{
            k: getattr(lead, k)
            for k in [
                "name",
                "business_name",
                "email",
                "phone",
                "website",
                "industry",
                "location",
                "notes",
            ]
        },
    )
    db.session.add(client)
    db.session.flush()
    lead.client_id, lead.status = client.id, "converted"
    from app.models import EmailDraft

    for draft in EmailDraft.query.filter_by(event_key=f"lead:{lead.id}:introduction"):
        draft.client_id = client.id
    for inquiry in Inquiry.query.filter_by(lead_id=lead.id):
        inquiry.client_id = client.id
    log_activity(
        "lead.converted",
        f"{lead.reference} converted with administrator confirmation",
        client_id=client.id,
    )
    audit("convert", "lead", lead.id, "Administrator confirmed conversion")
    return save_redirect(
        f"/clients/{client.id}",
        "Lead converted; its inquiry and communication history is retained.",
    )


@bp.route("/clients")
def clients():
    query = Client.query
    if request.args.get("q"):
        query = query.filter(
            or_(
                Client.name.ilike("%" + request.args["q"][:100] + "%"),
                Client.business_name.ilike("%" + request.args["q"][:100] + "%"),
            )
        )
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return list_page(
        "Clients",
        query.order_by(Client.created_at.desc()).all(),
        [
            ("reference", "Reference"),
            ("business_name", "Business"),
            ("name", "Contact"),
            ("email", "Email"),
            ("status", "Status"),
        ],
        "/clients",
        "All your client relationships, in one place.",
    )


@bp.route("/clients/new", methods=["GET", "POST"])
@bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@mutation
def client_form(client_id=None):
    client = (
        db.get_or_404(Client, client_id)
        if client_id
        else Client(reference="CLI-" + uuid4().hex[:8].upper(), status="active")
    )
    if request.method == "POST":
        data = payload()
        for key in [
            "name",
            "business_name",
            "phone",
            "website",
            "industry",
            "location",
            "notes",
        ]:
            setattr(client, key, text(data, key, key in ("name", "business_name")))
        client.email = email_value(data)
        db.session.add(client)
        db.session.flush()
        log_activity(
            "client.saved", f"Saved client {client.reference}", client_id=client.id
        )
        return save_redirect(f"/clients/{client.id}")
    return render_template(
        "form.html",
        title="Edit client" if client_id else "New client",
        fields=[
            field(
                k,
                required=k in ("name", "business_name"),
                type="textarea"
                if k == "notes"
                else "email"
                if k == "email"
                else "text",
                value=getattr(client, k, None) or "",
            )
            for k in [
                "name",
                "business_name",
                "email",
                "phone",
                "website",
                "industry",
                "location",
                "notes",
            ]
        ],
        submit_label="Save client",
    )


@bp.route("/clients/<int:client_id>")
def client_detail(client_id):
    from app.models import (
        Invoice,
        Proposal,
        Contract,
        Document,
        SupportTicket,
        MaintenanceAgreement,
    )

    client = db.get_or_404(Client, client_id)
    projects = Project.query.filter_by(client_id=client.id).all()
    ids = [p.id for p in projects]
    related = {}
    for key, model in [
        ("Invoices", Invoice),
        ("Proposals", Proposal),
        ("Contracts", Contract),
        ("Documents", Document),
        ("Support tickets", SupportTicket),
        ("Maintenance", MaintenanceAgreement),
    ]:
        related[key] = (
            model.query.filter(model.project_id.in_(ids)).all()
            if ids and hasattr(model, "project_id")
            else []
        )
    return render_template(
        "crm/client.html",
        client=client,
        projects=projects,
        related=related,
        contacts=Contact.query.filter_by(client_id=client.id).all(),
        inquiries=Inquiry.query.filter_by(client_id=client.id).all(),
        activity=ActivityLog.query.filter_by(client_id=client.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(100)
        .all(),
    )


@bp.post("/clients/<int:client_id>/archive")
@mutation
def archive_client(client_id):
    client = db.get_or_404(Client, client_id)
    if payload().get("confirmed") != "yes":
        raise ValueError("Confirm this archival action.")
    if Project.query.filter_by(client_id=client.id, status="active").first():
        raise ValueError(
            "Pause, close, or cancel active projects before archiving their client."
        )
    client.status = "active" if client.status == "archived" else "archived"
    audit("archive", "client", client.id, client.status)
    return save_redirect(f"/clients/{client.id}")


@bp.post("/clients/<int:client_id>/contacts")
@mutation
def add_contact(client_id):
    db.get_or_404(Client, client_id)
    data = payload()
    db.session.add(
        Contact(
            client_id=client_id,
            name=text(data, "name", True),
            email=email_value(data),
            phone=text(data, "phone"),
            role=text(data, "role"),
        )
    )
    return save_redirect(f"/clients/{client_id}")


@bp.route("/inquiries")
def inquiries():
    return list_page(
        "Inquiries",
        Inquiry.query.order_by(Inquiry.created_at.desc()).all(),
        [
            ("reference", "Reference"),
            ("website_type", "Website type"),
            ("budget", "Budget"),
            ("status", "Status"),
        ],
        "/inquiries",
    )


@bp.route("/inquiries/new", methods=["GET", "POST"])
@bp.route("/inquiries/<int:inquiry_id>", methods=["GET", "POST"])
@mutation
def inquiry_form(inquiry_id=None):
    inquiry = (
        db.get_or_404(Inquiry, inquiry_id)
        if inquiry_id
        else Inquiry(
            reference="INQ-" + uuid4().hex[:8].upper(), status="draft", answers={}
        )
    )
    if request.method == "POST":
        data = payload()
        client = selected(data, "client_id", Client, False)
        lead = selected(data, "lead_id", Lead, False)
        if not client and not lead:
            raise ValueError("Associate the inquiry with a lead or a client.")
        inquiry.client_id = client.id if client else None
        inquiry.lead_id = lead.id if lead else None
        for key in [
            "website_type",
            "business_description",
            "features",
            "communication",
            "notes",
        ]:
            setattr(inquiry, key, text(data, key, key == "website_type"))
        inquiry.budget = number_value(data, "budget")
        inquiry.desired_date = date_value(data, "desired_date")
        inquiry.answers = {
            str(i): text(data, f"question_{i}") for i in range(len(QUESTIONNAIRE))
        }
        inquiry.status = (
            "complete" if all(inquiry.answers.values()) else "missing_information"
        )
        db.session.add(inquiry)
        db.session.flush()
        event = f"inquiry:{inquiry.id}:missing"
        if (
            inquiry.status == "missing_information"
            and not Task.query.filter_by(event_key=event).first()
        ):
            db.session.add(
                Task(
                    client_id=inquiry.client_id,
                    title=f"Complete questionnaire {inquiry.reference}",
                    status="backlog",
                    priority="normal",
                    event_key=event,
                )
            )
        log_activity(
            "inquiry.saved",
            f"Recorded {inquiry.reference}",
            client_id=inquiry.client_id,
        )
        return save_redirect("/inquiries")
    fields = [
        field(
            "client_id",
            type="select",
            options=[("", "Select client")] + options(Client, "business_name"),
            value=inquiry.client_id or "",
        ),
        field(
            "lead_id",
            type="select",
            options=[("", "Select lead")] + options(Lead, "business_name"),
            value=inquiry.lead_id or "",
        ),
    ]
    fields += [
        field(
            k,
            type="date"
            if k == "desired_date"
            else "textarea"
            if k in ("notes", "features", "business_description")
            else "text",
            required=k == "website_type",
            value=local_input_date(inquiry.desired_date)
            if k == "desired_date"
            else getattr(inquiry, k, None) or "",
        )
        for k in [
            "website_type",
            "business_description",
            "features",
            "budget",
            "desired_date",
            "communication",
            "notes",
        ]
    ]
    fields += [
        field(
            f"question_{i}",
            label,
            type="textarea",
            value=(inquiry.answers or {}).get(str(i), ""),
        )
        for i, label in enumerate(QUESTIONNAIRE)
    ]
    return render_template(
        "form.html",
        title="Inquiry questionnaire",
        fields=fields,
        submit_label="Save questionnaire",
    )


@bp.route("/projects")
def projects():
    query = Project.query
    if request.args.get("q"):
        query = query.filter(Project.title.ilike("%" + request.args["q"][:100] + "%"))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    return list_page(
        "Projects",
        query.order_by(Project.created_at.desc()).all(),
        [
            ("reference", "Reference"),
            ("title", "Project"),
            ("current_stage", "Stage"),
            ("contract_value", "Contract value"),
            ("deadline", "Deadline"),
            ("status", "Status"),
        ],
        "/projects",
        "A clear path from first conversation to final handover.",
    )


@bp.route("/projects/new", methods=["GET", "POST"])
@mutation
def project_form():
    if request.method == "POST":
        data = payload()
        client = selected(data, "client_id", Client)
        project = create_project(
            client, text(data, "title", True), text(data, "description")
        )
        project.deadline = date_value(data, "deadline")
        project.revision_allowance = int(data.get("revision_allowance", 2))
        if not 0 <= project.revision_allowance <= 100:
            raise ValueError("Revision allowance must be between 0 and 100.")
        return save_redirect(f"/projects/{project.id}")
    return render_template(
        "form.html",
        title="New project",
        fields=[
            field(
                "client_id",
                type="select",
                required=True,
                options=options(Client, "business_name"),
                value=request.args.get("client_id", ""),
            ),
            field("title", required=True),
            field("description", type="textarea"),
            field("deadline", type="date"),
            field("revision_allowance", type="number", value=2),
        ],
        submit_label="Create project",
    )


@bp.route("/projects/<int:project_id>")
@bp.route("/projects/<int:project_id>/lifecycle")
def project_detail(project_id):
    project = db.get_or_404(Project, project_id)
    number = request.args.get("stage", project.current_stage, type=int)
    if number not in STAGE_MAP:
        abort(404)
    stage = ProjectStage.query.filter_by(
        project_id=project.id, number=number
    ).first_or_404()
    return render_template(
        "crm/project.html",
        project=project,
        stage=stage,
        definition=STAGE_MAP[number],
        definitions=STAGE_MAP,
        stages=ProjectStage.query.filter_by(project_id=project.id)
        .order_by(ProjectStage.number)
        .all(),
        requirements=Requirement.query.filter_by(
            project_id=project.id, stage_number=number
        ).all(),
        blockers=blockers(project, number) if stage.status != "completed" else [],
        approvals=Approval.query.filter_by(project_id=project.id, stage_number=number)
        .order_by(Approval.id.desc())
        .all(),
        tasks=Task.query.filter_by(project_id=project.id, stage_number=number).all(),
        milestones=ProjectMilestone.query.filter_by(project_id=project.id).all(),
        activity=ActivityLog.query.filter_by(project_id=project.id)
        .order_by(ActivityLog.id.desc())
        .limit(30)
        .all(),
    )


@bp.post("/projects/<int:project_id>/stages/<int:number>")
@mutation
def save_stage(project_id, number):
    project = db.get_or_404(Project, project_id)
    stage = ProjectStage.query.filter_by(
        project_id=project.id, number=number
    ).first_or_404()
    if stage.status == "completed":
        raise ValueError("Reopen this stage before changing its approved information.")
    data = payload()
    stage.data = {
        **(stage.data or {}),
        **{key: text(data, key) for key, label in STAGE_MAP[number]["fields"]},
        "notes": text(data, "notes"),
    }
    for requirement in Requirement.query.filter_by(
        project_id=project.id, stage_number=number
    ):
        requirement.completed = data.get(f"requirement_{requirement.id}") in (
            "on",
            "yes",
            True,
        )
        requirement.exception = text(data, f"exception_{requirement.id}")
    stage.status = "draft"
    # Editing previously approved work requires a fresh decision.
    stage.data = {**stage.data, "_invalidated_at": utcnow().isoformat()}
    log_activity(
        "stage.saved",
        f"Updated {stage.title}",
        project_id=project.id,
        client_id=project.client_id,
    )
    return save_redirect(f"/projects/{project.id}?stage={number}")


@bp.post("/projects/<int:project_id>/stages/<int:number>/submit")
@mutation
def submit_stage(project_id, number):
    db.get_or_404(Project, project_id)
    stage = ProjectStage.query.filter_by(
        project_id=project_id, number=number
    ).first_or_404()
    if stage.status == "completed":
        raise ValueError("This stage is already completed.")
    missing = [
        label
        for key, label in STAGE_MAP[number]["fields"]
        if not str((stage.data or {}).get(key, "")).strip()
    ]
    if missing:
        raise ValueError("Complete these fields first: " + ", ".join(missing))
    stage.status = "submitted"
    return save_redirect(f"/projects/{project_id}?stage={number}")


@bp.post("/projects/<int:project_id>/stages/<int:number>/complete")
@mutation
def finish_stage(project_id, number):
    project = db.get_or_404(Project, project_id)
    complete_stage(project, number, current_user.id)
    return save_redirect(f"/projects/{project.id}", "Stage completed after validation.")


@bp.post("/projects/<int:project_id>/approvals")
@mutation
def approval(project_id):
    project = db.get_or_404(Project, project_id)
    data = payload()
    number = int(data.get("stage_number", project.current_stage))
    if number not in STAGE_MAP:
        raise ValueError("Choose a valid stage.")
    kind = data.get("kind", "stage")
    if kind not in (
        "stage",
        "scope",
        "proposal",
        "contract",
        "design",
        "acceptance",
        "launch",
        "handover",
    ):
        raise ValueError("Choose a supported approval type.")
    decision = data.get("decision", "approved")
    if decision not in ("approved", "rejected"):
        raise ValueError("Choose approve or reject.")
    db.session.add(
        Approval(
            project_id=project.id,
            stage_number=number,
            kind=kind,
            decision=decision,
            person=text(data, "person", True),
            evidence=text(data, "evidence", True),
            actor_id=current_user.id,
        )
    )
    stage = ProjectStage.query.filter_by(project_id=project.id, number=number).first()
    if stage.status == "completed":
        raise ValueError("Reopen a completed stage before recording a new decision.")
    if kind == "stage":
        stage.status = decision
    log_activity(
        "approval.recorded",
        f"{kind.title()} {decision}; evidence recorded",
        project_id=project.id,
        client_id=project.client_id,
    )
    audit("approval", "project", project.id, f"{kind}: {decision}")
    return save_redirect(f"/projects/{project.id}?stage={number}")


@bp.post("/projects/<int:project_id>/transition")
@mutation
def reopen(project_id):
    project = db.get_or_404(Project, project_id)
    data = payload()
    transition(
        project, int(data.get("target", 0)), text(data, "reason", True), current_user.id
    )
    return save_redirect(f"/projects/{project.id}")


@bp.post("/projects/<int:project_id>/status")
@mutation
def project_status(project_id):
    project = db.get_or_404(Project, project_id)
    status = payload().get("status")
    if status not in ("active", "paused", "canceled"):
        raise ValueError(
            "Choose active, paused or canceled. Completion requires the lifecycle checks."
        )
    if project.status == "completed":
        raise ValueError("Reopen an earlier stage before changing a completed project.")
    project.status = status
    log_activity(
        "project.status",
        f"Project {status}",
        project_id=project.id,
        client_id=project.client_id,
    )
    return save_redirect(f"/projects/{project.id}")


@bp.route("/projects/<int:project_id>/scope", methods=["GET", "POST"])
@mutation
def scope(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        stage = ProjectStage.query.filter_by(project_id=project.id, number=4).first()
        if stage.status == "completed":
            raise ValueError(
                "Reopen scope planning to revise the approved scope; its approval history is preserved."
            )
        data = payload()
        item = ScopeItem(
            project_id=project.id,
            name=text(data, "name", True),
            description=text(data, "description"),
            hours=number_value(data, "hours"),
            rate=number_value(data, "rate"),
            complexity=text(data, "complexity") or "medium",
            priority=text(data, "priority") or "normal",
            dependencies=text(data, "dependencies"),
            acceptance_criteria=text(data, "acceptance_criteria", True),
            included=data.get("included") in ("yes", "on", True),
            status="draft",
        )
        db.session.add(item)
        stage.data = {**(stage.data or {}), "_invalidated_at": utcnow().isoformat()}
        return save_redirect(f"/projects/{project.id}/scope")
    items = ScopeItem.query.filter_by(project_id=project.id).all()
    return render_template(
        "crm/scope.html",
        project=project,
        items=items,
        total_hours=sum((x.hours for x in items if x.included), Decimal("0")),
    )


@bp.post("/projects/<int:project_id>/milestones")
@mutation
def milestone(project_id):
    project = db.get_or_404(Project, project_id)
    data = payload()
    db.session.add(
        ProjectMilestone(
            project_id=project.id,
            title=text(data, "title", True),
            due_at=date_value(data, "due_at"),
            completed=False,
        )
    )
    return save_redirect(f"/projects/{project.id}")


@bp.route("/tasks")
@bp.route("/projects/<int:project_id>/development")
def tasks(project_id=None):
    project = db.get_or_404(Project, project_id) if project_id else None
    query = Task.query.filter_by(project_id=project_id) if project else Task.query
    rows = query.order_by(Task.id.desc()).all()
    total = sum(
        (task.estimated_hours for task in rows if task.status != "canceled"),
        Decimal("0"),
    )
    done = sum(
        (task.estimated_hours for task in rows if task.status == "completed"),
        Decimal("0"),
    )
    progress = round(done / total * 100) if total else 0
    return render_template(
        "crm/tasks.html",
        tasks=rows,
        statuses=TASK_STATUSES,
        project=project,
        projects=Project.query.all(),
        progress=progress,
        total_hours=total,
    )


@bp.route("/tasks/new", methods=["GET", "POST"])
@bp.route("/tasks/<int:task_id>", methods=["GET", "POST"])
@mutation
def task_form(task_id=None):
    task = (
        db.get_or_404(Task, task_id)
        if task_id
        else Task(
            status="backlog", priority="normal", estimated_hours=0, actual_hours=0
        )
    )
    if request.method == "POST":
        data = payload()
        project = selected(data, "project_id", Project, False)
        task.project_id = project.id if project else None
        task.client_id = project.client_id if project else None
        task.title = text(data, "title", True)
        task.description = text(data, "description")
        assignee = selected(data, "assigned_user_id", User, False)
        if assignee and (not assignee.active or assignee.role != "admin"):
            raise ValueError("Assign tasks to an active workspace administrator.")
        task.assigned_user_id = assignee.id if assignee else None
        task.priority = data.get("priority", "normal")
        if task.priority not in ("low", "normal", "high", "urgent"):
            raise ValueError("Choose a valid priority.")
        task.due_at = date_value(data, "due_at")
        task.estimated_hours, task.actual_hours = (
            number_value(data, "estimated_hours"),
            number_value(data, "actual_hours"),
        )
        task.stage_number = int(data.get("stage_number") or 9) if project else None
        if task.stage_number and task.stage_number not in STAGE_MAP:
            raise ValueError("Choose a valid stage number.")
        status = data.get("status", "backlog")
        if status not in TASK_STATUSES:
            raise ValueError("Choose a valid task status.")
        if status == "completed" and task_id:
            check_dependencies(task)
        task.status = status
        task.completed_at = utcnow() if status == "completed" else None
        db.session.add(task)
        return save_redirect("/tasks")
    fields = [
        field("title", required=True, value=task.title or ""),
        field("description", type="textarea", value=task.description or ""),
        field(
            "project_id",
            type="select",
            options=[("", "Internal task")] + options(Project, "title"),
            value=task.project_id or request.args.get("project_id", ""),
        ),
        field(
            "stage_number",
            type="select",
            options=[(str(i), v["title"]) for i, v in STAGE_MAP.items()],
            value=task.stage_number or 9,
        ),
        field(
            "assigned_user_id",
            label="Assigned to",
            type="select",
            options=[("", "Unassigned")]
            + [
                (str(u.id), u.name)
                for u in User.query.filter_by(active=True, role="admin")
            ],
            value=task.assigned_user_id or "",
        ),
        field(
            "status",
            type="select",
            options=[(x, x.replace("_", " ").title()) for x in TASK_STATUSES],
            value=task.status,
        ),
        field(
            "priority",
            type="select",
            options=[(x, x.title()) for x in ["low", "normal", "high", "urgent"]],
            value=task.priority,
        ),
        field(
            "due_at",
            type="date",
            value=local_input_date(task.due_at) if task.due_at else "",
        ),
        field("estimated_hours", type="number", value=task.estimated_hours),
        field("actual_hours", type="number", value=task.actual_hours),
    ]
    return render_template(
        "crm/task_form.html",
        title="Edit task" if task_id else "New task",
        fields=fields,
        submit_label="Save task",
        task=task,
        dependency_options=Task.query.filter(
            Task.project_id == task.project_id, Task.id != task.id
        ).all()
        if task_id
        else [],
        dependencies=TaskDependency.query.filter_by(task_id=task.id).all()
        if task_id
        else [],
    )


def check_dependencies(task):
    for dependency in TaskDependency.query.filter_by(task_id=task.id):
        if db.session.get(Task, dependency.depends_on_id).status != "completed":
            raise ValueError("Complete prerequisite tasks first.")


@bp.post("/tasks/<int:task_id>/status")
@mutation
def task_status(task_id):
    task = db.get_or_404(Task, task_id)
    status = payload().get("status")
    if status not in TASK_STATUSES:
        raise ValueError("Unknown task status.")
    if status == "completed":
        check_dependencies(task)
    task.status = status
    task.completed_at = utcnow() if status == "completed" else None
    log_activity(
        "task.status",
        f"{task.title}: {status}",
        project_id=task.project_id,
        client_id=task.client_id,
    )
    return save_redirect("/tasks")


@bp.post("/tasks/<int:task_id>/dependencies")
@mutation
def task_dependency(task_id):
    task = db.get_or_404(Task, task_id)
    dependency = selected(payload(), "depends_on_id", Task)
    if task.project_id != dependency.project_id:
        raise ValueError("Dependencies must belong to the same project.")
    visited = set()

    def reaches(current):
        if current == task.id:
            return True
        if current in visited:
            return False
        visited.add(current)
        return any(
            reaches(x.depends_on_id)
            for x in TaskDependency.query.filter_by(task_id=current)
        )

    if reaches(dependency.id):
        raise ValueError("This dependency would create a cycle.")
    db.session.add(TaskDependency(task_id=task.id, depends_on_id=dependency.id))
    return save_redirect(f"/tasks/{task.id}")


@bp.post("/projects/<int:project_id>/milestones/<int:milestone_id>")
@mutation
def complete_milestone(project_id, milestone_id):
    db.get_or_404(Project, project_id)
    milestone = ProjectMilestone.query.filter_by(
        id=milestone_id, project_id=project_id
    ).first_or_404()
    milestone.completed = payload().get("completed") == "yes"
    log_activity(
        "milestone.updated",
        f"Milestone {milestone.title}: {'completed' if milestone.completed else 'reopened'}",
        project_id=project_id,
    )
    return save_redirect(f"/projects/{project_id}")


@bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@mutation
def project_edit(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        data = payload()
        if project.status == "completed":
            raise ValueError("Reopen the project before changing its details.")
        project.title = text(data, "title", True)
        project.description = text(data, "description")
        project.deadline = date_value(data, "deadline")
        for key in ("repository_url", "staging_url"):
            value = text(data, key)
            if value:
                from urllib.parse import urlsplit

                parsed = urlsplit(value)
                if (
                    parsed.scheme not in ("https", "http")
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError(
                        "References must be HTTP(S) URLs without embedded credentials."
                    )
            setattr(project, key, value)
        audit(
            "edit", "project", project.id, "Updated project references and description"
        )
        return save_redirect(f"/projects/{project.id}")
    fields = [
        field("title", required=True, value=project.title),
        field("description", type="textarea", value=project.description),
        field(
            "deadline",
            type="date",
            value=local_input_date(project.deadline) if project.deadline else "",
        ),
        field("repository_url", type="url", value=project.repository_url),
        field("staging_url", type="url", value=project.staging_url),
    ]
    return render_template(
        "form.html",
        title="Project settings",
        fields=fields,
        submit_label="Save project",
    )
