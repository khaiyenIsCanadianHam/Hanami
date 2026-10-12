"""An isolated fictional agency journey with real cross-module gate checks."""

from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (
    Client,
    Lead,
    Inquiry,
    Project,
    ProjectStage,
    Requirement,
    Task,
    Approval,
    Proposal,
    DesignSubmission,
    TestCase as Case,
    DeploymentRecord,
    HandoverRecord,
    StageTransition,
)
from app.services.lifecycle_service import STAGE_MAP, blockers
from app.services.invoice_service import (
    calculate_proposal,
    accept_proposal,
    create_contract,
    execute_contract,
    create_payment_schedule,
    issue_invoice,
    record_payment,
    verify_payment,
)
from app.services.delivery_service import (
    approve_design,
    record_test,
    seed_test_cases,
    complete_deployment,
    complete_handover,
    LAUNCH_CHECKS,
    HANDOVER_CHECKS,
)


def post(client, path, data=None):
    response = client.post(path, data=data or {})
    assert response.status_code in (200, 302), response.get_data(as_text=True)
    return response


def approve(client, project, number, kind="stage"):
    post(
        client,
        f"/projects/{project.id}/approvals",
        {
            "stage_number": str(number),
            "kind": kind,
            "decision": "approved",
            "person": "Luna Coffee House owner",
            "evidence": f"Fictional signed decision for {kind}, stage {number}.",
        },
    )


def prepare_stage(client, project, number):
    data = {
        key: f"Fictional reviewed {label.lower()}"
        for key, label in STAGE_MAP[number]["fields"]
    }
    data.update(
        {
            f"requirement_{row.id}": "on"
            for row in Requirement.query.filter_by(
                project_id=project.id, stage_number=number
            )
        }
    )
    post(client, f"/projects/{project.id}/stages/{number}", data)
    post(client, f"/projects/{project.id}/stages/{number}/submit")
    approve(client, project, number)


def finish_stage(client, project, number):
    post(client, f"/projects/{project.id}/stages/{number}/complete")
    db.session.refresh(project)
    assert (
        ProjectStage.query.filter_by(project_id=project.id, number=number).one().status
        == "completed"
    )
    assert project.current_stage == min(number + 1, 14)


