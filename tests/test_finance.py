"""Financial invariants: cents, explicit verification and immutable snapshots."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Approval, Client, Invoice, Project, Proposal, Task
from app.services.invoice_service import (
    accept_proposal,
    calculate_proposal,
    calculate_totals,
    create_contract,
    create_invoice,
    create_payment_schedule,
    execute_contract,
    issue_invoice,
    payment_conditions_met,
    record_payment,
    revise_proposal,
    verify_payment,
)


@pytest.fixture
def project(app):
    client = Client(
        name="Fictional Owner",
        business_name="Fictional Coffee",
        email="coffee@example.com",
    )
    db.session.add(client)
    db.session.flush()
    project = Project(
        client_id=client.id, title="Fictional commerce site", currency="PHP"
    )
    db.session.add(project)
    db.session.commit()
    return project


def accepted_proposal(project, admin, total="100.01"):
    proposal = Proposal(
        reference="PROP-TEST",
        project_id=project.id,
        title="Commercial test",
        status="draft",
    )
    calculate_proposal(
        proposal, [{"description": "Website", "quantity": "1", "unit_price": total}]
    )
    db.session.add(proposal)
    db.session.flush()
    proposal.status = "approved"
    db.session.flush()
    accept_proposal(proposal, "Fictional Owner", "Written client acceptance", admin.id)
    db.session.commit()
    return proposal


def executed_contract(project, admin, total="100.01"):
    contract = create_contract(accepted_proposal(project, admin, total))
    execute_contract(
        contract, "Client and developer", "Signed agreement attachment", admin.id
    )
    db.session.commit()
    return contract


def issued_invoice(project, total="100.01", kind="deposit"):
    invoice = create_invoice(
        project,
        [{"description": "Website", "quantity": "1", "unit_price": total}],
        kind=kind,
    )
    issue_invoice(invoice)
    db.session.commit()
    return invoice


def test_decimal_calculation_tax_discount_contingency_and_recurring():
    totals = calculate_totals(
        [
            {
                "description": "Labor",
                "quantity": "1.5",
                "unit_price": "100.10",
                "kind": "labor",
            },
            {"description": "Fixed", "quantity": 1, "unit_price": "20.00"},
            {
                "description": "License",
                "quantity": 1,
                "unit_price": "5.00",
                "kind": "expense",
            },
            {
                "description": "Monthly hosting",
                "quantity": 1,
                "unit_price": "7.50",
                "kind": "recurring",
            },
        ],
        contingency="10",
        discount="5.15",
        tax_rate="12",
    )
    assert totals["subtotal"] == Decimal("175.15")
    assert totals["tax"] == Decimal("21.60")
    assert totals["total"] == Decimal("201.60")
    assert totals["recurring_total"] == Decimal("7.50")
    assert calculate_totals(
        [{"description": "Rounding", "quantity": ".5", "unit_price": ".01"}]
    )["total"] == Decimal(".01")


@pytest.mark.parametrize(
    "item",
    [
        {"description": "Bad", "quantity": "-1", "unit_price": 100},
        {"description": "Bad", "quantity": "NaN", "unit_price": 100},
        {"description": "Bad", "unit_price": "Infinity"},
        {"description": "", "unit_price": 10},
        {"description": "Bad", "unit_price": "-.01"},
    ],
)
def test_invalid_financial_values_rejected(item):
    with pytest.raises(ValueError):
        calculate_totals([item])


def test_discount_and_tax_bounds():
    items = [{"description": "Work", "unit_price": 100}]
    with pytest.raises(ValueError, match="Discount"):
        calculate_totals(items, discount=101)
    with pytest.raises(ValueError, match="Tax rate"):
        calculate_totals(items, tax_rate=101)


def test_payment_schedule_exact_allocation_and_duplicate_guard(project, admin):
    contract = executed_contract(project, admin)
    installments = create_payment_schedule(contract, ["40", "30", "30"])
    db.session.commit()
    assert [i.total for i in installments] == [
        Decimal("40.00"),
        Decimal("30.00"),
        Decimal("30.01"),
    ]
    assert sum(i.total for i in installments) == contract.total
    assert [i.kind for i in installments] == ["deposit", "milestone", "final"]
    assert all(i.status == "draft" for i in installments)
    with pytest.raises(ValueError, match="already"):
        create_payment_schedule(contract, [50, 50])
    assert Invoice.query.count() == 3


def test_full_upfront_payment_satisfies_deposit_and_final_conditions(project, admin):
    from app.services.invoice_service import final_payment_conditions_met

    contract = executed_contract(project, admin)
    invoice = create_payment_schedule(contract, [100])[0]
    issue_invoice(invoice)
    db.session.commit()
    payment = record_payment(invoice, invoice.total, "bank", "TXN-UPFRONT")
    db.session.commit()
    assert not payment_conditions_met(project)
    assert not final_payment_conditions_met(project)
    verify_payment(payment, "Independent bank statement", admin.id)
    db.session.commit()
    assert payment_conditions_met(project)
    assert final_payment_conditions_met(project)


def test_paid_but_underbilled_project_does_not_satisfy_final_conditions(project, admin):
    from app.services.invoice_service import final_payment_conditions_met

    executed_contract(project, admin, total="100")
    for kind in ("deposit", "final"):
        invoice = issued_invoice(project, total="10", kind=kind)
        payment = record_payment(invoice, "10", "bank", f"TXN-UNDERBILLED-{kind}")
        verify_payment(payment, "Independent bank record", admin.id)
        db.session.commit()
    assert payment_conditions_met(project)
    assert not final_payment_conditions_met(project)


def test_reported_payment_does_not_reduce_balance_and_duplicate_is_rejected(
    project, admin
):
    invoice = issued_invoice(project, "150.25")
    payment = record_payment(invoice, "100.10", "bank transfer", "TXN-REPORTED")
    db.session.commit()
    assert invoice.paid == 0
    assert invoice.balance == Decimal("150.25")
    assert invoice.status == "issued"
    with pytest.raises(ValueError, match="already recorded"):
        record_payment(invoice, "1", "bank", "TXN-REPORTED")
    with pytest.raises(ValueError, match="evidence"):
        verify_payment(payment, "", admin.id)
    verify_payment(payment, "Bank entry matching TXN-REPORTED", admin.id)
    db.session.commit()
    assert invoice.paid == Decimal("100.10")
    assert invoice.balance == Decimal("50.15")
    assert invoice.status == "partially_paid"
    verify_payment(payment, "Repeated command", admin.id)
    db.session.commit()
    assert invoice.paid == Decimal("100.10")


def test_pending_payment_cannot_overpay_when_verified_later(project, admin):
    invoice = issued_invoice(project, "100")
    first = record_payment(invoice, 80, "bank", "TXN-FIRST")
    second = record_payment(invoice, 80, "bank", "TXN-SECOND")
    db.session.commit()
    verify_payment(first, "Independent entry", admin.id)
    db.session.commit()
    with pytest.raises(ValueError, match="balance"):
        verify_payment(second, "Independent entry", admin.id)
    with pytest.raises(ValueError, match="balance"):
        record_payment(invoice, 21, "bank", "TXN-THIRD")
    assert invoice.balance == Decimal("20.00")
    assert not second.verified


def test_issued_invoice_and_lines_preserve_history(project):
    invoice = issued_invoice(project)
    snapshot = dict(invoice.client_snapshot)
    invoice.client.business_name = "Renamed business"
    db.session.commit()
    assert invoice.client_snapshot == snapshot
    invoice.total = Decimal("1.00")
    with pytest.raises(ValueError, match="snapshot"):
        db.session.commit()
    db.session.rollback()
    assert invoice.total == Decimal("100.01")
    invoice.items[0].amount = Decimal("1.00")
    with pytest.raises(ValueError, match="line items"):
        db.session.commit()
    db.session.rollback()
    db.session.delete(invoice)
    with pytest.raises(ValueError, match="(line items|cannot be deleted)"):
        db.session.commit()
    db.session.rollback()
    assert Invoice.query.count() == 1
    from app.models import InvoiceItem

    db.session.add(
        InvoiceItem(
            invoice_id=invoice.id,
            description="Injected item",
            quantity=1,
            unit_price=1,
            amount=1,
        )
    )
    with pytest.raises(ValueError, match="line items"):
        db.session.commit()
    db.session.rollback()


def test_verified_payments_and_executed_contracts_are_immutable(project, admin):
    contract = executed_contract(project, admin)
    contract.body = "Replaced terms"
    with pytest.raises(ValueError, match="immutable"):
        db.session.commit()
    db.session.rollback()
    invoice = issued_invoice(project)
    payment = record_payment(invoice, "100.01", "bank", "TXN-FROZEN")
    verify_payment(payment, "Independent bank record", admin.id)
    db.session.commit()
    payment.verified = False
    with pytest.raises(ValueError, match="cannot be altered"):
        db.session.commit()
    db.session.rollback()
    assert payment.verified and invoice.balance == 0


def test_proposal_acceptance_requires_evidence_and_revision_preserves_original(
    project, admin
):
    proposal = accepted_proposal(project, admin)
    accepted_amount = proposal.total
    revised = revise_proposal(proposal)
    calculate_proposal(
        revised,
        [{"description": "Expanded website", "quantity": 1, "unit_price": "250"}],
    )
    db.session.commit()
    assert revised.version == 2 and revised.previous_id == proposal.id
    assert revised.status == "draft"
    assert proposal.status == "accepted" and proposal.total == accepted_amount
    assert revised.total == Decimal("250.00")
    proposal.accepted_at = None
    with pytest.raises(ValueError, match="frozen"):
        db.session.commit()
    db.session.rollback()
    assert proposal.accepted_at
    revised.status = "approved"
    revised.expires_at = date.today() - timedelta(days=1)
    # Expiry is set while the draft is editable, before approval is persisted.
    db.session.commit()
    with pytest.raises(ValueError, match="expired"):
        accept_proposal(revised, "Client", "Written acceptance", admin.id)


def test_finance_http_json_forms_pdf_and_invalid_foreign_keys(
    auth_client, project, admin
):
    db.session.add(
        Approval(
            project_id=project.id,
            stage_number=4,
            kind="scope",
            decision="approved",
            person="Owner",
            evidence="Scope agreement",
            actor_id=admin.id,
        )
    )
    db.session.commit()
    response = auth_client.post(
        "/proposals/new",
        json={
            "project_id": project.id,
            "title": "Website",
            "items": [
                {"description": "Website work", "quantity": 2, "unit_price": "100.25"}
            ],
            "tax_rate": 12,
        },
    )
    assert response.status_code == 200
    proposal_id = response.json["id"]
    assert (
        auth_client.post(f"/proposals/{proposal_id}/approve", json={}).status_code
        == 200
    )
    assert (
        auth_client.post(
            f"/proposals/{proposal_id}/accept", json={"person": "Client"}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            f"/proposals/{proposal_id}/accept",
            json={"person": "Client", "evidence": "Acceptance email"},
        ).status_code
        == 200
    )
    proposal_pdf = auth_client.get(f"/proposals/{proposal_id}/pdf")
    assert proposal_pdf.status_code == 200 and proposal_pdf.data.startswith(b"%PDF")
    invalid = auth_client.post(
        "/invoices/new",
        json={
            "project_id": 999999,
            "items": [{"description": "Work", "unit_price": 1}],
        },
    )
    assert invalid.status_code == 400 and "does not exist" in invalid.json["error"]
    invoice = issued_invoice(project)
    for path in (
        "/proposals",
        "/proposals/new",
        f"/proposals/{proposal_id}",
        "/contracts",
        "/contracts/new",
        "/invoices",
        "/invoices/new",
        f"/invoices/{invoice.id}",
        "/payments",
        "/payments/new",
        "/expenses",
        "/expenses/new",
    ):
        assert auth_client.get(path).status_code == 200, path
    invoice_pdf = auth_client.get(f"/invoices/{invoice.id}/pdf")
    assert invoice_pdf.status_code == 200 and invoice_pdf.data.startswith(b"%PDF")


def test_financial_approvals_and_event_tasks_are_idempotent(project, admin):
    from app.models import ScheduledJob

    proposal = accepted_proposal(project, admin)
    accept_proposal(proposal, "Fictional Owner", "Repeated event", admin.id)
    db.session.commit()
    assert Approval.query.filter_by(project_id=project.id, kind="proposal").count() == 1
    assert (
        Task.query.filter_by(event_key=f"proposal:{proposal.id}:accepted").count() == 1
    )
    assert (
        ScheduledJob.query.filter_by(
            event_key=f"proposal:{proposal.id}:accepted:event"
        ).count()
        == 1
    )


def test_invoice_drafts_editable_until_issued(auth_client, project):
    invoice = create_invoice(
        project, [{"description": "Draft line", "quantity": 1, "unit_price": 100}]
    )
    db.session.commit()
    response = auth_client.post(
        f"/invoices/{invoice.id}/edit",
        json={
            "items": [
                {"description": "Agreed line", "quantity": 1, "unit_price": "125.50"}
            ],
            "due_at": "2027-01-15",
            "instructions": "Pay by bank transfer",
            "tax_rate": 12,
        },
    )
    assert response.status_code == 200
    assert invoice.total == Decimal("140.56")
    assert invoice.due_at == date(2027, 1, 15)
    assert auth_client.post(f"/invoices/{invoice.id}/issue", json={}).status_code == 200
    assert (
        auth_client.post(f"/invoices/{invoice.id}/edit", json={"items": []}).status_code
        == 400
    )
