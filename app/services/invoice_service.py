"""Decimal financial calculations and deliberate commercial approvals.

Services flush as needed but leave the transaction commit to their caller.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from app.extensions import db
from app.models.base import utcnow
from app.models.finance import (
    Contract,
    Invoice,
    InvoiceItem,
    Payment,
    Proposal,
    ProposalItem,
)
from app.services.common import audit, log_activity


CENT = Decimal("0.01")


def number(value, name="Amount", minimum=Decimal("0"), maximum=Decimal("9999999999")):
    try:
        result = Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be a valid number.") from None
    if not result.is_finite() or result < minimum or result > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return result


def currency_amount(value, name="Amount"):
    return number(value, name).quantize(CENT, rounding=ROUND_HALF_UP)


def reference(prefix):
    return f"{prefix}-{utcnow():%Y%m%d}-{uuid4().hex[:8].upper()}"


def _items(items):
    if not items or not isinstance(items, list) or len(items) > 250:
        raise ValueError("Supply between one and 250 line items.")
    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every line item must be an object.")
        description = str(item.get("description", "")).strip()
        if not description or len(description) > 500:
            raise ValueError(
                "Each line item needs a description of up to 500 characters."
            )
        quantity = number(
            item.get("quantity", 1), "Quantity", Decimal("0.0001"), Decimal("99999999")
        ).quantize(Decimal("0.0001"))
        unit_price = currency_amount(item.get("unit_price", 0), "Unit price")
        amount = currency_amount(quantity * unit_price)
        kind = item.get("kind", "fixed")
        if kind not in {"labor", "fixed", "expense", "recurring"}:
            raise ValueError("Unknown quotation item kind.")
        result.append(
            dict(
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                amount=amount,
                kind=kind,
            )
        )
    return result


def calculate_totals(items, discount=0, tax_rate=0, contingency=0):
    normalized = _items(items)
    subtotal = sum(
        (i["amount"] for i in normalized if i["kind"] != "recurring"), Decimal("0.00")
    )
    recurring = sum(
        (i["amount"] for i in normalized if i["kind"] == "recurring"), Decimal("0.00")
    )
    contingency = currency_amount(contingency, "Contingency")
    discount = currency_amount(discount, "Discount")
    tax_rate = number(tax_rate, "Tax rate", maximum=Decimal("100")).quantize(
        Decimal("0.0001")
    )
    if discount > subtotal + contingency:
        raise ValueError("Discount cannot exceed the subtotal plus contingency.")
    base = subtotal + contingency - discount
    tax = currency_amount(base * tax_rate / 100, "Tax")
    total = currency_amount(base + tax, "Total")
    return dict(
        items=normalized,
        subtotal=subtotal,
        contingency=contingency,
        discount=discount,
        tax_rate=tax_rate,
        tax=tax,
        total=total,
        recurring_total=recurring,
    )


def calculate_proposal(proposal, items=None):
    if proposal.status not in (None, "draft"):
        raise ValueError("Revise a finalized proposal before changing prices.")
    inputs = (
        items
        if items is not None
        else [
            dict(
                description=i.description,
                quantity=i.quantity,
                unit_price=i.unit_price,
                kind=i.kind,
            )
            for i in proposal.items
        ]
    )
    totals = calculate_totals(
        inputs, proposal.discount, proposal.tax_rate, proposal.contingency
    )
    if items is not None:
        proposal.items = [ProposalItem(**i) for i in totals.pop("items")]
    else:
        totals.pop("items")
    for key, value in totals.items():
        setattr(proposal, key, value)
    return proposal


def revise_proposal(original):
    revised = Proposal(
        reference=reference("PROP"),
        project_id=original.project_id,
        previous_id=original.id,
        version=original.version + 1,
        title=original.title,
        status="draft",
        currency=original.currency,
        overview=original.overview,
        deliverables=original.deliverables,
        exclusions=original.exclusions,
        timeline=original.timeline,
        terms=original.terms,
        expires_at=original.expires_at,
        discount=original.discount,
        tax_rate=original.tax_rate,
        contingency=original.contingency,
    )
    calculate_proposal(
        revised,
        [
            dict(
                description=i.description,
                quantity=i.quantity,
                unit_price=i.unit_price,
                kind=i.kind,
            )
            for i in original.items
        ],
    )
    db.session.add(revised)
    db.session.flush()
    audit("revise", "Proposal", revised.id, f"Revision of proposal {original.id}")
    return revised


def _approval_task(project_id, key, title, stage):
    from app.models.core import Task

    if not Task.query.filter_by(event_key=key).first():
        db.session.add(
            Task(
                project_id=project_id,
                stage_number=stage,
                title=title,
                status="todo",
                priority="high",
                event_key=key,
            )
        )


def _approval(project_id, stage, kind, person, evidence, actor_id):
    from app.models.core import Approval

    person, evidence = str(person or "").strip(), str(evidence or "").strip()
    if not person or not evidence:
        raise ValueError("Record the approving person and acceptance evidence.")
    if not actor_id:
        raise ValueError("An administrator must confirm the approval.")
    db.session.add(
        Approval(
            project_id=project_id,
            stage_number=stage,
            kind=kind,
            decision="approved",
            person=person,
            evidence=evidence,
            actor_id=actor_id,
        )
    )


def _event(name, project, key):
    from app.services.automation_service import trigger_event

    trigger_event(name, project, event_key=key)


def accept_proposal(proposal, person, evidence, actor_id):
    if proposal.status == "accepted":
        return proposal
    if proposal.status not in {"approved", "sent"}:
        raise ValueError("Approve the proposal before recording client acceptance.")
    if proposal.expires_at and proposal.expires_at < utcnow().date():
        raise ValueError(
            "This proposal has expired. Create a new version before acceptance."
        )
    _approval(proposal.project_id, 5, "proposal", person, evidence, actor_id)
    proposal.status = "accepted"
    proposal.accepted_at = utcnow()
    proposal.acceptance_person = str(person).strip()
    proposal.acceptance_evidence = str(evidence).strip()
    proposal.accepted_by = actor_id
    proposal.project.contract_value = proposal.total
    _approval_task(
        proposal.project_id,
        f"proposal:{proposal.id}:accepted",
        "Prepare development agreement",
        6,
    )
    log_activity(
        "proposal_accepted",
        f"Client acceptance recorded for {proposal.reference}",
        project_id=proposal.project_id,
    )
    audit(
        "accept",
        "Proposal",
        proposal.id,
        "Client evidence recorded and administrator confirmed.",
    )
    _event(
        "proposal.accepted", proposal.project, f"proposal:{proposal.id}:accepted:event"
    )
    return proposal


def create_contract(proposal, body=None):
    if proposal.status != "accepted":
        raise ValueError("A contract requires an accepted proposal.")
    project = proposal.project
    text = (
        body
        or f"""DRAFT — REQUIRES PROFESSIONAL REVIEW

