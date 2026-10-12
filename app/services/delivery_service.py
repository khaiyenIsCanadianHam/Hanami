"""Delivery decisions are explicit, auditable records, never production actions."""

from datetime import datetime, timedelta
from decimal import Decimal
from app.extensions import db
from app.models.base import utcnow
from app.models.delivery import (
    RevisionRequest,
    ChangeRequest,
    TestCase,
    TestExecution,
    BugReport,
    DeploymentRecord,
    MaintenanceAgreement,
    MaintenanceTask,
)
from app.services.common import audit, log_activity

LAUNCH_CHECKS = {
    "production_configuration": "Production configuration reviewed",
    "domain_dns": "Domain and DNS prepared",
    "https": "HTTPS active and verified",
    "secrets": "Production secrets configured securely",
    "backups": "Restorable backup confirmed",
    "accounts": "Administrative accounts configured",
    "content": "Required content finalized",
    "privacy": "Privacy requirements reviewed",
    "post_deployment_testing": "Post-deployment checks passed",
}
HANDOVER_CHECKS = {
    "domain_ownership": "Domain ownership confirmed",
    "hosting_ownership": "Hosting ownership confirmed",
    "admin_transfer": "Administrative access transferred securely",
    "documentation": "Documentation delivered",
    "backup_instructions": "Backup instructions delivered",
    "maintenance_requirements": "Maintenance responsibilities explained",
    "licenses": "Third-party licenses documented",
}
TEST_CATEGORIES = (
    "functional",
    "responsive",
    "browser",
    "accessibility",
    "performance",
    "security",
    "forms",
    "email",
    "payments",
    "content",
    "seo",
    "uat",
)
SEVERITIES = ("low", "medium", "high", "critical")


def approval_exists(project, kind, stage):
    from app.services.lifecycle_service import approved

    return approved(project, kind, stage)


def add_approval(project, stage, kind, person, evidence, actor_id=None):
    from app.models.core import Approval

    if not person.strip() or not evidence.strip():
        raise ValueError("The approving person and written evidence are required.")
    approval = Approval(
        project_id=project.id,
        stage_number=stage,
        kind=kind,
        decision="approved",
        person=person.strip(),
        evidence=evidence.strip(),
        actor_id=actor_id,
    )
    db.session.add(approval)
    return approval


def event_task(project, key, title, stage, due_at=None, description=""):
    from app.models.core import Task

    task = Task.query.filter_by(event_key=key).first()
    if task is None:
        task = Task(
            project_id=project.id,
            client_id=project.client_id,
            stage_number=stage,
            event_key=key,
            title=title,
            description=description,
            status="backlog",
            priority="normal",
            due_at=due_at,
        )
        db.session.add(task)
    return task


def approve_design(design, person, evidence, actor_id=None):
    if design.status == "approved":
        raise ValueError(
            "This version already has an immutable approval. Submit a new version for changes."
        )
    if not person.strip() or not evidence.strip():
        raise ValueError(
            "Record the approving person and evidence of explicit design approval."
        )
    if (
        RevisionRequest.query.filter_by(design_id=design.id)
        .filter(RevisionRequest.status != "completed")
        .first()
    ):
        raise ValueError(
            "Resolve the outstanding revision requests before approving this version."
        )
    design.status = "approved"
    design.approved_at = utcnow()
    design.approved_by = person.strip()
    design.approval_evidence = evidence.strip()
    add_approval(
        design.project,
        8,
        "design",
        person,
        f"Design v{design.version}: {evidence}",
        actor_id,
    )
    event_task(
        design.project,
        f"design:{design.id}:development",
        "Plan development from approved design",
        9,
    )
    log_activity(
        "design_approved",
        f"Design version {design.version} approved by {person}.",
        project_id=design.project_id,
    )
    audit("approve", "DesignSubmission", design.id, f"Version {design.version}")


