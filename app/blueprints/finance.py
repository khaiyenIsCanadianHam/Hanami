"""Administrator commercial workflows with HTML and JSON mutations."""

from datetime import date
from types import SimpleNamespace

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.core import Approval, Project, ScopeItem
from app.models.finance import Contract, Expense, Invoice, Payment, Proposal
from app.services.common import admin_required, audit, log_activity
from app.services.invoice_service import (
    accept_proposal,
    calculate_proposal,
    create_contract,
    create_invoice,
    calculate_totals,
    create_payment_schedule,
    currency_amount,
    execute_contract,
    issue_invoice,
    record_payment,
    reference,
    revise_proposal,
    verify_payment,
)

bp = Blueprint("finance", __name__)


@bp.before_request
@admin_required
def require_administrator():
    pass


@bp.errorhandler(ValueError)
def validation_error(error):
    db.session.rollback()
    if request.is_json:
        return jsonify(error=str(error)), 400
    return render_template("finance/error.html", message=str(error)), 400


@bp.errorhandler(IntegrityError)
def integrity_error(error):
    db.session.rollback()
    message = "This record conflicts with an existing reference or a related record. Please check the values."
    if request.is_json:
        return jsonify(error=message), 400
    return render_template("finance/error.html", message=message), 400


def data():
    payload = request.get_json() if request.is_json else request.form
    if not hasattr(payload, "get"):
        raise ValueError("Supply an object containing the form fields.")
    return payload


def required(payload, key, limit=20000):
    value = str(payload.get(key, "")).strip()
    if not value or len(value) > limit:
        raise ValueError(
            f"{key.replace('_', ' ').capitalize()} is required (maximum {limit} characters)."
        )
    return value


def related(model, value, name):
    try:
        ident = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Select a valid {name}.") from None
    obj = db.session.get(model, ident)
    if obj is None:
        raise ValueError(f"The selected {name} does not exist.")
    return obj


def parsed_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("Dates must use YYYY-MM-DD.") from None


def line_items(payload):
    if "items" in payload:
        return payload["items"]
    result = []
    for line in str(payload.get("item_lines", "")).splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in (3, 4):
            raise ValueError(
                "Each item needs Description | Quantity | Unit price | Kind (optional)."
            )
        result.append(
            dict(
                description=parts[0],
                quantity=parts[1],
                unit_price=parts[2],
                kind=parts[3] if len(parts) == 4 else "fixed",
            )
        )
    return result


def done(obj, endpoint, message):
    db.session.commit()
    if request.is_json:
        return jsonify(
            ok=True,
            id=obj.id,
            status=getattr(obj, "status", None),
            url=url_for(endpoint, ident=obj.id),
        )
    flash(message, "success")
    return redirect(url_for(endpoint, ident=obj.id))


def field(name, label, type="text", **kwargs):
    return dict(name=name, label=label, type=type, **kwargs)


def project_field(selected=None):
    return field(
        "project_id",
        "Project",
        "select",
        required=True,
        value=selected,
        options=[
            (p.id, f"{p.reference} · {p.title}")
            for p in Project.query.order_by(Project.title).all()
        ],
    )


def proposal_fields(proposal=None):
    def val(key, default=""):
        return getattr(proposal, key, default) if proposal else default

    lines = (
        "\n".join(
            f"{i.description} | {i.quantity} | {i.unit_price} | {i.kind}"
            for i in proposal.items
        )
        if proposal
        else ""
    )
    fields = [
        project_field(val("project_id")),
        field("title", "Proposal title", required=True, value=val("title")),
        field(
            "overview",
            "Project overview and objectives",
            "textarea",
            value=val("overview"),
        ),
        field(
            "deliverables",
            "Deliverables and included features",
            "textarea",
            value=val("deliverables"),
        ),
        field(
            "exclusions",
            "Exclusions and assumptions",
            "textarea",
            value=val("exclusions"),
        ),
        field("timeline", "Timeline", "textarea", value=val("timeline")),
        field(
            "terms",
            "Payment schedule, revision policy and acceptance instructions",
            "textarea",
            value=val("terms"),
        ),
        field("expires_at", "Expires on", "date", value=val("expires_at")),
        field(
            "item_lines",
            "Pricing items",
            "textarea",
            value=lines,
            rows=7,
            help="One item per line: Description | Quantity or hours | Unit price | Kind. Kinds: labor, fixed, expense, recurring. Leave empty to copy the project scope.",
        ),
        field(
            "contingency",
            "Contingency amount",
            "number",
            value=val("contingency", 0),
            min=0,
        ),
        field("discount", "Discount amount", "number", value=val("discount", 0), min=0),
        field(
            "tax_rate",
            "Tax rate (%) on subtotal + contingency − discount",
            "number",
            value=val("tax_rate", 0),
            min=0,
        ),
    ]
    return fields


