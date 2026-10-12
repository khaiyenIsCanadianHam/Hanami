"""Authenticated discovery, delivery and aftercare workspaces."""

from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
from flask import Blueprint, flash, jsonify, redirect, render_template, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.base import money, utcnow
from app.models.core import Project, Task
from app.models.delivery import (
    Meeting,
    MeetingNote,
    DesignSubmission,
    RevisionRequest,
    ChangeRequest,
    TestCase,
    TestExecution,
    BugReport,
    DeploymentRecord,
    HandoverRecord,
    TrainingRecord,
    MaintenanceAgreement,
    MaintenanceTask,
    SupportTicket,
)
from app.services.common import admin_required, audit, log_activity
from app.services.delivery_service import (
    LAUNCH_CHECKS,
    HANDOVER_CHECKS,
    TEST_CATEGORIES,
    SEVERITIES,
    approve_design,
    request_revision,
    decide_change,
    record_test,
    qa_blockers,
    launch_blockers,
    complete_deployment,
    complete_handover,
    seed_test_cases,
    process_recurring_maintenance,
    add_approval,
    event_task,
)

bp = Blueprint("delivery", __name__)


def data():
    return request.get_json() if request.is_json else request.form


def text(name, required=False, limit=10000, default=""):
    value = str(data().get(name, default) or "").strip()
    if required and not value:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} is required.")
    if len(value) > limit:
        raise ValueError(
            f"{name.replace('_', ' ').capitalize()} must be at most {limit} characters."
        )
    return value


def choice(name, options, default=None):
    value = text(name, default=default or "")
    if value not in options:
        raise ValueError(f"Choose a valid {name.replace('_', ' ')}.")
    return value


def checked(name):
    return data().get(name) in (True, "1", "true", "on", "yes")


def integer(name, required=True):
    try:
        value = int(text(name, required))
    except (ValueError, TypeError):
        raise ValueError(f"Choose a valid {name.replace('_', ' ')}.")
    if value <= 0:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} must be positive.")
    return value


def amount(name, default="0"):
    value = money(text(name, default=default))
    if value < 0 or value > Decimal("999999999999.99"):
        raise ValueError(
            f"{name.replace('_', ' ').capitalize()} must be a nonnegative amount within the supported range."
        )
    return value


def when(name, required=False, date_only=False):
    value = text(name, required)
    if not value:
        return None
    try:
        if date_only:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (
            parsed.astimezone(timezone.utc).replace(tzinfo=None)
            if parsed.tzinfo
            else parsed
        )
    except ValueError:
        raise ValueError(
            f"Enter a valid date for {name.replace('_', ' ')}. Times are UTC."
        )


def url(name, required=True):
    value = text(name, required, 2000)
    if not value and not required:
        return ""
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            f"{name.replace('_', ' ').capitalize()} must be an HTTP(S) URL without embedded credentials."
        )
    return value


def record(model, project, field="record_id"):
    return model.query.filter_by(
        id=integer(field), project_id=project.id
    ).first_or_404()


def field(name, label=None, type="text", required=False, options=None, value=None):
    return dict(
        name=name,
        label=label or name.replace("_", " ").capitalize(),
        type=type,
        required=required,
        options=options or [],
        value=value,
    )


def form(title, action, fields, submit="Save", description=""):
    return dict(
        title=title,
        action=action,
        fields=fields,
        submit=submit,
        description=description,
    )


def opts(values):
    return [(v, v.replace("_", " ").capitalize()) for v in values]


def project_opts():
    return [
        (p.id, f"{p.reference} · {p.title}")
        for p in Project.query.order_by(Project.created_at.desc()).all()
    ]


def saved(message, **values):
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, **values)
    flash(message, "success")
    return redirect(request.path)


def workspace(
    title, subtitle, project=None, forms=None, groups=None, blockers=None, summary=None
):
    return render_template(
        "delivery/workspace.html",
        title=title,
        subtitle=subtitle,
        project=project,
        forms=forms or [],
        groups=groups or [],
        blockers=blockers or [],
        summary=summary or [],
    )


def group(title, columns, rows):
    return dict(title=title, columns=columns, rows=rows)


@bp.errorhandler(ValueError)
def validation_error(error):
    db.session.rollback()
    if request.is_json:
        return jsonify(error=str(error)), 400
    return render_template(
        "delivery/error.html", message=str(error), back_url=request.path
    ), 400


@bp.errorhandler(IntegrityError)
def integrity_error(error):
    db.session.rollback()
    message = "This record conflicts with an existing record. Refresh and check the version or name."
    if request.is_json:
        return jsonify(error=message), 400
    return render_template(
        "delivery/error.html", message=message, back_url=request.path
    ), 400