def request_revision(design, description, category="included"):
    if category not in ("defect", "included", "out_of_scope"):
        raise ValueError("Choose defect, included revision, or out-of-scope change.")
    if not description.strip():
        raise ValueError("Describe the requested revision.")
    project = design.project
    used = RevisionRequest.query.filter_by(
        project_id=project.id, category="included", included=True
    ).count()
    included = category == "defect" or (
        category == "included" and used < (project.revision_allowance or 0)
    )
    number = RevisionRequest.query.filter_by(project_id=project.id).count() + 1
    revision = RevisionRequest(
        project_id=project.id,
        design_id=design.id,
        description=description.strip(),
        category=category,
        included=included,
        round_number=number,
    )
    db.session.add(revision)
    db.session.flush()
    if not included:
        db.session.add(
            ChangeRequest(
                project_id=project.id,
                revision_id=revision.id,
                title=f"Revision {number}: scope and price review",
                description=description.strip(),
                impact="Outside the included revision allowance; assess price and schedule before approval.",
            )
        )
    log_activity(
        "revision_requested",
        f"Revision {number} recorded; {'included' if included else 'change approval required'}.",
        project_id=project.id,
    )
    return revision


def decide_change(change, decision, person, evidence, actor_id=None):
    if change.status in ("approved", "rejected"):
        raise ValueError(
            "This decision is finalized. Record a new change request for a further decision."
        )
    if (
        decision not in ("approved", "rejected")
        or not person.strip()
        or not evidence.strip()
    ):
        raise ValueError(
            "A valid decision, client decision-maker and evidence are required."
        )
    if decision == "approved" and not change.impact.strip():
        raise ValueError(
            "Document the scope, cost and schedule impact before approval."
        )
    change.status = decision
    change.decision_person = person.strip()
    change.decision_evidence = evidence.strip()
    change.decided_at = utcnow()
    if decision == "approved":
        event_task(
            change.project,
            f"change:{change.id}:implementation",
            f"Approved change: {change.title}",
            9,
            description=f"{change.description}\nImpact: {change.impact}",
        )
    audit(decision, "ChangeRequest", change.id)
    log_activity(
        "change_decision",
        f"Change {change.id} {decision}.",
        project_id=change.project_id,
    )


def record_test(case, result, actual_result, tester, evidence):
    if result not in ("passed", "failed", "blocked"):
        raise ValueError("Test result must be passed, failed, or blocked.")
    if not all(value.strip() for value in (actual_result, tester, evidence)):
        raise ValueError(
            "Actual results, tester and evidence are required for every execution."
        )
    execution = TestExecution(
        project_id=case.project_id,
        test_case_id=case.id,
        result=result,
        actual_result=actual_result.strip(),
        tester=tester.strip(),
        evidence=evidence.strip(),
    )
    db.session.add(execution)
    db.session.flush()
    if result == "failed":
        db.session.add(
            BugReport(
                project_id=case.project_id,
                test_execution_id=execution.id,
                title=f"Failed: {case.name}"[:200],
                description=actual_result,
                severity=case.severity,
                priority="urgent" if case.severity == "critical" else "normal",
                release_blocking=case.required or case.severity in ("high", "critical"),
                reproduction_steps=case.steps,
                expected_behavior=case.expected_result,
                actual_behavior=actual_result,
            )
        )
    log_activity("test_executed", f"{case.name}: {result}.", project_id=case.project_id)
    return execution


def qa_blockers(project):
    cases = TestCase.query.filter_by(project_id=project.id, required=True).all()
    blockers = []
    if not cases:
        blockers.append("Add and execute required test cases.")
    for case in cases:
        execution = (
            TestExecution.query.filter_by(test_case_id=case.id)
            .order_by(TestExecution.id.desc())
            .first()
        )
        if not execution or execution.result != "passed":
            blockers.append(f"Required test has not passed: {case.name}.")
    bugs = (
        BugReport.query.filter_by(project_id=project.id)
        .filter(
            db.or_(
                BugReport.release_blocking.is_(True), BugReport.severity == "critical"
            ),
            BugReport.status.notin_(("resolved", "closed")),
        )
        .all()
    )
    blockers.extend(
        f"Unresolved release-blocking bug #{bug.id}: {bug.title}." for bug in bugs
    )
    return blockers