@bp.get("/proposals")
def proposals():
    rows = Proposal.query.order_by(Proposal.created_at.desc()).all()
    return render_template(
        "list.html",
        title="Proposals",
        subtitle="Scope, pricing and recorded client decisions.",
        rows=rows,
        columns=[
            ("reference", "Reference"),
            ("title", "Proposal"),
            ("version", "Version"),
            ("total", "One-time total"),
            ("currency", "Currency"),
            ("status", "Status"),
        ],
        new_url=url_for("finance.proposal_new"),
        detail_url=lambda r: url_for("finance.proposal_detail", ident=r.id),
    )


@bp.route("/proposals/new", methods=["GET", "POST"])
def proposal_new():
    if request.method == "POST":
        payload = data()
        project = related(Project, payload.get("project_id"), "project")
        proposal = Proposal(
            reference=reference("PROP"),
            project_id=project.id,
            title=required(payload, "title", 200),
            status="draft",
            currency=project.currency,
            version=1,
        )
        _fill_proposal(proposal, payload)
        db.session.add(proposal)
        db.session.flush()
        audit("create", "Proposal", proposal.id)
        return done(proposal, "finance.proposal_detail", "Proposal draft created.")
    return render_template(
        "form.html",
        title="New proposal",
        fields=proposal_fields(),
        cancel_url="/proposals",
    )


def _fill_proposal(proposal, payload):
    for key in ("overview", "deliverables", "exclusions", "timeline", "terms"):
        setattr(proposal, key, str(payload.get(key, ""))[:20000])
    proposal.title = required(payload, "title", 200)
    proposal.expires_at = parsed_date(payload.get("expires_at"))
    proposal.contingency = payload.get("contingency", 0)
    proposal.discount = payload.get("discount", 0)
    proposal.tax_rate = payload.get("tax_rate", 0)
    items = line_items(payload)
    if not items:
        scope = ScopeItem.query.filter_by(
            project_id=proposal.project_id, included=True
        ).all()
        items = [
            dict(description=s.name, quantity=s.hours, unit_price=s.rate, kind="labor")
            for s in scope
            if s.hours > 0
        ]
    calculate_proposal(proposal, items)


@bp.get("/proposals/<int:ident>")
def proposal_detail(ident):
    proposal = db.get_or_404(Proposal, ident)
    versions = (
        Proposal.query.filter_by(project_id=proposal.project_id)
        .order_by(Proposal.created_at.desc())
        .all()
    )
    return render_template(
        "finance/proposal.html", proposal=proposal, versions=versions
    )


@bp.route("/proposals/<int:ident>/edit", methods=["GET", "POST"])
def proposal_edit(ident):
    proposal = db.get_or_404(Proposal, ident)
    if proposal.status != "draft":
        raise ValueError("Create a revised version to change this proposal.")
    if request.method == "POST":
        _fill_proposal(proposal, data())
        audit("edit", "Proposal", proposal.id)
        return done(proposal, "finance.proposal_detail", "Draft updated.")
    return render_template(
        "form.html",
        title="Edit proposal",
        fields=proposal_fields(proposal)[1:],
        cancel_url=url_for("finance.proposal_detail", ident=ident),
    )


