"""Evidence gates, release-blocking defects and repeatable maintenance scheduling."""

from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from app.extensions import db
from app.models.base import utcnow
from app.models import (
    Client,
    Approval,
    DesignSubmission,
    TestCase as QACase,
    BugReport,
    DeploymentRecord,
    HandoverRecord,
    MaintenanceAgreement,
    MaintenanceTask,
    Invoice,
    Task,
    Meeting,
)
from app.services.lifecycle_service import create_project
from app.services.delivery_service import (
    approve_design,
    request_revision,
    decide_change,
    record_test,
    qa_blockers,
    launch_blockers,
    complete_deployment,
    complete_handover,
    LAUNCH_CHECKS,
    HANDOVER_CHECKS,
    process_recurring_maintenance,
    approval_exists,
)


@pytest.fixture
def project(app):
    customer = Client(
        name="Fictional Delivery Client",
        business_name="Fictional Studio",
        email="fictional@example.com",
    )
    db.session.add(customer)
    db.session.flush()
    project = create_project(customer, "Fictional Delivery Website")
    project.revision_allowance = 1
    db.session.commit()
    return project


def design_for(project):
    design = DesignSubmission(
        project_id=project.id,
        title="Mobile layout",
        version=1,
        reference_url="https://example.com/design",
        description="Fictional layout",
    )
    db.session.add(design)
    db.session.commit()
    return design


def case_for(project):
    case = QACase(
        project_id=project.id,
        name="Complete checkout",
        category="functional",
        steps="Submit the agreed form.",
        expected_result="Data saved.",
        required=True,
        severity="high",
    )
    db.session.add(case)
    db.session.commit()
    return case


def test_revision_allowance_creates_billable_change_and_requires_approval(project):
    design = design_for(project)
    included = request_revision(design, "Adjust spacing.", "included")
    excess = request_revision(design, "Add a new page.", "included")
    db.session.flush()
    assert included.included is True
    assert excess.included is False
    assert excess.change_request.status == "draft"
    assert excess.change_request.estimated_cost == Decimal("0")
    with pytest.raises(ValueError, match="outstanding revision"):
        approve_design(design, "Client", "Signed design approval")
    change = excess.change_request
    change.impact = "Add one page; PHP 1000, one working day."
    change.estimated_cost = Decimal("1000")
    decide_change(change, "approved", "Client", "Written scope approval")
    db.session.flush()
    assert (
        Task.query.filter_by(event_key=f"change:{change.id}:implementation").count()
        == 1
    )
    with pytest.raises(ValueError, match="finalized"):
        decide_change(change, "approved", "Client", "Duplicate")


def test_design_approval_requires_evidence_and_is_immutable(project):
    design = design_for(project)
    with pytest.raises(ValueError, match="approval"):
        approve_design(design, "Client", "")
    assert design.status == "submitted"
    approve_design(design, "Client", "Signed mockup review v1")
    db.session.flush()
    assert design.status == "approved"
    assert Approval.query.filter_by(project_id=project.id, kind="design").count() == 1
    with pytest.raises(ValueError, match="already"):
        approve_design(design, "Client", "Repeat")


def test_failed_test_creates_release_blocker_and_requires_retest(auth_client, project):
    case = case_for(project)
    response = auth_client.post(
        f"/projects/{project.id}/testing",
        json={
            "action": "execute",
            "case_id": case.id,
            "result": "failed",
            "actual_result": "HTTP 500",
            "tester": "Administrator",
            "evidence": "Test log #123",
        },
    )
    assert response.status_code == 200
    bug = BugReport.query.one()
    assert bug.release_blocking is True
    assert len(qa_blockers(project)) == 2
    response = auth_client.post(
        f"/projects/{project.id}/testing",
        json={
            "action": "bug_status",
            "bug_id": bug.id,
            "status": "resolved",
            "resolution": "Fixed handler",
        },
    )
    assert response.status_code == 400
    assert "passing retest" in response.json["error"]
    record_test(case, "passed", "Data saved.", "Administrator", "Test log #124")
    db.session.commit()
    assert (
        len(qa_blockers(project)) == 1
    )  # Passing a test does not silently close the defect.
    response = auth_client.post(
        f"/projects/{project.id}/testing",
        json={
            "action": "bug_status",
            "bug_id": bug.id,
            "status": "resolved",
            "resolution": "Retested fix in log #124",
        },
    )
    assert response.status_code == 200
    assert qa_blockers(project) == []


def test_critical_bug_cannot_be_nonblocking(auth_client, project):
    response = auth_client.post(
        f"/projects/{project.id}/testing",
        json={
            "action": "bug",
            "title": "Unauthorized account access",
            "description": "Access check missing.",
            "severity": "critical",
            "priority": "urgent",
            "reproduction_steps": "Access protected URL.",
            "expected_behavior": "Denied",
            "actual_behavior": "Allowed",
            "release_blocking": False,
        },
    )
    assert response.status_code == 200
    assert BugReport.query.one().release_blocking is True


def test_cross_project_design_reference_rejected(auth_client, project):
    design = design_for(project)
    other = create_project(project.client, "Other project")
    db.session.commit()
    response = auth_client.post(
        f"/projects/{other.id}/design",
        json={
            "action": "approve",
            "design_id": design.id,
            "person": "Client",
            "evidence": "Signed review",
        },
    )
    assert response.status_code == 404
    assert design.status == "submitted"


