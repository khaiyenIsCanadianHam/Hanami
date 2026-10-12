"""Explicit, transactional lifecycle gates. Callers own database commits."""

from decimal import Decimal
from uuid import uuid4
from app.extensions import db
from app.models import (
    Project,
    ProjectStage,
    Requirement,
    Task,
    StageTransition,
    Approval,
    ScopeItem,
)
from app.models.base import utcnow
from app.services.common import log_activity

STAGES = [
    (
        1,
        "Client acquisition",
        "Qualify the opportunity and deliberately convert the lead.",
        [("qualification", "Qualification summary"), ("service", "Requested service")],
        ["Client conversion confirmed"],
        "Qualification checklist",
        "Initial introduction",
    ),
    (
        2,
        "Initial inquiry",
        "Collect the business and website requirements.",
        [
            ("website_type", "Website type"),
            ("audience", "Target audience"),
            ("features", "Required pages and features"),
            ("budget", "Budget range"),
        ],
        ["Inquiry questionnaire reviewed"],
        "Requirements questionnaire",
        "Inquiry acknowledgment",
    ),
    (
        3,
        "Discovery & consultation",
        "Review objectives, constraints, and consultation decisions.",
        [
            ("objectives", "Business objectives"),
            ("requirements", "Reviewed requirements summary"),
            ("constraints", "Budget, deadline and technical constraints"),
        ],
        ["Requirements summary reviewed"],
        "Discovery summary",
        "Consultation follow-up",
    ),
    (
        4,
        "Scope & planning",
        "Define deliverables, exclusions and acceptance criteria.",
        [
            ("deliverables", "Deliverables"),
            ("exclusions", "Excluded features"),
            ("responsibilities", "Client responsibilities"),
            ("acceptance_criteria", "Acceptance criteria"),
        ],
        ["Scope reviewed", "Milestones agreed"],
        "Scope of Work",
        "Scope approval request",
    ),
    (
        5,
        "Proposal & quotation",
        "Record a versioned quotation and client acceptance.",
        [("timeline", "Proposed timeline"), ("payment_schedule", "Payment schedule")],
        ["Proposal reviewed"],
        "Project proposal",
        "Proposal submission",
    ),
    (
        6,
        "Contract & deposit",
        "Verify the executed agreement and required deposit.",
        [("terms", "Agreement and deposit requirements")],
        ["Agreement verified", "Deposit verified"],
        "Development agreement",
        "Deposit request",
    ),
    (
        7,
        "Client onboarding",
        "Collect critical assets and delegated account access.",
        [
            ("assets", "Asset inventory"),
            ("access", "Delegated access and account invitations"),
        ],
        [
            "Logo and brand assets received",
            "Content received",
            "Domain and hosting access confirmed",
        ],
        "Asset checklist",
        "Welcome and asset request",
    ),
    (
        8,
        "Design & approval",
        "Manage design versions, client feedback and approval.",
        [("design_summary", "Design delivery summary")],
        ["Responsive designs reviewed", "Client approval evidence recorded"],
        "Design approval",
        "Design review request",
    ),
    (
        9,
        "Website development",
        "Complete the agreed features and prepare for QA.",
        [
            ("development_summary", "Development summary"),
            ("staging_url", "Staging reference"),
        ],
        ["Development tasks completed", "Features ready for QA"],
        "Weekly progress report",
        "Development progress",
    ),
    (
        10,
        "Testing & revisions",
        "Execute tests and resolve all release-blocking defects.",
        [
            ("tested_version", "Tested version"),
            ("qa_summary", "QA summary and exceptions"),
        ],
        [
            "Functional and responsive tests executed",
            "Security and accessibility reviewed",
        ],
        "QA report",
        "Client review invitation",
    ),
    (
        11,
        "Final acceptance & payment",
        "Record written acceptance and verify the final balance.",
        [
            ("tested_version", "Final tested version"),
            ("exceptions", "Agreed exceptions (or none)"),
        ],
        ["Written acceptance verified", "Final payment verified"],
        "Acceptance form",
        "Final review request",
    ),
    (
        12,
        "Deployment & launch",
        "Record a separately authorized launch and verification.",
        [("production_url", "Production URL"), ("rollback_plan", "Rollback plan")],
        [
            "DNS and HTTPS confirmed",
            "Backups and production accounts verified",
            "Privacy and content reviewed",
            "Post-launch checks completed",
        ],
        "Launch checklist",
        "Launch announcement",
    ),
    (
        13,
        "Handover & training",
        "Confirm delivery, ownership transfers and training.",
        [
            ("handover_summary", "Handover deliverables"),
            ("warranty", "Warranty terms and expiration"),
        ],
        [
            "Ownership and account transfer confirmed",
            "Documentation delivered",
            "Training completed or waived with evidence",
        ],
        "Handover document",
        "Website handover",
    ),
    (
        14,
        "Maintenance & support",
        "Record a maintenance agreement or an explicit decline.",
        [
            (
                "maintenance_decision",
                "Maintenance agreement reference or client decline",
            ),
            ("support_expectations", "Support and renewal expectations"),
        ],
        ["Maintenance decision recorded"],
        "Maintenance agreement",
        "Maintenance follow-up",
    ),
]
STAGE_MAP = {
    row[0]: {
        "number": row[0],
        "title": row[1],
        "description": row[2],
        "fields": row[3],
        "checklist": row[4],
        "document": row[5],
        "email": row[6],
    }
    for row in STAGES
}