@bp.post("/proposals/<int:ident>/approve")
def proposal_approve(ident):
    proposal = db.get_or_404(Proposal, ident)
    if proposal.status != "draft":
        raise ValueError("Only draft proposals may be approved.")
    if not Approval.query.filter_by(
        project_id=proposal.project_id,
        stage_number=4,
        kind="scope",
        decision="approved",
    ).first():
        raise ValueError("Record project scope approval before approving the proposal.")
    calculate_proposal(proposal)
    db.session.flush()
    proposal.status = "approved"
    audit("approve", "Proposal", ident)
    return done(
        proposal,
        "finance.proposal_detail",
        "Proposal approved. Client acceptance is still required.",
    )


@bp.post("/proposals/<int:ident>/sent")
def proposal_sent(ident):
    from app.models.base import utcnow

    proposal = db.get_or_404(Proposal, ident)
    if proposal.status != "approved":
        raise ValueError("Approve the proposal before marking it sent.")
    proposal.status, proposal.sent_at = "sent", utcnow()
    audit("sent", "Proposal", ident, "Administrator recorded proposal delivery.")
    return done(
        proposal,
        "finance.proposal_detail",
        "Delivery recorded. This does not record acceptance.",
    )


@bp.post("/proposals/<int:ident>/accept")
def proposal_accept(ident):
    proposal, payload = db.get_or_404(Proposal, ident), data()
    accept_proposal(
        proposal, payload.get("person"), payload.get("evidence"), current_user.id
    )
    return done(proposal, "finance.proposal_detail", "Client acceptance recorded.")


@bp.post("/proposals/<int:ident>/revise")
def proposal_revise(ident):
    proposal = revise_proposal(db.get_or_404(Proposal, ident))
    return done(
        proposal,
        "finance.proposal_detail",
        "New proposal version created; edit the new draft.",
    )


@bp.get("/contracts")
def contracts():
    return render_template(
        "list.html",
        title="Contracts",
        subtitle="Agreements require professional review and explicit execution evidence.",
        rows=Contract.query.order_by(Contract.created_at.desc()).all(),
        columns=[
            ("reference", "Reference"),
            ("version", "Version"),
            ("total", "Value"),
            ("currency", "Currency"),
            ("status", "Status"),
        ],
        new_url=url_for("finance.contract_new"),
        detail_url=lambda r: url_for("finance.contract_detail", ident=r.id),
    )


@bp.route("/contracts/new", methods=["GET", "POST"])
def contract_new():
    if request.method == "POST":
        payload = data()
        proposal = related(Proposal, payload.get("proposal_id"), "accepted proposal")
        contract = create_contract(proposal, payload.get("body") or None)
        return done(
            contract, "finance.contract_detail", "Contract draft created for review."
        )
    return render_template(
        "form.html",
        title="Generate contract draft",
        fields=[
            field(
                "proposal_id",
                "Accepted proposal",
                "select",
                required=True,
                value=request.args.get("proposal_id"),
                options=[
                    (p.id, f"{p.reference} · {p.title}")
                    for p in Proposal.query.filter_by(status="accepted").all()
                ],
            ),
            field(
                "body",
                "Agreement text (optional)",
                "textarea",
                help="Leave blank to generate a draft for professional review.",
            ),
        ],
        cancel_url="/contracts",
    )


@bp.get("/contracts/<int:ident>")
def contract_detail(ident):
    return render_template(
        "finance/contract.html", contract=db.get_or_404(Contract, ident)
    )


@bp.route("/contracts/<int:ident>/edit", methods=["GET", "POST"])
def contract_edit(ident):
    contract = db.get_or_404(Contract, ident)
    if contract.status != "draft":
        raise ValueError(
            "Executed agreements are immutable. Create an amendment version."
        )
    if request.method == "POST":
        contract.body = required(data(), "body")
        audit("edit", "Contract", ident)
        return done(contract, "finance.contract_detail", "Draft contract updated.")
    return render_template(
        "form.html",
        title="Edit contract draft",
        fields=[
            field(
                "body",
                "Agreement text",
                "textarea",
                required=True,
                value=contract.body,
                rows=20,
            )
        ],
        cancel_url=url_for("finance.contract_detail", ident=ident),
    )