def test_launch_acceptance_and_authorization_are_distinct(project):
    db.session.add(
        Approval(
            project_id=project.id,
            kind="acceptance",
            stage_number=11,
            person="Client",
            evidence="Written acceptance",
            decision="approved",
        )
    )
    db.session.commit()
    blockers = launch_blockers(project)
    assert not any("final client acceptance" in b for b in blockers)
    assert any("separate client launch" in b for b in blockers)
    assert any("payment" in b for b in blockers)
    record = DeploymentRecord(
        project_id=project.id,
        production_url="https://example.com",
        hosting_provider="Example host",
        method="Externally executed release",
        version="test-commit",
        rollback_plan="Restore previous verified release.",
        backup_evidence="Snapshot #1",
        checklist={key: True for key in LAUNCH_CHECKS},
    )
    db.session.add(record)
    db.session.flush()
    with pytest.raises(ValueError, match="Launch is blocked"):
        complete_deployment(record, "Deployment operator confirmation")
    assert record.status == "planned"


def test_latest_rejection_invalidates_prior_launch_authorization(project):
    db.session.add(
        Approval(
            project_id=project.id,
            kind="launch",
            stage_number=12,
            person="Client",
            evidence="Launch authorization",
            decision="approved",
        )
    )
    db.session.commit()
    assert approval_exists(project, "launch", 12)
    db.session.add(
        Approval(
            project_id=project.id,
            kind="launch",
            stage_number=12,
            person="Client",
            evidence="Hold launch until campaign ready",
            decision="rejected",
        )
    )
    db.session.commit()
    assert not approval_exists(project, "launch", 12)
    assert any("separate client launch" in b for b in launch_blockers(project))


def test_handover_requires_actual_launch_and_delivery_evidence(project):
    record = HandoverRecord(
        project_id=project.id,
        recipient="Client",
        production_url="https://example.com",
        documentation="Website guide",
        evidence="Signed handover receipt",
        deliverables={key: True for key in HANDOVER_CHECKS},
    )
    db.session.add(record)
    db.session.flush()
    with pytest.raises(ValueError, match="completed launch"):
        complete_handover(record)
    assert record.status == "draft"


def test_maintenance_schedule_is_idempotent_and_does_not_assert_work(project):
    now = datetime(2026, 10, 12, 9)
    agreement = MaintenanceAgreement(
        project_id=project.id,
        client_id=project.client_id,
        name="Care plan",
        website="https://example.com",
        monthly_fee=Decimal("1000"),
        billing_frequency="quarterly",
        start_date=(now - timedelta(days=10)).date(),
        renewal_date=(now + timedelta(days=7)).date(),
        covered_services="Review updates, backups and security.",
        status="active",
        acceptance_evidence="Signed maintenance terms",
        currency="PHP",
    )
    db.session.add(agreement)
    db.session.commit()
    assert process_recurring_maintenance(now) == {"tasks": 1, "invoices": 1}
    db.session.commit()
    assert process_recurring_maintenance(now) == {"tasks": 0, "invoices": 0}
    assert MaintenanceTask.query.count() == 1
    assert MaintenanceTask.query.one().status == "pending"
    assert not MaintenanceTask.query.one().evidence
    invoice = Invoice.query.one()
    assert invoice.status == "draft"
    assert invoice.total == Decimal("3000")
    assert agreement.renewal_date == (now + timedelta(days=7)).date()


def test_maintenance_completion_requires_execution_evidence(auth_client, project):
    now = utcnow()
    agreement = MaintenanceAgreement(
        project_id=project.id,
        client_id=project.client_id,
        name="Care plan",
        website="https://example.com",
        monthly_fee=Decimal("1000"),
        start_date=now.date(),
        renewal_date=(now + timedelta(days=30)).date(),
        covered_services="Review backups.",
        status="active",
        acceptance_evidence="Signed terms",
    )
    db.session.add(agreement)
    db.session.commit()
    process_recurring_maintenance(now)
    db.session.commit()
    task = MaintenanceTask.query.one()
    response = auth_client.post(
        "/maintenance", json={"action": "complete", "task_id": task.id, "evidence": ""}
    )
    assert response.status_code == 400
    assert task.status == "pending"
    response = auth_client.post(
        "/maintenance",
        json={
            "action": "complete",
            "task_id": task.id,
            "evidence": "Operator restored snapshot #123 into an isolated environment and verified content.",
        },
    )
    assert response.status_code == 200
    assert task.status == "completed"


def test_delivery_pages_render_and_are_authenticated(auth_client, client, project):
    for path in (
        f"/projects/{project.id}/discovery",
        f"/projects/{project.id}/design",
        f"/projects/{project.id}/testing",
        f"/projects/{project.id}/launch",
        f"/projects/{project.id}/handover",
        "/maintenance",
        "/support",
    ):
        response = auth_client.get(path)
        assert response.status_code == 200, path
    auth_client.post("/logout")
    assert auth_client.get("/maintenance").status_code == 302


def test_discovery_action_notes_require_owner_and_due_date(auth_client, project):
    response = auth_client.post(
        f"/projects/{project.id}/discovery",
        json={
            "action": "meeting",
            "title": "Discovery",
            "scheduled_at": "2026-10-15T09:00:00+08:00",
            "participants": "Administrator and fictional client",
            "agenda": "Discuss requirements",
        },
    )
    assert response.status_code == 200
    meeting = Meeting.query.one()
    assert meeting.scheduled_at.hour == 1  # Offset timestamps are normalized to UTC.
    response = auth_client.post(
        f"/projects/{project.id}/discovery",
        json={
            "action": "note",
            "meeting_id": meeting.id,
            "category": "action",
            "body": "Provide assets",
        },
    )
    assert response.status_code == 400