def create_project(client, title, description=""):
    if not title or not title.strip():
        raise ValueError("A project title is required.")
    if client.status == "archived":
        raise ValueError("Restore the client before creating a project.")
    project = Project(
        client_id=client.id,
        reference="PRJ-" + uuid4().hex[:8].upper(),
        title=title.strip(),
        description=description,
        status="active",
        current_stage=1,
    )
    db.session.add(project)
    db.session.flush()
    for number, definition in STAGE_MAP.items():
        db.session.add(
            ProjectStage(
                project_id=project.id,
                number=number,
                title=definition["title"],
                status="draft",
                data={},
            )
        )
        for title in definition["checklist"]:
            db.session.add(
                Requirement(
                    project_id=project.id,
                    stage_number=number,
                    title=title,
                    required=True,
                    completed=False,
                )
            )
    from app.services.automation_service import trigger_event

    trigger_event("project.created", project)
    ensure_task(project, "Review client qualification", 1, "project-created")
    log_activity(
        "project.created",
        f"Created project {project.reference}",
        client_id=client.id,
        project_id=project.id,
    )
    return project


def ensure_task(project, title, stage_number, event):
    key = f"project:{project.id}:{event}"
    existing = Task.query.filter_by(event_key=key).first()
    if existing:
        return existing
    task = Task(
        project_id=project.id,
        client_id=project.client_id,
        title=title,
        stage_number=stage_number,
        status="backlog",
        priority="normal",
        event_key=key,
    )
    db.session.add(task)
    return task


def approved(project, kind, number=None):
    query = Approval.query.filter_by(project_id=project.id, kind=kind)
    if number is not None:
        query = query.filter_by(stage_number=number)
    record = query.order_by(Approval.id.desc()).first()
    # A later rejection supersedes prior approval; backward movement invalidates stale approvals.
    stage = ProjectStage.query.filter_by(
        project_id=project.id, number=number or project.current_stage
    ).first()
    invalidated = (stage.data or {}).get("_invalidated_at") if stage else None
    return bool(
        record
        and record.decision == "approved"
        and record.person
        and record.evidence
        and (not invalidated or record.created_at.isoformat() > invalidated)
    )


def blockers(project, number):
    from app.models import Proposal, Contract, Invoice, ScopeItem

    definition = STAGE_MAP.get(number)
    stage = ProjectStage.query.filter_by(project_id=project.id, number=number).first()
    if not definition or not stage:
        return ["Unknown workflow stage."]
    issues = []
    if project.status != "active":
        issues.append("Resume the project before completing a stage.")
    if number != project.current_stage:
        issues.append(
            "Only the current stage can be completed. Use Return to stage to reopen earlier work."
        )
    for key, label in definition["fields"]:
        if not str((stage.data or {}).get(key, "")).strip():
            issues.append(f"{label} is required.")
    for requirement in Requirement.query.filter_by(
        project_id=project.id, stage_number=number, required=True
    ):
        if not requirement.completed and not (requirement.exception or "").strip():
            issues.append(f"Complete or document an exception: {requirement.title}.")
    if not approved(project, "stage", number):
        issues.append("Record explicit stage approval with a name and evidence.")
    if number == 4:
        items = ScopeItem.query.filter_by(project_id=project.id, included=True).all()
        if not items or any(not x.acceptance_criteria for x in items):
            issues.append("Add included scope features with acceptance criteria.")
        if not approved(project, "scope", 4):
            issues.append("An explicit scope approval is required.")
    if (
        number == 5
        and not Proposal.query.filter_by(
            project_id=project.id, status="accepted"
        ).first()
    ):
        issues.append("A proposal with recorded client acceptance is required.")
    if number >= 6:
        if not Contract.query.filter_by(
            project_id=project.id, status="executed"
        ).first():
            issues.append("An executed contract is required.")
        deposits = (
            Invoice.query.filter_by(project_id=project.id, kind="deposit")
            .filter(Invoice.status.in_(["issued", "partially_paid", "paid"]))
            .all()
        )
        if not deposits or any(x.balance > Decimal("0") for x in deposits):
            issues.append(
                "An issued deposit invoice must be fully paid by verified payments."
            )
    if number == 8:
        from app.models import DesignSubmission, RevisionRequest

        design = (
            DesignSubmission.query.filter_by(project_id=project.id)
            .order_by(DesignSubmission.version.desc(), DesignSubmission.id.desc())
            .first()
        )
        if not design or design.status != "approved":
            issues.append("The latest design submission must be explicitly approved.")
        if (
            RevisionRequest.query.filter_by(project_id=project.id)
            .filter(RevisionRequest.status != "completed")
            .first()
        ):
            issues.append(
                "Resolve outstanding design revisions before completing design approval."
            )
    if number == 9:
        tasks = Task.query.filter_by(project_id=project.id, stage_number=9).all()
        if not tasks or any(task.status != "completed" for task in tasks):
            issues.append("Complete the development tasks before QA.")
    if number >= 10:
        from app.services.delivery_service import qa_blockers

        issues.extend(qa_blockers(project))
    if number >= 11:
        if not approved(project, "acceptance", 11):
            issues.append(
                "Written final acceptance requires separate administrator verification."
            )
        from app.services.invoice_service import final_payment_conditions_met

        if not final_payment_conditions_met(project):
            issues.append(
                "Settle the full contract and all project invoices, including the final invoice or verified 100% upfront payment."
            )
    if number >= 12:
        from app.models import DeploymentRecord

        if not approved(project, "launch", 12):
            issues.append("Record separate launch authorization.")
        if not DeploymentRecord.query.filter_by(
            project_id=project.id, status="completed"
        ).first():
            issues.append("Record and verify the completed deployment.")
    if number >= 13:
        from app.models import HandoverRecord

        if not HandoverRecord.query.filter_by(
            project_id=project.id, status="completed"
        ).first():
            issues.append("Confirm the agreed handover deliverables.")
    return list(dict.fromkeys(issues))