@bp.post("/contracts/<int:ident>/revise")
def contract_revise(ident):
    original = db.get_or_404(Contract, ident)
    contract = create_contract(original.proposal, original.body)
    contract.previous_id, contract.version = original.id, original.version + 1
    audit(
        "revise", "Contract", contract.id, f"Amendment draft of contract {original.id}"
    )
    return done(
        contract,
        "finance.contract_detail",
        "Amendment draft created. The original remains preserved.",
    )


@bp.post("/contracts/<int:ident>/execute")
def contract_execute(ident):
    payload, contract = data(), db.get_or_404(Contract, ident)
    execute_contract(
        contract, payload.get("person"), payload.get("evidence"), current_user.id
    )
    return done(
        contract, "finance.contract_detail", "Executed agreement recorded and frozen."
    )


@bp.post("/contracts/<int:ident>/schedule")
def contract_schedule(ident):
    payload, contract = data(), db.get_or_404(Contract, ident)
    percentages = payload.get("percentages", "40,30,30")
    if isinstance(percentages, str):
        percentages = [part.strip() for part in percentages.split(",")]
    invoices = create_payment_schedule(contract, percentages, payload.get("due_dates"))
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, invoice_ids=[i.id for i in invoices])
    flash(
        "Payment schedule created as invoice drafts. Review and issue each installment.",
        "success",
    )
    return redirect(url_for("finance.invoices"))


@bp.get("/invoices")
def invoices():
    rows = Invoice.query.order_by(Invoice.created_at.desc()).all()
    return render_template(
        "list.html",
        title="Invoices",
        subtitle="Issued snapshots and verified receivables.",
        rows=rows,
        columns=[
            ("reference", "Invoice"),
            ("kind", "Type"),
            ("total", "Total"),
            ("currency", "Currency"),
            ("paid", "Verified paid"),
            ("balance", "Balance"),
            ("due_at", "Due"),
            ("status", "Status"),
        ],
        new_url=url_for("finance.invoice_new"),
        detail_url=lambda r: url_for("finance.invoice_detail", ident=r.id),
    )


@bp.route("/invoices/new", methods=["GET", "POST"])
def invoice_new():
    if request.method == "POST":
        payload = data()
        project = related(Project, payload.get("project_id"), "project")
        invoice = create_invoice(
            project,
            line_items(payload),
            kind=payload.get("kind", "milestone"),
            due_at=parsed_date(payload.get("due_at")),
            discount=payload.get("discount", 0),
            tax_rate=payload.get("tax_rate", 0),
            instructions=payload.get("instructions", ""),
            contract_id=payload.get("contract_id") or None,
        )
        return done(invoice, "finance.invoice_detail", "Invoice draft created.")
    return render_template(
        "form.html",
        title="New invoice",
        fields=[
            project_field(request.args.get("project_id")),
            field(
                "kind",
                "Invoice type",
                "select",
                required=True,
                options=[
                    (i, i.title())
                    for i in (
                        "deposit",
                        "milestone",
                        "final",
                        "maintenance",
                        "adjustment",
                    )
                ],
            ),
            field("due_at", "Due date", "date"),
            field(
                "item_lines",
                "Line items",
                "textarea",
                required=True,
                help="One per line: Description | Quantity | Unit price",
            ),
            field("discount", "Discount amount", "number", value=0, min=0),
            field("tax_rate", "Tax rate (%) after discount", "number", value=0, min=0),
            field("instructions", "Payment instructions", "textarea"),
        ],
        cancel_url="/invoices",
    )


@bp.get("/invoices/<int:ident>")
def invoice_detail(ident):
    return render_template(
        "finance/invoice.html", invoice=db.get_or_404(Invoice, ident)
    )


