"""Commercial documents keep frozen monetary snapshots after issuance."""

from decimal import Decimal

from sqlalchemy import event, inspect, select

from app.extensions import db
from app.models.base import BaseModel, utcnow


class Proposal(BaseModel):
    __tablename__ = "proposals"
    reference = db.Column(db.String(40), unique=True, nullable=False)
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    previous_id = db.Column(db.Integer, db.ForeignKey("proposals.id"))
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    currency = db.Column(db.String(3), nullable=False, default="PHP")
    overview = db.Column(db.Text, default="")
    deliverables = db.Column(db.Text, default="")
    exclusions = db.Column(db.Text, default="")
    timeline = db.Column(db.Text, default="")
    terms = db.Column(db.Text, default="")
    expires_at = db.Column(db.Date)
    contingency = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    discount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    recurring_total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    sent_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)
    acceptance_person = db.Column(db.String(200))
    acceptance_evidence = db.Column(db.Text)
    accepted_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    project = db.relationship("Project", foreign_keys=[project_id])
    items = db.relationship(
        "ProposalItem",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalItem.id",
    )


class ProposalItem(BaseModel):
    __tablename__ = "proposal_items"
    proposal_id = db.Column(
        db.Integer, db.ForeignKey("proposals.id"), nullable=False, index=True
    )
    description = db.Column(db.String(500), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="fixed")
    quantity = db.Column(db.Numeric(12, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    proposal = db.relationship("Proposal", back_populates="items")


class Contract(BaseModel):
    __tablename__ = "contracts"
    reference = db.Column(db.String(40), unique=True, nullable=False)
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposals.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    previous_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    body = db.Column(db.Text, nullable=False)
    total = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="PHP")
    executed_at = db.Column(db.DateTime)
    signed_by = db.Column(db.String(200))
    evidence = db.Column(db.Text)
    confirmed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    project = db.relationship("Project", foreign_keys=[project_id])
    proposal = db.relationship("Proposal", foreign_keys=[proposal_id])


class Invoice(BaseModel):
    __tablename__ = "invoices"
    reference = db.Column(db.String(40), unique=True, nullable=False)
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    client_id = db.Column(
        db.Integer, db.ForeignKey("client.id"), nullable=False, index=True
    )
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    kind = db.Column(db.String(30), nullable=False, default="milestone")
    currency = db.Column(db.String(3), nullable=False, default="PHP")
    issued_at = db.Column(db.DateTime)
    due_at = db.Column(db.Date, index=True)
    client_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    project_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    subtotal = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    discount = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    tax_rate = db.Column(db.Numeric(7, 4), nullable=False, default=0)
    tax = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    instructions = db.Column(db.Text, default="")
    void_reason = db.Column(db.Text)
    schedule_key = db.Column(db.String(100), unique=True)
    project = db.relationship("Project", foreign_keys=[project_id])
    client = db.relationship("Client", foreign_keys=[client_id])
    items = db.relationship(
        "InvoiceItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.id",
    )
    payments = db.relationship(
        "Payment", back_populates="invoice", order_by="Payment.id"
    )

    @property
    def paid(self):
        return sum((p.amount for p in self.payments if p.verified), Decimal("0.00"))

    @property
    def amount_paid(self):
        return self.paid

    @property
    def balance(self):
        return self.total - self.paid

    @property
    def overdue(self):
        return bool(
            self.issued_at
            and self.status != "void"
            and self.due_at
            and self.due_at < utcnow().date()
            and self.balance > 0
        )


class InvoiceItem(BaseModel):
    __tablename__ = "invoice_items"
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True
    )
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Numeric(12, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    invoice = db.relationship("Invoice", back_populates="items")


class Payment(BaseModel):
    __tablename__ = "payments"
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True
    )
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    method = db.Column(db.String(100), nullable=False)
    reference = db.Column(db.String(100), nullable=False, unique=True)
    received_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    verified = db.Column(db.Boolean, nullable=False, default=False, index=True)
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    evidence = db.Column(db.Text)
    invoice = db.relationship("Invoice", back_populates="payments")

    @property
    def project_id(self):
        return self.invoice.project_id


class Expense(BaseModel):
    __tablename__ = "expenses"
    project_id = db.Column(
        db.Integer, db.ForeignKey("project.id"), nullable=False, index=True
    )
    description = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(100), nullable=False, default="General")
    amount = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="PHP")
    incurred_at = db.Column(db.Date, nullable=False, default=lambda: utcnow().date())
    recurring = db.Column(db.Boolean, nullable=False, default=False)
    receipt_reference = db.Column(db.String(500))
    project = db.relationship("Project", foreign_keys=[project_id])