@bp.route("/projects/<int:project_id>/discovery", methods=["GET", "POST"])
@admin_required
def discovery(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        action = text("action", True)
        if action == "meeting":
            meeting = Meeting(
                project_id=project.id,
                title=text("title", True, 200),
                scheduled_at=when("scheduled_at", True),
                participants=text("participants", True),
                agenda=text("agenda", True),
            )
            db.session.add(meeting)
            db.session.flush()
            event_task(
                project,
                f"meeting:{meeting.id}:prepare",
                f"Prepare consultation: {meeting.title}",
                3,
                meeting.scheduled_at,
            )
            log_activity("meeting_scheduled", meeting.title, project_id=project.id)
        elif action == "note":
            meeting = record(Meeting, project, "meeting_id")
            note = MeetingNote(
                meeting_id=meeting.id,
                project_id=project.id,
                category=choice("category", ("note", "decision", "action", "question")),
                body=text("body", True),
                action_owner=text("action_owner", limit=200),
                due_at=when("due_at"),
            )
            db.session.add(note)
            db.session.flush()
            if note.category == "action":
                if not note.action_owner or not note.due_at:
                    raise ValueError("Action notes require an owner and a due date.")
                event_task(
                    project,
                    f"meeting-note:{note.id}",
                    note.body[:200],
                    3,
                    note.due_at,
                    description=f"Owner: {note.action_owner}\n{note.body}",
                )
        elif action == "resolve_note":
            note = record(MeetingNote, project, "note_id")
            note.resolved = True
        elif action == "complete":
            meeting = record(Meeting, project, "meeting_id")
            if meeting.status == "completed":
                raise ValueError("This consultation summary is already finalized.")
            meeting.summary = text("summary", True)
            meeting.status = "completed"
            add_approval(
                project, 3, "stage", current_user.name, meeting.summary, current_user.id
            )
            event_task(
                project,
                f"meeting:{meeting.id}:scope",
                "Prepare scope from reviewed discovery summary",
                4,
                description=meeting.summary,
            )
            log_activity(
                "discovery_reviewed",
                f"Consultation summary approved: {meeting.title}",
                project_id=project.id,
            )
        else:
            raise ValueError("Unknown discovery action.")
        return saved("Discovery record saved.")
    meetings = (
        Meeting.query.filter_by(project_id=project.id)
        .order_by(Meeting.scheduled_at.desc())
        .all()
    )
    meeting_options = [(m.id, m.title) for m in meetings]
    notes = (
        MeetingNote.query.filter_by(project_id=project.id)
        .order_by(MeetingNote.created_at.desc())
        .all()
    )
    forms = [
        form(
            "Schedule a consultation",
            "meeting",
            [
                field("title", required=True),
                field("scheduled_at", "Meeting time (UTC)", "datetime-local", True),
                field("participants", type="textarea", required=True),
                field("agenda", type="textarea", required=True),
            ],
        )
    ]
    if meetings:
        forms += [
            form(
                "Capture decisions and follow-up",
                "note",
                [
                    field("meeting_id", "Meeting", "select", True, meeting_options),
                    field(
                        "category",
                        type="select",
                        options=opts(("note", "decision", "action", "question")),
                    ),
                    field("body", type="textarea", required=True),
                    field("action_owner"),
                    field("due_at", "Due time (UTC)", "datetime-local"),
                ],
            ),
            form(
                "Review discovery summary",
                "complete",
                [
                    field(
                        "meeting_id",
                        "Meeting",
                        "select",
                        True,
                        [(m.id, m.title) for m in meetings if m.status != "completed"],
                    ),
                    field(
                        "summary",
                        "Reviewed business goals, requirements, constraints and open questions",
                        "textarea",
                        True,
                    ),
                ],
                "Confirm reviewed summary",
                "This records administrator review of the requirements summary.",
            ),
        ]
    if any(not n.resolved for n in notes):
        forms.append(
            form(
                "Resolve a follow-up note",
                "resolve_note",
                [
                    field(
                        "note_id",
                        "Note",
                        "select",
                        True,
                        [
                            (n.id, f"{n.category}: {n.body[:80]}")
                            for n in notes
                            if not n.resolved
                        ],
                    )
                ],
            )
        )
    return workspace(
        "Discovery & consultation",
        "Meetings, decisions and a reviewed requirements summary.",
        project,
        forms,
        [
            group(
                "Consultations",
                ["Title", "Scheduled UTC", "Participants", "Status", "Summary"],
                [
                    [m.title, m.scheduled_at, m.participants, m.status, m.summary]
                    for m in meetings
                ],
            ),
            group(
                "Meeting notes",
                ["Category", "Note", "Owner", "Due UTC", "Resolved"],
                [
                    [
                        n.category,
                        n.body,
                        n.action_owner,
                        n.due_at,
                        "Yes" if n.resolved else "No",
                    ]
                    for n in notes
                ],
            ),
        ],
    )


@bp.route("/projects/<int:project_id>/design", methods=["GET", "POST"])
@admin_required
def design(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        action = text("action", True)
        if action == "submit":
            version = (
                db.session.query(db.func.max(DesignSubmission.version))
                .filter_by(project_id=project.id)
                .scalar()
                or 0
            ) + 1
            db.session.add(
                DesignSubmission(
                    project_id=project.id,
                    title=text("title", True, 200),
                    version=version,
                    category=choice(
                        "category",
                        (
                            "sitemap",
                            "wireframe",
                            "mockup",
                            "desktop",
                            "tablet",
                            "mobile",
                        ),
                    ),
                    reference_url=url("reference_url"),
                    description=text("description"),
                )
            )
            log_activity(
                "design_submitted",
                f"Design version {version} submitted for review.",
                project_id=project.id,
            )
        elif action == "approve":
            approve_design(
                record(DesignSubmission, project, "design_id"),
                text("person", True, 200),
                text("evidence", True),
                current_user.id,
            )
        elif action == "revision":
            request_revision(
                record(DesignSubmission, project, "design_id"),
                text("description", True),
                choice("category", ("defect", "included", "out_of_scope")),
            )
        elif action == "resolve_revision":
            revision = record(RevisionRequest, project, "revision_id")
            if revision.status == "completed":
                raise ValueError("This revision is already completed.")
            if not revision.included and (
                not revision.change_request
                or revision.change_request.status != "approved"
            ):
                raise ValueError(
                    "The billable change must be approved before completing this revision."
                )
            revision.resolution = text("resolution", True)
            revision.status = "completed"
            revision.completed_at = utcnow()
        elif action == "change":
            db.session.add(
                ChangeRequest(
                    project_id=project.id,
                    title=text("title", True, 200),
                    description=text("description", True),
                    impact=text("impact", True),
                    estimated_cost=amount("estimated_cost"),
                    estimated_hours=amount("estimated_hours"),
                )
            )
        elif action == "change_estimate":
            change = record(ChangeRequest, project, "change_id")
            if change.status in ("approved", "rejected"):
                raise ValueError(
                    "Finalized changes cannot be edited. Create a new change request."
                )
            change.impact = text("impact", True)
            change.estimated_cost = amount("estimated_cost")
            change.estimated_hours = amount("estimated_hours")
        elif action == "change_decision":
            decide_change(
                record(ChangeRequest, project, "change_id"),
                choice("decision", ("approved", "rejected")),
                text("person", True, 200),
                text("evidence", True),
                current_user.id,
            )
        else:
            raise ValueError("Unknown design action.")
        return saved("Design workspace updated.")
    designs = (
        DesignSubmission.query.filter_by(project_id=project.id)
        .order_by(DesignSubmission.version.desc())
        .all()
    )
    revisions = (
        RevisionRequest.query.filter_by(project_id=project.id)
        .order_by(RevisionRequest.id.desc())
        .all()
    )
    changes = (
        ChangeRequest.query.filter_by(project_id=project.id)
        .order_by(ChangeRequest.id.desc())
        .all()
    )
    design_options = [(d.id, f"v{d.version}: {d.title} ({d.status})") for d in designs]
    pending_changes = [
        (c.id, f"#{c.id}: {c.title}") for c in changes if c.status == "draft"
    ]
    forms = [
        form(
            "Submit a design version",
            "submit",
            [
                field("title", required=True),
                field(
                    "category",
                    type="select",
                    options=opts(
                        (
                            "sitemap",
                            "wireframe",
                            "mockup",
                            "desktop",
                            "tablet",
                            "mobile",
                        )
                    ),
                ),
                field("reference_url", "Design / Figma reference URL", "url", True),
                field("description", type="textarea"),
            ],
        )
    ]
    if designs:
        forms += [
            form(
                "Record explicit design approval",
                "approve",
                [
                    field("design_id", "Design", "select", True, design_options),
                    field("person", "Approving client representative", required=True),
                    field(
                        "evidence",
                        "Written approval evidence / document reference",
                        "textarea",
                        True,
                    ),
                ],
                "Record approval",
            ),
            form(
                "Request a revision",
                "revision",
                [
                    field("design_id", "Design", "select", True, design_options),
                    field(
                        "category",
                        type="select",
                        options=opts(("defect", "included", "out_of_scope")),
                    ),
                    field("description", type="textarea", required=True),
                ],
                description="Each included request consumes one agreed revision round. Requests beyond the allowance become draft changes for price and scope review.",
            ),
        ]
    if any(r.status != "completed" for r in revisions):
        forms.append(
            form(
                "Complete a revision",
                "resolve_revision",
                [
                    field(
                        "revision_id",
                        "Revision",
                        "select",
                        True,
                        [
                            (r.id, f"#{r.round_number}: {r.description[:60]}")
                            for r in revisions
                            if r.status != "completed"
                        ],
                    ),
                    field("resolution", type="textarea", required=True),
                ],
            )
        )
    forms.append(
        form(
            "Draft a scope change",
            "change",
            [
                field("title", required=True),
                field("description", type="textarea", required=True),
                field("impact", "Scope, price and schedule impact", "textarea", True),
                field("estimated_cost", type="number", value="0"),
                field("estimated_hours", type="number", value="0"),
            ],
        )
    )
    if pending_changes:
        forms += [
            form(
                "Estimate a draft change",
                "change_estimate",
                [
                    field("change_id", "Change", "select", True, pending_changes),
                    field(
                        "impact", "Scope, price and schedule impact", "textarea", True
                    ),
                    field("estimated_cost", type="number", required=True),
                    field("estimated_hours", type="number", required=True),
                ],
            ),
            form(
                "Record change decision",
                "change_decision",
                [
                    field("change_id", "Change", "select", True, pending_changes),
                    field(
                        "decision",
                        type="select",
                        options=opts(("approved", "rejected")),
                    ),
                    field("person", required=True),
                    field("evidence", type="textarea", required=True),
                ],
                "Record client decision",
            ),
        ]
    used = sum(1 for r in revisions if r.category == "included" and r.included)
    return workspace(
        "Design & revisions",
        "Versioned designs and evidence-backed client decisions.",
        project,
        forms,
        [
            group(
                "Design versions",
                ["Version", "Title", "Type", "Reference", "Status", "Approved by"],
                [
                    [
                        d.version,
                        d.title,
                        d.category,
                        d.reference_url,
                        d.status,
                        d.approved_by,
                    ]
                    for d in designs
                ],
            ),
            group(
                "Revisions",
                [
                    "Round",
                    "Description",
                    "Category",
                    "Included",
                    "Status",
                    "Resolution",
                ],
                [
                    [
                        r.round_number,
                        r.description,
                        r.category,
                        "Yes" if r.included else "Billable approval needed",
                        r.status,
                        r.resolution,
                    ]
                    for r in revisions
                ],
            ),
            group(
                "Scope changes",
                ["ID", "Title", "Impact", "Estimate", "Hours", "Status"],
                [
                    [
                        c.id,
                        c.title,
                        c.impact,
                        c.estimated_cost,
                        c.estimated_hours,
                        c.status,
                    ]
                    for c in changes
                ],
            ),
        ],
        summary=[
            ("Included revision rounds used", f"{used} / {project.revision_allowance}")
        ],
    )


@bp.route("/projects/<int:project_id>/testing", methods=["GET", "POST"])
@admin_required
def testing(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        action = text("action", True)
        if action == "seed":
            count = seed_test_cases(project)
            return saved(f"{count} standard test cases created for review.")
        if action == "case":
            db.session.add(
                TestCase(
                    project_id=project.id,
                    name=text("name", True, 200),
                    category=choice("category", TEST_CATEGORIES),
                    description=text("description"),
                    preconditions=text("preconditions"),
                    steps=text("steps", True),
                    expected_result=text("expected_result", True),
                    required=checked("required"),
                    severity=choice("severity", SEVERITIES),
                )
            )
        elif action == "execute":
            record_test(
                record(TestCase, project, "case_id"),
                choice("result", ("passed", "failed", "blocked")),
                text("actual_result", True),
                text("tester", True, 200),
                text("evidence", True),
            )
        elif action == "bug":
            severity = choice("severity", SEVERITIES)
            db.session.add(
                BugReport(
                    project_id=project.id,
                    title=text("title", True, 200),
                    description=text("description", True),
                    severity=severity,
                    priority=choice("priority", ("low", "normal", "high", "urgent")),
                    release_blocking=checked("release_blocking")
                    or severity == "critical",
                    feature=text("feature", limit=200),
                    reproduction_steps=text("reproduction_steps", True),
                    expected_behavior=text("expected_behavior", True),
                    actual_behavior=text("actual_behavior", True),
                    assigned_to=text("assigned_to", limit=200),
                )
            )
        elif action == "bug_status":
            bug = record(BugReport, project, "bug_id")
            status = choice(
                "status", ("open", "investigating", "in_progress", "resolved", "closed")
            )
            resolution = text("resolution", status in ("resolved", "closed"))
            if status in ("resolved", "closed") and bug.test_execution_id:
                latest = (
                    TestExecution.query.filter_by(
                        test_case_id=bug.test_execution.test_case_id
                    )
                    .order_by(TestExecution.id.desc())
                    .first()
                )
                if (
                    not latest
                    or latest.result != "passed"
                    or latest.id <= bug.test_execution_id
                ):
                    raise ValueError(
                        "Record a passing retest after the failed execution before resolving this bug."
                    )
            bug.status, bug.resolution = status, resolution
            bug.resolved_at = utcnow() if status in ("resolved", "closed") else None
            audit("update_status", "BugReport", bug.id, status)
        else:
            raise ValueError("Unknown QA action.")
        return saved("QA record saved.")
    cases = TestCase.query.filter_by(project_id=project.id).order_by(TestCase.id).all()
    bugs = (
        BugReport.query.filter_by(project_id=project.id)
        .order_by(BugReport.id.desc())
        .all()
    )
    executions = (
        TestExecution.query.filter_by(project_id=project.id)
        .order_by(TestExecution.id.desc())
        .all()
    )
    forms = [
        form(
            "Prepare standard QA cases",
            "seed",
            [],
            "Generate standard test cases",
            "Creates unexecuted test cases once. Review project-specific criteria and add integration tests as needed.",
        ),
        form(
            "Add a test case",
            "case",
            [
                field("name", required=True),
                field("category", type="select", options=opts(TEST_CATEGORIES)),
                field("description", type="textarea"),
                field("preconditions", type="textarea"),
                field("steps", type="textarea", required=True),
                field("expected_result", type="textarea", required=True),
                field("severity", type="select", options=opts(SEVERITIES)),
                field("required", "Required for QA completion", "checkbox", value=True),
            ],
        ),
    ]
    if cases:
        forms.append(
            form(
                "Record a test execution",
                "execute",
                [
                    field(
                        "case_id",
                        "Test case",
                        "select",
                        True,
                        [(c.id, c.name) for c in cases],
                    ),
                    field(
                        "result",
                        type="select",
                        options=opts(("passed", "failed", "blocked")),
                    ),
                    field("actual_result", type="textarea", required=True),
                    field("tester", required=True),
                    field(
                        "evidence",
                        "Observed evidence / attachment reference",
                        "textarea",
                        True,
                    ),
                ],
                "Record actual result",
                "Failed executions create a bug automatically. All required tests must pass before final acceptance.",
            )
        )
    forms.append(
        form(
            "Report a defect",
            "bug",
            [
                field("title", required=True),
                field("description", type="textarea", required=True),
                field("feature"),
                field("severity", type="select", options=opts(SEVERITIES)),
                field(
                    "priority",
                    type="select",
                    options=opts(("low", "normal", "high", "urgent")),
                ),
                field("reproduction_steps", type="textarea", required=True),
                field("expected_behavior", type="textarea", required=True),
                field("actual_behavior", type="textarea", required=True),
                field("assigned_to"),
                field("release_blocking", type="checkbox"),
            ],
        )
    )
    if bugs:
        forms.append(
            form(
                "Update defect status",
                "bug_status",
                [
                    field(
                        "bug_id",
                        "Bug",
                        "select",
                        True,
                        [(b.id, f"#{b.id} {b.title}") for b in bugs],
                    ),
                    field(
                        "status",
                        type="select",
                        options=opts(
                            (
                                "open",
                                "investigating",
                                "in_progress",
                                "resolved",
                                "closed",
                            )
                        ),
                    ),
                    field(
                        "resolution", "Resolution and verification evidence", "textarea"
                    ),
                ],
            )
        )
    return workspace(
        "Testing & acceptance readiness",
        "Record real executions, inspect failed tests, and resolve release blockers.",
        project,
        forms,
        [
            group(
                "Test cases",
                ["Name", "Category", "Required", "Latest result", "Expected result"],
                [
                    [
                        c.name,
                        c.category,
                        "Yes" if c.required else "No",
                        c.latest_execution.result if c.latest_execution else "Not run",
                        c.expected_result,
                    ]
                    for c in cases
                ],
            ),
            group(
                "Defects",
                ["ID", "Title", "Severity", "Blocks release", "Status", "Resolution"],
                [
                    [
                        b.id,
                        b.title,
                        b.severity,
                        "Yes" if b.release_blocking else "No",
                        b.status,
                        b.resolution,
                    ]
                    for b in bugs
                ],
            ),
            group(
                "Execution history",
                ["Test", "Result", "Tester", "Actual result", "Evidence", "Date UTC"],
                [
                    [
                        e.test_case.name,
                        e.result,
                        e.tester,
                        e.actual_result,
                        e.evidence,
                        e.executed_at,
                    ]
                    for e in executions
                ],
            ),
        ],
        blockers=qa_blockers(project),
    )


@bp.route("/projects/<int:project_id>/launch", methods=["GET", "POST"])
@admin_required
def launch(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        action = text("action", True)
        if action == "authorize":
            add_approval(
                project,
                12,
                "launch",
                text("person", True, 200),
                text("evidence", True),
                current_user.id,
            )
            audit(
                "authorize",
                "Project",
                project.id,
                "Separate client launch authorization",
            )
        elif action == "plan":
            db.session.add(
                DeploymentRecord(
                    project_id=project.id,
                    production_url=url("production_url"),
                    hosting_provider=text("hosting_provider", True, 200),
                    domain_registrar=text("domain_registrar", limit=200),
                    method=text("method", True, 200),
                    version=text("version", True, 200),
                    rollback_plan=text("rollback_plan", True),
                    backup_evidence=text("backup_evidence", True),
                    checklist={key: checked(key) for key in LAUNCH_CHECKS},
                )
            )
        elif action == "verify":
            deployment = record(DeploymentRecord, project, "deployment_id")
            if deployment.status == "completed":
                raise ValueError("Completed launch records cannot be changed.")
            deployment.checklist = {key: checked(key) for key in LAUNCH_CHECKS}
            deployment.backup_evidence = text("backup_evidence", True)
            complete_deployment(
                deployment, text("verification_evidence", True), current_user.id
            )
        else:
            raise ValueError("Unknown launch action.")
        return saved(
            "Launch record saved. No production operation was executed by this CRM."
        )
    deployments = (
        DeploymentRecord.query.filter_by(project_id=project.id)
        .order_by(DeploymentRecord.id.desc())
        .all()
    )
    forms = [
        form(
            "Record separate launch authorization",
            "authorize",
            [
                field("person", "Authorizing client representative", required=True),
                field(
                    "evidence",
                    "Written authorization to launch (separate from final acceptance)",
                    "textarea",
                    True,
                ),
            ],
            "Record authorization",
        ),
        form(
            "Prepare an external deployment record",
            "plan",
            [
                field("production_url", type="url", required=True),
                field("hosting_provider", required=True),
                field("domain_registrar"),
                field("method", required=True),
                field("version", "Tested version / commit", required=True),
                field("rollback_plan", type="textarea", required=True),
                field("backup_evidence", type="textarea", required=True),
            ],
            "Save deployment plan",
            "Carry out deployment through your separately authorized deployment process. This CRM records readiness and evidence only.",
        ),
    ]
    pending = [
        (d.id, f"#{d.id} · {d.version} · {d.production_url}")
        for d in deployments
        if d.status != "completed"
    ]
    if pending:
        forms.append(
            form(
                "Confirm external deployment and verification",
                "verify",
                [field("deployment_id", "Deployment", "select", True, pending)]
                + [
                    field(key, label, "checkbox", True)
                    for key, label in LAUNCH_CHECKS.items()
                ]
                + [
                    field(
                        "backup_evidence",
                        "Verified backup location / record (no credentials)",
                        "textarea",
                        True,
                    ),
                    field(
                        "verification_evidence",
                        "Evidence of actual deployment and post-launch verification",
                        "textarea",
                        True,
                    ),
                ],
                "Record completed launch",
                "Completion requires passed QA, final acceptance, verified payment and separate launch authorization.",
            )
        )
    return workspace(
        "Deployment & launch",
        "Readiness, authorization, rollback planning and verified external deployment records.",
        project,
        forms,
        [
            group(
                "Deployment records",
                [
                    "Version",
                    "Production URL",
                    "Host",
                    "Method",
                    "Status",
                    "Date UTC",
                    "Verification",
                ],
                [
                    [
                        d.version,
                        d.production_url,
                        d.hosting_provider,
                        d.method,
                        d.status,
                        d.deployed_at,
                        d.verification_evidence,
                    ]
                    for d in deployments
                ],
            )
        ],
        blockers=launch_blockers(project),
    )


@bp.route("/projects/<int:project_id>/handover", methods=["GET", "POST"])
@admin_required
def handover(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == "POST":
        action = text("action", True)
        if action == "handover":
            record_obj = HandoverRecord(
                project_id=project.id,
                recipient=text("recipient", True, 200),
                production_url=url("production_url"),
                documentation=text("documentation", True),
                outstanding_obligations=text("outstanding_obligations"),
                evidence=text("evidence", True),
                warranty_expires_at=when("warranty_expires_at"),
                deliverables={key: checked(key) for key in HANDOVER_CHECKS}
                | {
                    "source_code": text("source_code", True),
                    "design_assets": text("design_assets", True),
                },
            )
            db.session.add(record_obj)
            db.session.flush()
            complete_handover(record_obj, current_user.id)
        elif action == "training":
            status = choice("status", ("scheduled", "completed"))
            db.session.add(
                TrainingRecord(
                    project_id=project.id,
                    scheduled_at=when("scheduled_at", True),
                    participants=text("participants", True),
                    topics=text("topics", True),
                    resources=text("resources"),
                    follow_up_questions=text("follow_up_questions"),
                    status=status,
                    completion_evidence=text(
                        "completion_evidence", status == "completed"
                    ),
                )
            )
        elif action == "complete_training":
            training = record(TrainingRecord, project, "training_id")
            if training.status == "completed":
                raise ValueError("Training completion is already recorded.")
            training.completion_evidence = text("completion_evidence", True)
            training.status = "completed"
        else:
            raise ValueError("Unknown handover action.")
        return saved("Handover workspace updated.")
    handovers = (
        HandoverRecord.query.filter_by(project_id=project.id)
        .order_by(HandoverRecord.id.desc())
        .all()
    )
    training = (
        TrainingRecord.query.filter_by(project_id=project.id)
        .order_by(TrainingRecord.scheduled_at.desc())
        .all()
    )
    forms = [
        form(
            "Confirm agreed handover delivery",
            "handover",
            [
                field("recipient", required=True),
                field("production_url", type="url", required=True),
            ]
            + [
                field(key, label, "checkbox", True)
                for key, label in HANDOVER_CHECKS.items()
            ]
            + [
                field(
                    "source_code",
                    "Source code delivery evidence or agreed exclusion",
                    "textarea",
                    True,
                ),
                field(
                    "design_assets",
                    "Design asset delivery evidence or agreed exclusion",
                    "textarea",
                    True,
                ),
                field(
                    "documentation",
                    "Documentation, backup instructions, maintenance requirements and license references",
                    "textarea",
                    True,
                ),
                field("outstanding_obligations", type="textarea"),
                field(
                    "evidence",
                    "Evidence that the client received the deliverables",
                    "textarea",
                    True,
                ),
                field("warranty_expires_at", "Warranty expiry (UTC)", "datetime-local"),
            ],
            "Confirm handover",
        ),
        form(
            "Record training",
            "training",
            [
                field("scheduled_at", "Training time (UTC)", "datetime-local", True),
                field("participants", type="textarea", required=True),
                field("topics", type="textarea", required=True),
                field("resources", type="textarea"),
                field("follow_up_questions", type="textarea"),
                field(
                    "status", type="select", options=opts(("scheduled", "completed"))
                ),
                field("completion_evidence", type="textarea"),
            ],
        ),
    ]
    pending = [
        (t.id, f"{t.scheduled_at} · {t.participants[:50]}")
        for t in training
        if t.status != "completed"
    ]
    if pending:
        forms.append(
            form(
                "Confirm training completed",
                "complete_training",
                [
                    field("training_id", "Training", "select", True, pending),
                    field("completion_evidence", type="textarea", required=True),
                ],
            )
        )
    return workspace(
        "Handover & training",
        "Confirm delivery and record the resources that help your client operate their website.",
        project,
        forms,
        [
            group(
                "Handover history",
                [
                    "Recipient",
                    "Website",
                    "Status",
                    "Documentation",
                    "Evidence",
                    "Warranty expires UTC",
                ],
                [
                    [
                        h.recipient,
                        h.production_url,
                        h.status,
                        h.documentation,
                        h.evidence,
                        h.warranty_expires_at,
                    ]
                    for h in handovers
                ],
            ),
            group(
                "Training",
                ["Date UTC", "Participants", "Topics", "Status", "Evidence"],
                [
                    [
                        t.scheduled_at,
                        t.participants,
                        t.topics,
                        t.status,
                        t.completion_evidence,
                    ]
                    for t in training
                ],
            ),
        ],
    )


@bp.route("/maintenance", methods=["GET", "POST"])
@admin_required
def maintenance():
    if request.method == "POST":
        action = text("action", True)
        if action == "agreement":
            project = db.get_or_404(Project, integer("project_id"))
            start_date, renewal_date = (
                when("start_date", True, True),
                when("renewal_date", True, True),
            )
            if renewal_date <= start_date:
                raise ValueError("Renewal date must be after the start date.")
            status = choice("status", ("draft", "active"))
            agreement = MaintenanceAgreement(
                project_id=project.id,
                client_id=project.client_id,
                name=text("name", True, 200),
                website=url("website"),
                monthly_fee=amount("monthly_fee"),
                currency=project.currency,
                billing_frequency=choice(
                    "billing_frequency", ("monthly", "quarterly", "annual")
                ),
                start_date=start_date,
                renewal_date=renewal_date,
                covered_services=text("covered_services", True),
                excluded_services=text("excluded_services"),
                support_hours=text("support_hours", limit=200),
                response_expectations=text("response_expectations", True),
                status=status,
                acceptance_evidence=text("acceptance_evidence", status == "active"),
            )
            db.session.add(agreement)
            log_activity("maintenance_created", agreement.name, project_id=project.id)
        elif action == "schedule":
            counts = process_recurring_maintenance()
            return saved(
                f"Created {counts['tasks']} pending reviews and {counts['invoices']} draft renewal invoices.",
                **counts,
            )
        elif action == "agreement_status":
            agreement = db.get_or_404(MaintenanceAgreement, integer("agreement_id"))
            status = choice(
                "status", ("draft", "active", "paused", "canceled", "expired")
            )
            if status == "active":
                agreement.acceptance_evidence = text("acceptance_evidence", True)
                if agreement.renewal_date < utcnow().date():
                    raise ValueError(
                        "Confirm a new renewal term before activating an expired agreement."
                    )
            agreement.status = status
            audit("update_status", "MaintenanceAgreement", agreement.id, status)
        elif action == "renew":
            agreement = db.get_or_404(MaintenanceAgreement, integer("agreement_id"))
            new_date = when("renewal_date", True, True)
            if new_date <= agreement.renewal_date or new_date <= utcnow().date():
                raise ValueError(
                    "The new renewal date must extend the existing agreement into the future."
                )
            agreement.acceptance_evidence = text("acceptance_evidence", True)
            audit(
                "renew",
                "MaintenanceAgreement",
                agreement.id,
                f"{agreement.renewal_date} to {new_date}; human-confirmed evidence recorded",
            )
            agreement.renewal_date = new_date
            agreement.status = "active"
        elif action == "complete":
            task = db.get_or_404(MaintenanceTask, integer("task_id"))
            if task.status == "completed":
                raise ValueError("This maintenance activity is already completed.")
            task.evidence = text("evidence", True)
            task.status = "completed"
            task.completed_at = utcnow()
            general = Task.query.filter_by(
                event_key=f"maintenance:{task.agreement_id}:{task.period}"
            ).first()
            if general:
                general.status, general.completed_at = "completed", utcnow()
            audit("complete", "MaintenanceTask", task.id)
            log_activity(
                "maintenance_completed", task.title, project_id=task.project_id
            )
        else:
            raise ValueError("Unknown maintenance action.")
        return saved("Maintenance record saved.")
    agreements = MaintenanceAgreement.query.order_by(
        MaintenanceAgreement.renewal_date
    ).all()
    tasks = MaintenanceTask.query.order_by(MaintenanceTask.due_at.desc()).all()
    agreement_options = [(a.id, f"{a.name} · {a.project.title}") for a in agreements]
    forms = [
        form(
            "Create a maintenance agreement",
            "agreement",
            [
                field("project_id", "Project", "select", True, project_opts()),
                field("name", "Plan name", required=True),
                field("website", type="url", required=True),
                field("monthly_fee", type="number", required=True),
                field(
                    "billing_frequency",
                    type="select",
                    options=opts(("monthly", "quarterly", "annual")),
                ),
                field("start_date", type="date", required=True),
                field("renewal_date", type="date", required=True),
                field("covered_services", type="textarea", required=True),
                field("excluded_services", type="textarea"),
                field("support_hours"),
                field("response_expectations", type="textarea", required=True),
                field("status", type="select", options=opts(("draft", "active"))),
                field(
                    "acceptance_evidence",
                    "Agreement acceptance evidence (required to activate)",
                    "textarea",
                ),
            ],
        ),
        form(
            "Prepare recurring work",
            "schedule",
            [],
            "Generate due maintenance records",
            "Creates pending monthly reviews and draft renewal invoices due within 14 days. Review and issue invoices in Finance. Scheduler scans perform the same idempotent operation.",
        ),
    ]
    if agreements:
        forms += [
            form(
                "Update agreement status",
                "agreement_status",
                [
                    field(
                        "agreement_id", "Agreement", "select", True, agreement_options
                    ),
                    field(
                        "status",
                        type="select",
                        options=opts(
                            ("draft", "active", "paused", "canceled", "expired")
                        ),
                    ),
                    field("acceptance_evidence", type="textarea"),
                ],
            ),
            form(
                "Confirm a renewed term",
                "renew",
                [
                    field(
                        "agreement_id", "Agreement", "select", True, agreement_options
                    ),
                    field("renewal_date", "Next renewal date", "date", True),
                    field(
                        "acceptance_evidence",
                        "Renewal agreement and payment evidence",
                        "textarea",
                        True,
                    ),
                ],
            ),
        ]
    pending = [(t.id, t.title) for t in tasks if t.status != "completed"]
    if pending:
        forms.append(
            form(
                "Confirm maintenance performed",
                "complete",
                [
                    field("task_id", "Maintenance task", "select", True, pending),
                    field(
                        "evidence",
                        "Performed checks, results, execution records and operator confirmation",
                        "textarea",
                        True,
                    ),
                ],
                "Record actual completion",
            )
        )
    return workspace(
        "Maintenance",
        "Recurring work, renewal dates and reviewable billing drafts.",
        forms=forms,
        groups=[
            group(
                "Agreements",
                ["Plan", "Project", "Monthly fee", "Frequency", "Renewal", "Status"],
                [
                    [
                        a.name,
                        a.project.title,
                        f"{a.currency} {a.monthly_fee}",
                        a.billing_frequency,
                        a.renewal_date,
                        a.status,
                    ]
                    for a in agreements
                ],
            ),
            group(
                "Maintenance activities",
                ["Task", "Period", "Due UTC", "Status", "Evidence"],
                [[t.title, t.period, t.due_at, t.status, t.evidence] for t in tasks],
            ),
        ],
    )


@bp.route("/support", methods=["GET", "POST"])
@admin_required
def support():
    if request.method == "POST":
        action = text("action", True)
        if action == "ticket":
            project = db.get_or_404(Project, integer("project_id"))
            ticket = SupportTicket(
                project_id=project.id,
                client_id=project.client_id,
                title=text("title", True, 200),
                category=choice(
                    "category",
                    (
                        "general",
                        "defect",
                        "content",
                        "security",
                        "hosting",
                        "billing",
                        "change",
                    ),
                ),
                description=text("description", True),
                priority=choice("priority", ("low", "normal", "high", "urgent")),
                assigned_to=text("assigned_to", limit=200),
            )
            db.session.add(ticket)
            db.session.flush()
            event_task(
                project,
                f"support:{ticket.id}:triage",
                f"Triage {ticket.reference}: {ticket.title}",
                14,
            )
            log_activity("support_opened", ticket.reference, project_id=project.id)
        elif action == "update":
            ticket = db.get_or_404(SupportTicket, integer("ticket_id"))
            status = choice(
                "status",
                (
                    "open",
                    "investigating",
                    "awaiting_client",
                    "in_progress",
                    "resolved",
                    "closed",
                ),
            )
            ticket.resolution = text("resolution", status in ("resolved", "closed"))
            ticket.time_spent = amount("time_spent")
            ticket.assigned_to = text("assigned_to", limit=200)
            ticket.status = status
            ticket.resolved_at = utcnow() if status in ("resolved", "closed") else None
            audit("update_status", "SupportTicket", ticket.id, status)
        else:
            raise ValueError("Unknown support action.")
        return saved("Support ticket saved.")
    status = request.args.get("status", "")
    query = SupportTicket.query
    if status:
        if status not in (
            "open",
            "investigating",
            "awaiting_client",
            "in_progress",
            "resolved",
            "closed",
        ):
            raise ValueError("Choose a valid support status.")
        query = query.filter_by(status=status)
    tickets = query.order_by(SupportTicket.created_at.desc()).all()
    forms = [
        form(
            "Open a support ticket",
            "ticket",
            [
                field("project_id", "Project", "select", True, project_opts()),
                field("title", required=True),
                field(
                    "category",
                    type="select",
                    options=opts(
                        (
                            "general",
                            "defect",
                            "content",
                            "security",
                            "hosting",
                            "billing",
                            "change",
                        )
                    ),
                ),
                field("description", type="textarea", required=True),
                field(
                    "priority",
                    type="select",
                    options=opts(("low", "normal", "high", "urgent")),
                ),
                field("assigned_to"),
            ],
        )
    ]
    if tickets:
        forms.append(
            form(
                "Update a support ticket",
                "update",
                [
                    field(
                        "ticket_id",
                        "Ticket",
                        "select",
                        True,
                        [(t.id, f"{t.reference}: {t.title}") for t in tickets],
                    ),
                    field(
                        "status",
                        type="select",
                        options=opts(
                            (
                                "open",
                                "investigating",
                                "awaiting_client",
                                "in_progress",
                                "resolved",
                                "closed",
                            )
                        ),
                    ),
                    field("assigned_to"),
                    field("time_spent", "Total time spent (hours)", "number", value=0),
                    field(
                        "resolution",
                        "Resolution (required to resolve or close)",
                        "textarea",
                    ),
                ],
            )
        )
    return workspace(
        "Support tickets",
        "Follow issues through investigation to a documented resolution.",
        forms=forms,
        groups=[
            group(
                "Tickets",
                [
                    "Reference",
                    "Title",
                    "Client",
                    "Project",
                    "Priority",
                    "Status",
                    "Hours",
                    "Resolution",
                ],
                [
                    [
                        t.reference,
                        t.title,
                        t.client.name,
                        t.project.title,
                        t.priority,
                        t.status,
                        t.time_spent,
                        t.resolution,
                    ]
                    for t in tickets
                ],
            )
        ],
    )