@bp.route("/invoices/<int:ident>/edit", methods=["GET", "POST"])
def invoice_edit(ident):
    from app.models.finance import InvoiceItem

    invoice = db.get_or_404(Invoice, ident)
    if invoice.status != "draft" or invoice.issued_at:
        raise ValueError(
            "Only invoice drafts can be edited. Preserve issued records and create a correction invoice."
        )
    if request.method == "POST":
        payload = data()
        totals = calculate_totals(
            line_items(payload),
            discount=payload.get("discount", 0),
            tax_rate=payload.get("tax_rate", 0),
        )
        if totals["total"] <= 0 or any(
            i["kind"] == "recurring" for i in totals["items"]
        ):
            raise ValueError(
                "Invoice line items must total a positive amount currently due."
            )
        invoice.items = [
            InvoiceItem(**{k: v for k, v in item.items() if k != "kind"})
            for item in totals["items"]
        ]
        for key in ("discount", "tax_rate", "subtotal", "tax", "total"):
            setattr(invoice, key, totals[key])
        invoice.due_at = parsed_date(payload.get("due_at"))
        invoice.instructions = str(payload.get("instructions", ""))[:20000]
        audit("edit", "Invoice", ident, "Draft updated before issuance.")
        return done(invoice, "finance.invoice_detail", "Invoice draft updated.")
    return render_template(
        "form.html",
        title=f"Edit invoice draft {invoice.reference}",
        fields=[
            field("due_at", "Due date", "date", value=invoice.due_at),
            field(
                "item_lines",
                "Line items",
                "textarea",
                required=True,
                value="\n".join(
                    f"{i.description} | {i.quantity} | {i.unit_price}"
                    for i in invoice.items
                ),
                help="One per line: Description | Quantity | Unit price",
            ),
            field(
                "discount", "Discount amount", "number", value=invoice.discount, min=0
            ),
            field(
                "tax_rate",
                "Tax rate (%) after discount",
                "number",
                value=invoice.tax_rate,
                min=0,
            ),
            field(
                "instructions",
                "Payment instructions",
                "textarea",
                value=invoice.instructions,
            ),
        ],
        cancel_url=url_for("finance.invoice_detail", ident=ident),
    )


@bp.post("/invoices/<int:ident>/issue")
def invoice_issue(ident):
    invoice = issue_invoice(db.get_or_404(Invoice, ident))
    return done(
        invoice,
        "finance.invoice_detail",
        "Invoice issued and its financial snapshot frozen.",
    )


@bp.post("/invoices/<int:ident>/void")
def invoice_void(ident):
    invoice = db.get_or_404(Invoice, ident)
    if invoice.paid > 0:
        raise ValueError("An invoice with verified payments cannot be voided.")
    invoice.void_reason = required(data(), "reason", 2000)
    invoice.status = "void"
    audit("void", "Invoice", ident, invoice.void_reason)
    return done(
        invoice,
        "finance.invoice_detail",
        "Invoice voided. Original amounts remain preserved.",
    )


@bp.get("/payments")
def payments():
    return render_template(
        "list.html",
        title="Payments",
        subtitle="Reported transactions count as collected only after verification.",
        rows=Payment.query.order_by(Payment.received_at.desc()).all(),
        columns=[
            ("reference", "Transaction"),
            ("amount", "Amount"),
            ("method", "Method"),
            ("received_at", "Received"),
            ("verified", "Verified"),
        ],
        new_url=url_for("finance.payment_new"),
        detail_url=lambda r: url_for("finance.payment_detail", ident=r.id),
    )


@bp.route("/payments/new", methods=["GET", "POST"])
def payment_new():
    if request.method == "POST":
        payload = data()
        invoice = related(Invoice, payload.get("invoice_id"), "invoice")
        payment = record_payment(
            invoice,
            payload.get("amount"),
            payload.get("method"),
            payload.get("reference"),
        )
        return done(
            payment,
            "finance.payment_detail",
            "Payment recorded. Verify it against independent evidence to update the balance.",
        )
    candidates = [
        i
        for i in Invoice.query.filter(
            Invoice.issued_at.isnot(None), Invoice.status != "void"
        ).all()
        if i.balance > 0
    ]
    return render_template(
        "form.html",
        title="Record reported payment",
        fields=[
            field(
                "invoice_id",
                "Invoice",
                "select",
                required=True,
                value=request.args.get("invoice_id"),
                options=[
                    (i.id, f"{i.reference} · {i.currency} {i.balance:.2f} outstanding")
                    for i in candidates
                ],
            ),
            field("amount", "Amount", "number", required=True, min="0.01"),
            field("method", "Payment method", required=True),
            field("reference", "Unique bank or transaction reference", required=True),
        ],
        cancel_url="/payments",
    )