def test_fictional_lead_to_completed_handover(auth_client, admin):
    # HTTP CRM entry preserves its origin and requires a deliberate conversion.
    post(
        auth_client,
        "/leads/new",
        {
            "name": "Luna Owner",
            "business_name": "Luna Coffee House",
            "email": "luna@example.com",
            "source": "Referral",
            "service": "Business website",
            "budget": "15000",
            "status": "qualified",
        },
    )
    lead = Lead.query.one()
    assert auth_client.post(f"/leads/{lead.id}/convert").status_code == 400
    post(auth_client, f"/leads/{lead.id}/convert", {"confirmed": "yes"})
    client_record = Client.query.one()
    assert client_record.lead_id == lead.id
    post(auth_client, f"/leads/{lead.id}/convert", {"confirmed": "yes"})
    assert Client.query.count() == 1
    questionnaire = {f"question_{i}": "Fictional reviewed answer" for i in range(15)}
    post(
        auth_client,
        "/inquiries/new",
        {
            "client_id": str(client_record.id),
            "lead_id": str(lead.id),
            "website_type": "Coffee shop business website",
            "business_description": "Fictional independent coffee shop",
            "features": "Home, menu, about, contact",
            "budget": "15000",
            "communication": "email",
            **questionnaire,
        },
    )
    assert Inquiry.query.one().status == "complete"
    post(
        auth_client,
        "/projects/new",
        {
            "client_id": str(client_record.id),
            "title": "Luna business website",
            "revision_allowance": "2",
        },
    )
    project = Project.query.one()
    assert len(project.stages) == 14
    assert (
        auth_client.post(f"/projects/{project.id}/stages/1/complete").status_code == 400
    )

    for number in (1, 2, 3):
        prepare_stage(auth_client, project, number)
        finish_stage(auth_client, project, number)

    post(
        auth_client,
        f"/projects/{project.id}/scope",
        {
            "name": "Responsive coffee website",
            "description": "Home, menu, about, contact and map",
            "hours": "30",
            "rate": "500",
            "included": "on",
            "acceptance_criteria": "Approved content works on desktop and mobile; contact form validated.",
        },
    )
    prepare_stage(auth_client, project, 4)
    assert (
        auth_client.post(f"/projects/{project.id}/stages/4/complete").status_code == 400
    )
    approve(auth_client, project, 4, "scope")
    finish_stage(auth_client, project, 4)

    proposal = Proposal(
        reference="PROP-FICTIONAL-E2E",
        project_id=project.id,
        title="Luna website",
        status="draft",
    )
    calculate_proposal(
        proposal,
        [
            {
                "description": "Business website",
                "quantity": "30",
                "unit_price": "500",
                "kind": "labor",
            }
        ],
    )
    db.session.add(proposal)
    db.session.flush()
    proposal.status = "approved"
    db.session.flush()
    accept_proposal(
        proposal, "Luna Owner", "Fictional written quotation acceptance", admin.id
    )
    db.session.commit()
    assert proposal.total == Decimal("15000.00")
    prepare_stage(auth_client, project, 5)
    finish_stage(auth_client, project, 5)

    contract = create_contract(proposal)
    execute_contract(
        contract,
        "Luna Owner",
        "Fictional signed agreement independently checked",
        admin.id,
    )
    installments = create_payment_schedule(contract, [40, 30, 30])
    for invoice in installments:
        issue_invoice(invoice)
    db.session.commit()
    assert [invoice.total for invoice in installments] == [
        Decimal("6000.00"),
        Decimal("4500.00"),
        Decimal("4500.00"),
    ]
    prepare_stage(auth_client, project, 6)
    deposit = record_payment(
        installments[0], "6000", "bank transfer", "FICTIONAL-DEPOSIT"
    )
    db.session.commit()
    assert installments[0].balance == Decimal("6000.00")
    assert (
        auth_client.post(f"/projects/{project.id}/stages/6/complete").status_code == 400
    )
    verify_payment(deposit, "Fictional independently checked bank statement", admin.id)
    db.session.commit()
    finish_stage(auth_client, project, 6)
    prepare_stage(auth_client, project, 7)
    finish_stage(auth_client, project, 7)

    design = DesignSubmission(
        project_id=project.id,
        title="Responsive layouts",
        version=1,
        reference_url="https://example.com/fictional-design",
        description="Desktop and mobile views",
    )
    db.session.add(design)
    db.session.commit()
    prepare_stage(auth_client, project, 8)
    assert (
        auth_client.post(f"/projects/{project.id}/stages/8/complete").status_code == 400
    )
    approve_design(
        design, "Luna Owner", "Fictional approval of design version 1", admin.id
    )
    milestone_payment = record_payment(
        installments[1], "4500", "bank transfer", "FICTIONAL-DESIGN"
    )
    verify_payment(
        milestone_payment, "Fictional bank statement: design milestone", admin.id
    )
    db.session.commit()
    finish_stage(auth_client, project, 8)

    prepare_stage(auth_client, project, 9)
    assert (
        auth_client.post(f"/projects/{project.id}/stages/9/complete").status_code == 400
    )
    for task in Task.query.filter_by(project_id=project.id, stage_number=9):
        post(auth_client, f"/tasks/{task.id}/status", {"status": "completed"})
    finish_stage(auth_client, project, 9)

    seed_test_cases(project)
    db.session.commit()
    prepare_stage(auth_client, project, 10)
    assert (
        auth_client.post(f"/projects/{project.id}/stages/10/complete").status_code
        == 400
    )
    for case in Case.query.filter_by(project_id=project.id):
        record_test(
            case,
            "passed",
            "Fictional recorded execution met expected result",
            "QA administrator",
            "Fictional evidence for staging version 1",
        )
    db.session.commit()
    finish_stage(auth_client, project, 10)

    prepare_stage(auth_client, project, 11)
    approve(auth_client, project, 11, "acceptance")
    assert (
        auth_client.post(f"/projects/{project.id}/stages/11/complete").status_code
        == 400
    )
    final_payment = record_payment(
        installments[2], "4500", "bank transfer", "FICTIONAL-FINAL"
    )
    verify_payment(
        final_payment, "Fictional bank statement: final settlement", admin.id
    )
    db.session.commit()
    finish_stage(auth_client, project, 11)

    prepare_stage(auth_client, project, 12)
    deployment = DeploymentRecord(
        project_id=project.id,
        production_url="https://example.com/luna",
        hosting_provider="Fictional host",
        method="Reviewed manual deployment",
        version="v1.0.0",
        rollback_plan="Restore reviewed backup",
        backup_evidence="Fictional restore drill passed",
        checklist={key: True for key in LAUNCH_CHECKS},
    )
    db.session.add(deployment)
    db.session.commit()
    with pytest.raises(ValueError, match="launch authorization"):
        complete_deployment(
            deployment, "Fictional post-deployment verification", admin.id
        )
    approve(auth_client, project, 12, "launch")
    complete_deployment(deployment, "Fictional production smoke test passed", admin.id)
    db.session.commit()
    finish_stage(auth_client, project, 12)

    prepare_stage(auth_client, project, 13)
    handover = HandoverRecord(
        project_id=project.id,
        recipient="Luna Owner",
        production_url="https://example.com/luna",
        documentation="Fictional user guide, ownership inventory and backup guide",
        evidence="Fictional client receipt confirmed",
        deliverables={key: True for key in HANDOVER_CHECKS},
    )
    db.session.add(handover)
    db.session.flush()
    complete_handover(handover, admin.id)
    db.session.commit()
    finish_stage(auth_client, project, 13)
    prepare_stage(auth_client, project, 14)
    finish_stage(auth_client, project, 14)

    assert project.status == "completed"
    assert project.progress == 100
    assert StageTransition.query.filter_by(project_id=project.id).count() == 14
    assert all(
        invoice.balance == 0 and invoice.status == "paid" for invoice in installments
    )
    assert HandoverRecord.query.one().status == "completed"
    assert Approval.query.filter_by(project_id=project.id, kind="launch").count() == 1
    assert auth_client.get(f"/projects/{project.id}").status_code == 200