def launch_blockers(project):
    from app.services.invoice_service import (
        payment_conditions_met,
        project_balance,
        final_payment_conditions_met,
    )

    blockers = qa_blockers(project)
    if not approval_exists(project, "acceptance", 11):
        blockers.append("Record explicit final client acceptance in stage 11.")
    if not approval_exists(project, "launch", 12):
        blockers.append("Record separate client launch authorization in stage 12.")
    if not payment_conditions_met(project) or project_balance(project) > 0:
        blockers.append(
            "Contract payment conditions and all issued invoice balances must be satisfied."
        )
    if not final_payment_conditions_met(project):
        blockers.append(
            "Verify full contract settlement: final invoice or 100% upfront payment, with no outstanding project invoices."
        )
    return blockers


def complete_deployment(record, verification_evidence, actor_id=None):
    if record.status == "completed":
        raise ValueError("This launch record is already completed.")
    blockers = launch_blockers(record.project)
    blockers.extend(
        label for key, label in LAUNCH_CHECKS.items() if not record.checklist.get(key)
    )
    if blockers:
        raise ValueError("Launch is blocked: " + " ".join(blockers))
    if not verification_evidence.strip():
        raise ValueError(
            "Record evidence that deployment and post-launch verification actually occurred."
        )
    record.status = "completed"
    record.verification_evidence = verification_evidence.strip()
    record.deployed_at = utcnow()
    record.recorded_by = actor_id
    event_task(
        record.project, f"launch:{record.id}:handover", "Prepare website handover", 13
    )
    event_task(
        record.project,
        f"launch:{record.id}:verification",
        "Post-launch verification follow-up",
        12,
        utcnow() + timedelta(days=1),
    )
    audit(
        "complete",
        "DeploymentRecord",
        record.id,
        "Manually confirmed external deployment; CRM did not deploy.",
    )
    log_activity(
        "launch_recorded",
        "External deployment and verification confirmed.",
        project_id=record.project_id,
    )


def complete_handover(record, actor_id=None):
    if record.status == "completed":
        raise ValueError("This handover record is already completed.")
    if not DeploymentRecord.query.filter_by(
        project_id=record.project_id, status="completed"
    ).first():
        raise ValueError("A completed launch record is required before handover.")
    missing = [
        label
        for key, label in HANDOVER_CHECKS.items()
        if not record.deliverables.get(key)
    ]
    if missing:
        raise ValueError("Confirm handover deliverables: " + ", ".join(missing))
    if not record.evidence.strip() or not record.documentation.strip():
        raise ValueError("Delivery evidence and documentation are required.")
    record.status = "completed"
    record.completed_at = utcnow()
    add_approval(
        record.project, 13, "handover", record.recipient, record.evidence, actor_id
    )
    if record.warranty_expires_at:
        event_task(
            record.project,
            f"handover:{record.id}:warranty",
            "Warranty expiry follow-up",
            14,
            record.warranty_expires_at - timedelta(days=7),
        )
    log_activity(
        "handover_completed",
        "Agreed website handover deliverables confirmed.",
        project_id=record.project_id,
    )
    audit("complete", "HandoverRecord", record.id)