def complete_stage(project, number, actor_id=None):
    stage = ProjectStage.query.filter_by(project_id=project.id, number=number).first()
    if stage and stage.status == "completed":
        return stage
    issues = blockers(project, number)
    if issues:
        raise ValueError(" ".join(issues))
    stage.status, stage.completed_at = "completed", utcnow()
    next_stage = min(number + 1, 14)
    db.session.add(
        StageTransition(
            project_id=project.id,
            from_stage=number,
            to_stage=next_stage,
            reason="Stage completed after verification",
            actor_id=actor_id,
        )
    )
    if number < 14:
        project.current_stage = next_stage
        ensure_task(
            project,
            f"Prepare {STAGE_MAP[next_stage]['title'].lower()}",
            next_stage,
            f"stage-{number}-completed",
        )
    else:
        project.status = "completed"
    if number == 4:
        snapshot = [
            {
                key: str(getattr(item, key))
                for key in (
                    "id",
                    "name",
                    "description",
                    "hours",
                    "rate",
                    "acceptance_criteria",
                    "included",
                )
            }
            for item in ScopeItem.query.filter_by(project_id=project.id)
        ]
        stage.data = {
            **stage.data,
            "approved_versions": [
                *(stage.data.get("approved_versions", [])),
                {"approved_at": utcnow().isoformat(), "items": snapshot},
            ],
        }
        for item in ScopeItem.query.filter_by(project_id=project.id, included=True):
            item.status = "approved"
    if number == 8:
        for item in ScopeItem.query.filter_by(
            project_id=project.id, included=True, status="approved"
        ):
            task = ensure_task(project, item.name, 9, f"scope-{item.id}-development")
            task.description, task.estimated_hours = item.description, item.hours
    from app.services.automation_service import trigger_event

    trigger_event(
        "stage.completed",
        project,
        event_key=f"stage:{stage.id}:completed:{stage.completed_at.isoformat()}",
    )
    log_activity(
        "stage.completed",
        f"Completed {stage.title}",
        client_id=project.client_id,
        project_id=project.id,
    )
    return stage


def transition(project, target, reason, actor_id=None):
    if target not in STAGE_MAP or target >= project.current_stage or not reason.strip():
        raise ValueError("Select an earlier stage and give a reason for reopening it.")
    db.session.add(
        StageTransition(
            project_id=project.id,
            from_stage=project.current_stage,
            to_stage=target,
            reason=reason.strip(),
            actor_id=actor_id,
        )
    )
    for stage in ProjectStage.query.filter(
        ProjectStage.project_id == project.id, ProjectStage.number >= target
    ):
        stage.status, stage.completed_at = "draft", None
        stage.data = {**(stage.data or {}), "_invalidated_at": utcnow().isoformat()}
    project.current_stage, project.status = target, "active"
    log_activity(
        "stage.reopened",
        f"Returned to {STAGE_MAP[target]['title']}: {reason}",
        project_id=project.id,
        client_id=project.client_id,
    )