def test_reopening_invalidates_stale_stage_decisions(auth_client, admin):
    post(
        auth_client,
        "/clients/new",
        {"name": "Fictional client", "business_name": "Fictional studio"},
    )
    person = Client.query.one()
    post(
        auth_client,
        "/projects/new",
        {"client_id": str(person.id), "title": "Review workflow"},
    )
    project = Project.query.one()
    prepare_stage(auth_client, project, 1)
    finish_stage(auth_client, project, 1)
    post(
        auth_client,
        f"/projects/{project.id}/transition",
        {"target": "1", "reason": "Client changed qualification details"},
    )
    assert project.current_stage == 1
    assert "Record explicit stage approval with a name and evidence." in blockers(
        project, 1
    )
    assert (
        auth_client.post(f"/projects/{project.id}/stages/1/complete").status_code == 400
    )
    assert Approval.query.filter_by(project_id=project.id, stage_number=1).count() == 1
    approve(auth_client, project, 1)
    finish_stage(auth_client, project, 1)
    assert StageTransition.query.filter_by(project_id=project.id).count() == 3


def test_full_upfront_payment_requires_the_complete_contract_amount(auth_client, admin):
    from app.services.invoice_service import (
        create_invoice,
        final_payment_conditions_met,
    )

    post(
        auth_client,
        "/clients/new",
        {"name": "Upfront client", "business_name": "Fictional studio"},
    )
    person = Client.query.one()
    post(
        auth_client,
        "/projects/new",
        {"client_id": str(person.id), "title": "Upfront project"},
    )
    project = Project.query.one()
    proposal = Proposal(
        reference="PROP-UPFRONT-E2E",
        project_id=project.id,
        title="Upfront website",
        status="draft",
    )
    calculate_proposal(
        proposal,
        [{"description": "Business website", "quantity": "1", "unit_price": "15000"}],
    )
    db.session.add(proposal)
    db.session.flush()
    proposal.status = "approved"
    db.session.flush()
    accept_proposal(
        proposal, "Fictional owner", "Fictional accepted quotation", admin.id
    )
    contract = create_contract(proposal)
    execute_contract(
        contract, "Fictional owner", "Fictional contract execution", admin.id
    )
    invoice = create_payment_schedule(contract, [100])[0]
    issue_invoice(invoice)
    db.session.commit()
    assert invoice.kind == "deposit"
    assert not final_payment_conditions_met(project)
    payment = record_payment(invoice, "15000", "bank transfer", "FICTIONAL-UPFRONT")
    db.session.commit()
    assert not final_payment_conditions_met(project)
    verify_payment(payment, "Fictional independent bank evidence", admin.id)
    db.session.commit()
    assert final_payment_conditions_met(project)

    extra = create_invoice(
        project,
        [{"description": "Approved extra scope", "quantity": "1", "unit_price": "500"}],
        kind="adjustment",
    )
    db.session.commit()
    assert not final_payment_conditions_met(project), (
        "Unissued extra scope must still be reconciled"
    )
    issue_invoice(extra)
    db.session.commit()
    assert not final_payment_conditions_met(project), (
        "Outstanding adjustment must block final settlement"
    )