def seed_test_cases(project):
    standard = [
        (
            "functional",
            "Core user journey",
            "Execute each agreed primary user journey.",
            "All agreed steps complete and data is saved correctly.",
        ),
        (
            "responsive",
            "Responsive layouts",
            "Check desktop, tablet and mobile widths.",
            "Navigation, content and controls remain usable without unintended horizontal scrolling.",
        ),
        (
            "browser",
            "Supported browsers",
            "Run the primary journey in every agreed supported browser.",
            "The journey behaves consistently in the supported browser matrix.",
        ),
        (
            "accessibility",
            "Keyboard and labels",
            "Navigate without a pointer and inspect control labels and contrast.",
            "Focus is visible, controls are labeled and agreed accessibility criteria pass.",
        ),
        (
            "security",
            "Access and input security",
            "Check protected routes, validation, secrets and security headers.",
            "Unauthorized access is denied and invalid input is handled safely.",
        ),
        (
            "performance",
            "Agreed performance budget",
            "Measure the approved performance targets on representative pages.",
            "Measurements meet the documented project performance budget.",
        ),
        (
            "content",
            "Client content verification",
            "Review approved text, media, links and required legal content.",
            "Published content matches approved materials and links resolve.",
        ),
        (
            "seo",
            "SEO basics",
            "Inspect page titles, descriptions, canonical metadata and sitemap.",
            "Required pages expose accurate search metadata.",
        ),
        (
            "uat",
            "Client acceptance review",
            "Ask the client to execute the agreed acceptance scenarios.",
            "Client records results against each agreed acceptance criterion.",
        ),
    ]
    count = 0
    for category, name, steps, expected in standard:
        if not TestCase.query.filter_by(project_id=project.id, name=name).first():
            db.session.add(
                TestCase(
                    project_id=project.id,
                    name=name,
                    category=category,
                    steps=steps,
                    expected_result=expected,
                )
            )
            count += 1
    return count


def process_recurring_maintenance(now=None):
    """Generate pending checks and draft renewal invoices; never claim work performed.

    One task per active agreement/month and one invoice per agreement/renewal date.
    Renewal dates advance only upon a separately confirmed renewal, not a scan.
    Caller owns the transaction.
    """
    now = now or utcnow()
    today = now.date()
    counts = {"tasks": 0, "invoices": 0}
    from app.services.invoice_service import create_invoice
    from app.models.finance import Invoice

    for agreement in MaintenanceAgreement.query.filter_by(status="active").all():
        if agreement.start_date > today:
            continue
        period = today.strftime("%Y-%m")
        if (
            today <= agreement.renewal_date
            and not MaintenanceTask.query.filter_by(
                agreement_id=agreement.id, period=period, category="scheduled_review"
            ).first()
        ):
            task = MaintenanceTask(
                agreement_id=agreement.id,
                project_id=agreement.project_id,
                title=f"{agreement.name}: scheduled maintenance review",
                category="scheduled_review",
                period=period,
                due_at=now,
                evidence="",
            )
            db.session.add(task)
            event_task(
                agreement.project,
                f"maintenance:{agreement.id}:{period}",
                task.title,
                14,
                now,
                description=agreement.covered_services,
            )
            counts["tasks"] += 1
        if today <= agreement.renewal_date <= today + timedelta(days=14):
            schedule_key = (
                f"maintenance:{agreement.id}:{agreement.renewal_date.isoformat()}"
            )
            if not Invoice.query.filter_by(schedule_key=schedule_key).first():
                months = {"monthly": 1, "quarterly": 3, "annual": 12}[
                    agreement.billing_frequency
                ]
                create_invoice(
                    agreement.project,
                    items=[
                        {
                            "description": f"{agreement.name} renewal ({agreement.billing_frequency})",
                            "quantity": 1,
                            "unit_price": agreement.monthly_fee * Decimal(months),
                        }
                    ],
                    kind="maintenance",
                    due_at=agreement.renewal_date,
                    schedule_key=schedule_key,
                    instructions="Draft renewal: administrator must review and issue. Renewal is not automatic.",
                )
                counts["invoices"] += 1
            event_task(
                agreement.project,
                schedule_key + ":review",
                f"Review maintenance renewal: {agreement.name}",
                14,
                datetime.combine(agreement.renewal_date, datetime.min.time()),
            )
    return counts