@bp.get("/payments/<int:ident>")
def payment_detail(ident):
    return render_template(
        "finance/payment.html", payment=db.get_or_404(Payment, ident)
    )


@bp.post("/payments/<int:ident>/verify")
def payment_verify(ident):
    payment = verify_payment(
        db.get_or_404(Payment, ident), data().get("evidence"), current_user.id
    )
    return done(
        payment,
        "finance.payment_detail",
        "Payment independently verified; invoice balance updated.",
    )


@bp.get("/expenses")
def expenses():
    return render_template(
        "list.html",
        title="Expenses",
        subtitle="Project costs and recurring commitments.",
        rows=Expense.query.order_by(Expense.incurred_at.desc()).all(),
        columns=[
            ("description", "Expense"),
            ("category", "Category"),
            ("amount", "Amount"),
            ("currency", "Currency"),
            ("incurred_at", "Date"),
            ("recurring", "Recurring"),
        ],
        new_url=url_for("finance.expense_new"),
        detail_url=lambda r: url_for("finance.expense_detail", ident=r.id),
    )


@bp.route("/expenses/new", methods=["GET", "POST"])
def expense_new():
    if request.method == "POST":
        payload = data()
        project = related(Project, payload.get("project_id"), "project")
        amount = currency_amount(payload.get("amount"))
        if amount <= 0:
            raise ValueError("Expense amount must be positive.")
        expense = Expense(
            project_id=project.id,
            description=required(payload, "description", 500),
            category=required(payload, "category", 100),
            amount=amount,
            currency=project.currency,
            incurred_at=parsed_date(payload.get("incurred_at")) or date.today(),
            recurring=payload.get("recurring") in (True, "1", "true", "on"),
            receipt_reference=str(payload.get("receipt_reference", ""))[:500],
        )
        db.session.add(expense)
        db.session.flush()
        audit("create", "Expense", expense.id)
        log_activity("expense_recorded", expense.description, project_id=project.id)
        return done(expense, "finance.expense_detail", "Expense recorded.")
    return render_template(
        "form.html",
        title="Record project expense",
        fields=[
            project_field(),
            field("description", "Description", required=True),
            field("category", "Category", required=True, value="General"),
            field("amount", "Amount", "number", required=True, min="0.01"),
            field("incurred_at", "Incurred on", "date", value=date.today()),
            field("receipt_reference", "Receipt or document reference"),
            field("recurring", "Recurring expense", "checkbox"),
        ],
        cancel_url="/expenses",
    )


@bp.get("/expenses/<int:ident>")
def expense_detail(ident):
    expense = db.get_or_404(Expense, ident)
    return render_template(
        "detail.html",
        title=expense.description,
        record=expense,
        sections=[
            dict(
                title="Expense details",
                fields=[
                    ("Project", expense.project.title),
                    ("Amount", f"{expense.currency} {expense.amount:.2f}"),
                    ("Category", expense.category),
                    ("Incurred", expense.incurred_at),
                    ("Recurring", "Yes" if expense.recurring else "No"),
                    ("Receipt reference", expense.receipt_reference),
                ],
            )
        ],
    )


@bp.get("/<kind>/<int:ident>/pdf")
def financial_pdf(kind, ident):
    models = {"proposals": Proposal, "contracts": Contract, "invoices": Invoice}
    if kind not in models:
        abort(404)
    record = db.get_or_404(models[kind], ident)
    from app.services.document_service import export_pdf

    document = SimpleNamespace(
        title=f"{kind[:-1].title()} {record.reference}",
        status=record.status,
        version=getattr(record, "version", 1),
        body=render_template("finance/export.txt", record=record, kind=kind),
    )
    return send_file(
        export_pdf(document),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{record.reference}.pdf",
    )