Development agreement for {project.title}
Client: {project.client.business_name or project.client.name}
Proposal: {proposal.reference} (version {proposal.version})
Scope and deliverables: {proposal.deliverables or proposal.overview}
Exclusions: {proposal.exclusions or "Record exclusions before execution."}
Schedule: {proposal.timeline or "Agree the schedule before execution."}
Contract value: {proposal.currency} {proposal.total:.2f}
Payment terms: {proposal.terms or "Record the agreed deposit and milestone payment terms."}
Revision allowance: {project.revision_allowance}

Change requests require written scope, pricing and schedule approval before work begins.
Intellectual property transfer, confidentiality, cancellation and termination provisions must be agreed in writing.
Specify warranty scope and duration, maintenance exclusions and dispute handling before signing.
Signature — Client: __________________  Date: __________
Signature — Developer: _______________  Date: __________

This draft is a working template and requires professional review for your circumstances."""
    )
    contract = Contract(
        reference=reference("CON"),
        project_id=project.id,
        proposal_id=proposal.id,
        body=text,
        total=proposal.total,
        currency=proposal.currency,
        status="draft",
        version=1,
    )
    db.session.add(contract)
    db.session.flush()
    audit("create", "Contract", contract.id, "Draft generated from accepted proposal.")
    return contract


def execute_contract(contract, person, evidence, actor_id):
    if contract.status == "executed":
        return contract
    if contract.status != "draft":
        raise ValueError("Only a draft contract may be executed.")
    _approval(contract.project_id, 6, "contract", person, evidence, actor_id)
    contract.status = "executed"
    contract.executed_at = utcnow()
    contract.signed_by = str(person).strip()
    contract.evidence = str(evidence).strip()
    contract.confirmed_by = actor_id
    _approval_task(
        contract.project_id,
        f"contract:{contract.id}:executed",
        "Issue initial project invoice",
        6,
    )
    log_activity(
        "contract_executed",
        f"Execution evidence recorded for {contract.reference}",
        project_id=contract.project_id,
    )
    audit("execute", "Contract", contract.id, "Signed agreement evidence confirmed.")
    _event(
        "contract.executed", contract.project, f"contract:{contract.id}:executed:event"
    )
    return contract


def create_invoice(
    project,
    items,
    kind="milestone",
    due_at=None,
    discount=0,
    tax_rate=0,
    instructions="",
    contract_id=None,
    schedule_key=None,
):
    if kind not in {"deposit", "milestone", "final", "maintenance", "adjustment"}:
        raise ValueError("Unknown invoice kind.")
    totals = calculate_totals(items, discount=discount, tax_rate=tax_rate)
    if any(i["kind"] == "recurring" for i in totals["items"]):
        raise ValueError("Invoice line items must represent amounts currently due.")
    if totals["total"] <= 0:
        raise ValueError("Invoice total must be greater than zero.")
    if contract_id:
        contract = db.session.get(Contract, int(contract_id))
        if not contract or contract.project_id != project.id:
            raise ValueError("The contract must belong to the selected project.")
    if isinstance(due_at, str):
        try:
            due_at = date.fromisoformat(due_at)
        except ValueError:
            raise ValueError("Due date must use YYYY-MM-DD.") from None
    invoice = Invoice(
        reference=reference("INV"),
        project_id=project.id,
        client_id=project.client_id,
        contract_id=contract_id,
        currency=project.currency or "PHP",
        status="draft",
        kind=kind,
        due_at=due_at,
        discount=totals["discount"],
        tax_rate=totals["tax_rate"],
        subtotal=totals["subtotal"],
        tax=totals["tax"],
        total=totals["total"],
        instructions=str(instructions or ""),
        schedule_key=schedule_key,
    )
    invoice.items = [
        InvoiceItem(**{k: v for k, v in i.items() if k != "kind"})
        for i in totals["items"]
    ]
    db.session.add(invoice)
    db.session.flush()
    audit("create", "Invoice", invoice.id, "Invoice draft created.")
    return invoice


def issue_invoice(invoice):
    if invoice.issued_at:
        return invoice
    if invoice.status != "draft" or not invoice.items:
        raise ValueError("Only a draft invoice with line items can be issued.")
    db.session.flush()  # Persist draft line items before freezing their snapshot.
    client, project = invoice.client, invoice.project
    invoice.client_snapshot = {
        key: getattr(client, key, "")
        for key in ("name", "business_name", "email", "phone", "location")
    }
    invoice.project_snapshot = {"reference": project.reference, "title": project.title}
    invoice.issued_at = utcnow()
    invoice.status = "issued"
    log_activity(
        "invoice_issued",
        f"Issued {invoice.reference} for {invoice.currency} {invoice.total:.2f}",
        client_id=invoice.client_id,
        project_id=invoice.project_id,
    )
    audit("issue", "Invoice", invoice.id, "Financial snapshot frozen.")
    _event("invoice.issued", invoice.project, f"invoice:{invoice.id}:issued:event")
    return invoice


def record_payment(invoice, amount, method, payment_reference, received_at=None):
    if not invoice.issued_at or invoice.status == "void":
        raise ValueError("Payments require an issued, non-void invoice.")
    amount = currency_amount(amount)
    if amount <= 0 or amount > invoice.balance:
        raise ValueError(
            "Payment must be positive and cannot exceed the outstanding balance."
        )
    method, payment_reference = (
        str(method or "").strip(),
        str(payment_reference or "").strip(),
    )
    if (
        not method
        or not payment_reference
        or len(method) > 100
        or len(payment_reference) > 100
    ):
        raise ValueError(
            "Record a payment method and unique transaction reference (up to 100 characters)."
        )
    if Payment.query.filter_by(reference=payment_reference).first():
        raise ValueError("This transaction reference is already recorded.")
    payment = Payment(
        invoice=invoice,
        amount=amount,
        method=method,
        reference=payment_reference,
        received_at=received_at or utcnow(),
        verified=False,
    )
    db.session.add(payment)
    db.session.flush()
    audit(
        "record",
        "Payment",
        payment.id,
        "Reported payment; awaits administrator verification.",
    )
    return payment


def verify_payment(payment, evidence, actor_id):
    if payment.verified:
        return payment
    invoice = payment.invoice
    if not actor_id or not str(evidence or "").strip():
        raise ValueError(
            "An administrator and independent payment evidence are required."
        )
    # Acquire the invoice's write lock before reading verified balances. This
    # serializes simultaneous verification requests on SQLite and PostgreSQL.
    # A cached relationship must not decide whether a second payment overpays.
    db.session.execute(
        db.update(Invoice)
        .where(Invoice.id == invoice.id)
        .values(status=Invoice.status),
        execution_options={"synchronize_session": False},
    )
    db.session.refresh(payment, attribute_names=["verified"])
    if payment.verified:
        return payment
    db.session.expire(invoice, ["payments", "status"])
    if (
        invoice.status == "void"
        or not invoice.issued_at
        or payment.amount > invoice.balance
    ):
        raise ValueError(
            "The payment cannot be verified against the current invoice balance."
        )
    payment.verified = True
    payment.verified_at = utcnow()
    payment.verified_by = actor_id
    payment.evidence = str(evidence).strip()
    invoice.status = "paid" if invoice.balance == 0 else "partially_paid"
    if invoice.kind == "deposit" and invoice.balance == 0:
        _approval_task(
            invoice.project_id,
            f"invoice:{invoice.id}:deposit_verified",
            "Begin client onboarding after agreement verification",
            7,
        )
    log_activity(
        "payment_verified",
        f"Verified {invoice.currency} {payment.amount:.2f} for {invoice.reference}",
        client_id=invoice.client_id,
        project_id=invoice.project_id,
    )
    audit(
        "verify",
        "Payment",
        payment.id,
        "Administrator verified independent payment evidence.",
    )
    _event("payment.verified", invoice.project, f"payment:{payment.id}:verified:event")
    return payment


def project_balance(project_or_id):
    project_id = getattr(project_or_id, "id", project_or_id)
    return sum(
        (
            i.balance
            for i in Invoice.query.filter(
                Invoice.project_id == project_id,
                Invoice.issued_at.isnot(None),
                Invoice.status != "void",
            ).all()
        ),
        Decimal("0.00"),
    )


def payment_conditions_met(project_or_id):
    project_id = getattr(project_or_id, "id", project_or_id)
    executed = Contract.query.filter_by(
        project_id=project_id, status="executed"
    ).first()
    deposits = Invoice.query.filter(
        Invoice.project_id == project_id,
        Invoice.kind == "deposit",
        Invoice.issued_at.isnot(None),
        Invoice.status != "void",
    ).all()
    return bool(executed and deposits and all(i.balance == 0 for i in deposits))


def create_payment_schedule(contract, percentages, due_dates=None):
    if contract.status != "executed":
        raise ValueError("Execute the contract before generating a payment schedule.")
    if not isinstance(percentages, (list, tuple)) or not 1 <= len(percentages) <= 12:
        raise ValueError(
            "A payment schedule needs between one and twelve installments."
        )
    percentages = [
        number(p, "Installment percentage", Decimal("0.01"), Decimal("100"))
        for p in percentages
    ]
    if sum(percentages) != Decimal("100"):
        raise ValueError("Installment percentages must add up to 100.")
    if Invoice.query.filter(
        Invoice.schedule_key.like(f"contract:{contract.id}:%")
    ).first():
        raise ValueError("This contract already has a payment schedule.")
    if due_dates and len(due_dates) != len(percentages):
        raise ValueError("Provide one due date per installment.")
    invoices, allocated = [], Decimal("0.00")
    for idx, percentage in enumerate(percentages):
        amount = (
            contract.total - allocated
            if idx == len(percentages) - 1
            else currency_amount(contract.total * percentage / 100)
        )
        allocated += amount
        kind = (
            "deposit"
            if idx == 0
            else ("final" if idx == len(percentages) - 1 else "milestone")
        )
        invoice = create_invoice(
            contract.project,
            [
                dict(
                    description=f"{percentage}% — {contract.reference} installment {idx + 1}",
                    quantity=1,
                    unit_price=amount,
                )
            ],
            kind=kind,
            due_at=due_dates[idx]
            if due_dates
            else utcnow().date() + timedelta(days=14 + idx * 30),
            contract_id=contract.id,
            schedule_key=f"contract:{contract.id}:{idx + 1}",
        )
        invoices.append(invoice)
    return invoices


def final_payment_conditions_met(project_or_id):
    """All work must be paid, including a supported 100% upfront schedule."""
    project_id = getattr(project_or_id, "id", project_or_id)
    contract = (
        Contract.query.filter_by(project_id=project_id, status="executed")
        .order_by(Contract.id.desc())
        .first()
    )
    if not contract:
        return False
    invoices = Invoice.query.filter(
        Invoice.project_id == project_id,
        Invoice.status != "void",
        Invoice.kind != "maintenance",
    ).all()
    if not invoices or any(i.issued_at is None or i.balance != 0 for i in invoices):
        return False
    paid = sum((i.paid for i in invoices), Decimal("0.00"))
    if paid < contract.total:
        return False
    return any(i.kind == "final" for i in invoices) or any(
        i.kind == "deposit"
        and i.contract_id == contract.id
        and i.paid >= contract.total
        for i in invoices
    )