def _was_set(target, field, connection):
    # Read the stored value: an expired ORM attribute may have no deleted history
    # when it is overwritten, so attribute history alone cannot guard snapshots.
    if inspect(target).identity:
        table = target.__table__
        return bool(
            connection.scalar(select(table.c[field]).where(table.c.id == target.id))
        )
    state = inspect(target).attrs[field]
    old = state.history.deleted
    if state.history.has_changes():
        return bool(old[0]) if old else False
    return bool(state.value)


@event.listens_for(Invoice, "before_update")
def _protect_invoice(mapper, connection, target):
    if _was_set(target, "issued_at", connection):
        allowed = {"status", "void_reason", "updated_at", "payments"}
        if any(
            a.history.has_changes()
            for a in inspect(target).attrs
            if a.key not in allowed
        ):
            raise ValueError(
                "Issued invoice snapshots cannot be modified; create a correction invoice."
            )


@event.listens_for(Contract, "before_update")
def _protect_contract(mapper, connection, target):
    if _was_set(target, "executed_at", connection) and any(
        a.history.has_changes()
        for a in inspect(target).attrs
        if a.key in inspect(target).mapper.column_attrs and a.key != "updated_at"
    ):
        raise ValueError("Executed contracts are immutable; create a new version.")


@event.listens_for(Payment, "before_update")
def _protect_payment(mapper, connection, target):
    if _was_set(target, "verified", connection) and any(
        a.history.has_changes()
        for a in inspect(target).attrs
        if a.key in inspect(target).mapper.column_attrs and a.key != "updated_at"
    ):
        raise ValueError("Verified payments cannot be altered.")


@event.listens_for(Proposal, "before_update")
def _protect_proposal(mapper, connection, target):
    status = connection.scalar(
        select(Proposal.__table__.c.status).where(Proposal.__table__.c.id == target.id)
    )
    if status != "draft":
        allowed = {
            "status",
            "sent_at",
            "accepted_at",
            "acceptance_person",
            "acceptance_evidence",
            "accepted_by",
            "updated_at",
        }
        if status == "accepted" or _was_set(target, "accepted_at", connection):
            allowed = {"updated_at"}
        if any(
            a.history.has_changes()
            for a in inspect(target).attrs
            if a.key in inspect(target).mapper.column_attrs and a.key not in allowed
        ):
            raise ValueError("Approved proposals are frozen; create a revised version.")


def _protect_item(mapper, connection, target):
    invoice_item = isinstance(target, InvoiceItem)
    parent_model = Invoice if invoice_item else Proposal
    foreign_key = "invoice_id" if invoice_item else "proposal_id"
    parent = target.invoice if invoice_item else target.proposal
    parent_ids = {getattr(target, foreign_key), parent.id if parent else None}
    if inspect(target).identity:
        parent_ids.add(
            connection.scalar(
                select(target.__table__.c[foreign_key]).where(
                    target.__table__.c.id == target.id
                )
            )
        )
    for parent_id in parent_ids - {None}:
        table = parent_model.__table__
        stored = connection.scalar(
            select(table.c.issued_at if invoice_item else table.c.status).where(
                table.c.id == parent_id
            )
        )
        if bool(stored) if invoice_item else stored not in (None, "draft"):
            raise ValueError("Finalized document line items cannot be modified.")


for _model in (InvoiceItem, ProposalItem):
    event.listen(_model, "before_insert", _protect_item)
    event.listen(_model, "before_update", _protect_item)
    event.listen(_model, "before_delete", _protect_item)


def _protect_delete(mapper, connection, target):
    frozen = (
        isinstance(target, Invoice)
        and _was_set(target, "issued_at", connection)
        or isinstance(target, Contract)
        and _was_set(target, "executed_at", connection)
        or isinstance(target, Payment)
        and _was_set(target, "verified", connection)
        or isinstance(target, Proposal)
        and connection.scalar(
            select(Proposal.__table__.c.status).where(
                Proposal.__table__.c.id == target.id
            )
        )
        != "draft"
    )
    if frozen:
        raise ValueError("Finalized financial records cannot be deleted.")


for _model in (Invoice, Contract, Payment, Proposal):
    event.listen(_model, "before_delete", _protect_delete)
