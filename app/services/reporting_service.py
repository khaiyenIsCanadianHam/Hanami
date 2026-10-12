"""Operational reports: Decimal totals, explicit currencies, verified receipts only."""

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy.orm import joinedload, selectinload
from app.extensions import db
from app.models import (
    Client,
    Lead,
    Project,
    Proposal,
    Contract,
    Invoice,
    Payment,
    Expense,
)
from app.models.delivery import MaintenanceAgreement
from app.services.common import setting

ZERO = Decimal("0.00")
CURRENCIES = ("PHP", "USD", "EUR", "GBP", "CAD", "AUD", "SGD", "JPY")


def business_timezone():
    return ZoneInfo(
        setting(
            "business_timezone",
            current_app.config.get("BUSINESS_TIMEZONE", "Asia/Manila"),
        )
    )


def local_date(value):
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(business_timezone()).date()
    return value


def today():
    return datetime.now(business_timezone()).date()


def month_start(value, offset=0):
    ordinal = value.year * 12 + value.month - 1 + offset
    return date(ordinal // 12, ordinal % 12 + 1, 1)


def date_range(args):
    """Inclusive business-local dates; no date filters silently discarded."""
    end = date.fromisoformat(args.get("end") or today().isoformat())
    start = date.fromisoformat(args.get("start") or month_start(end, -5).isoformat())
    if start > end:
        raise ValueError("Start date must be on or before the end date.")
    if (end - start).days > 3660:
        raise ValueError("Choose a reporting period of ten years or less.")
    return start, end


def in_period(value, start, end):
    return value is not None and start <= local_date(value) <= end


def _totals_by(items, label):
    totals = defaultdict(lambda: ZERO)
    for item in items:
        totals[label(item)] += item.amount
    return sorted(totals.items(), key=lambda pair: pair[1], reverse=True)


def financial_report(start, end, currency="PHP"):
    """Money never crosses currencies. Draft/void invoices and unverified funds excluded.

    Current receivables refer to invoices issued in the selected period, reduced by
    all verified receipts to date. This is an operational report, not a tax report.
    """
    proposals = db.session.scalars(
        db.select(Proposal).where(
            Proposal.currency == currency,
            Proposal.status.notin_(["rejected", "superseded", "expired"]),
        )
    ).all()
    revised_proposal_ids = {p.previous_id for p in proposals if p.previous_id}
    proposals = [
        p
        for p in proposals
        if p.id not in revised_proposal_ids and in_period(p.created_at, start, end)
    ]
    contracts = db.session.scalars(
        db.select(Contract).where(
            Contract.currency == currency, Contract.executed_at.is_not(None)
        )
    ).all()
    replaced_contracts = {c.previous_id for c in contracts if c.previous_id}
    contracts = [
        c
        for c in contracts
        if c.id not in replaced_contracts and in_period(c.executed_at, start, end)
    ]
    invoices = db.session.scalars(
        db.select(Invoice)
        .where(
            Invoice.currency == currency,
            Invoice.issued_at.is_not(None),
            Invoice.status != "void",
        )
        .options(selectinload(Invoice.payments))
    ).all()
    invoices = [i for i in invoices if in_period(i.issued_at, start, end)]
    payments = db.session.scalars(
        db.select(Payment)
        .join(Invoice)
        .where(
            Payment.verified.is_(True),
            Invoice.currency == currency,
            Invoice.status != "void",
        )
        .options(
            joinedload(Payment.invoice).joinedload(Invoice.client),
            joinedload(Payment.invoice)
            .joinedload(Invoice.project)
            .joinedload(Project.client)
            .joinedload(Client.lead),
        )
    ).all()
    payments = [p for p in payments if in_period(p.received_at, start, end)]
    expenses = db.session.scalars(
        db.select(Expense).where(
            Expense.currency == currency,
            Expense.incurred_at >= start,
            Expense.incurred_at <= end,
        )
    ).all()
    agreements = db.session.scalars(
        db.select(MaintenanceAgreement).where(
            MaintenanceAgreement.currency == currency,
            MaintenanceAgreement.status == "active",
        )
    ).all()
    # The schema names the recurring amount monthly_fee; annual invoices multiply it
    # by twelve. Show current contracted MRR separately from collected maintenance.
    mrr = sum((a.monthly_fee for a in agreements), ZERO)
    months = []
    cursor = month_start(start)
    while cursor <= end:
        months.append(
            {
                "key": cursor.strftime("%Y-%m"),
                "label": cursor.strftime("%b %y"),
                "receipts": ZERO,
                "expenses": ZERO,
                "overdue": ZERO,
            }
        )
        cursor = month_start(cursor, 1)
    month_map = {m["key"]: m for m in months}
    for payment in payments:
        month_map[local_date(payment.received_at).strftime("%Y-%m")]["receipts"] += (
            payment.amount
        )
    for expense in expenses:
        month_map[expense.incurred_at.strftime("%Y-%m")]["expenses"] += expense.amount
    overdue = [
        i for i in invoices if i.due_at and i.due_at < today() and i.balance > ZERO
    ]
    for invoice in overdue:
        key = invoice.due_at.strftime("%Y-%m")
        if key in month_map:
            month_map[key]["overdue"] += invoice.balance
    receipts = sum((p.amount for p in payments), ZERO)
    spent = sum((e.amount for e in expenses), ZERO)
    return {
        "currency": currency,
        "start": start,
        "end": end,
        "proposed": sum((p.total for p in proposals), ZERO),
        "contracted": sum((c.total for c in contracts), ZERO),
        "invoiced": sum((i.total for i in invoices), ZERO),
        "receipts": receipts,
        "expenses": spent,
        "cash_net": receipts - spent,
        "outstanding": sum((max(i.balance, ZERO) for i in invoices), ZERO),
        "overdue": sum((i.balance for i in overdue), ZERO),
        "overdue_count": len(overdue),
        "paid_count": sum(i.balance <= ZERO for i in invoices),
        "unpaid_count": sum(i.balance > ZERO for i in invoices),
        "maintenance_receipts": sum(
            (p.amount for p in payments if p.invoice.kind == "maintenance"), ZERO
        ),
        "maintenance_mrr": mrr,
        "monthly": months,
        "by_client": _totals_by(
            payments, lambda p: p.invoice.client.business_name or p.invoice.client.name
        ),
        "by_project": _totals_by(payments, lambda p: p.invoice.project.title),
        "by_service": _totals_by(
            payments,
            lambda p: p.invoice.project.client.lead.service
            if p.invoice.project.client.lead
            else "Website development",
        ),
        "invoices": invoices,
        "payments": payments,
    }


def project_report(start, end):
    leads = [
        lead
        for lead in db.session.scalars(db.select(Lead)).all()
        if in_period(lead.created_at, start, end)
    ]
    projects = [
        project
        for project in db.session.scalars(
            db.select(Project).options(selectinload(Project.stages))
        ).all()
        if in_period(project.created_at, start, end)
    ]
    converted = sum(lead.status == "converted" for lead in leads)
    completed = [project for project in projects if project.status == "completed"]
    durations = []
    for project in completed:
        dates = [
            stage.completed_at
            for stage in project.stages
            if stage.number == 14 and stage.completed_at
        ]
        if dates:
            durations.append(
                max(0, (max(dates) - project.created_at).total_seconds() / 86400)
            )
    sources = defaultdict(int)
    stages = defaultdict(int)
    for lead in leads:
        sources[lead.source or "Unspecified"] += 1
    for project in projects:
        stages[project.current_stage] += 1
    return {
        "lead_count": len(leads),
        "converted": converted,
        "conversion_rate": round(converted / len(leads) * 100, 1) if leads else 0,
        "project_count": len(projects),
        "completed": len(completed),
        "completion_rate": round(len(completed) / len(projects) * 100, 1)
        if projects
        else 0,
        "average_days": round(sum(durations) / len(durations), 1)
        if durations
        else None,
        "sources": sorted(sources.items(), key=lambda pair: pair[1], reverse=True),
        "stages": sorted(stages.items()),
    }


def chart_data(report):
    """Decimal values become strings; JS converts only for drawing, never accounting."""
    return {
        "labels": [m["label"] for m in report["monthly"]],
        "receipts": [str(m["receipts"]) for m in report["monthly"]],
        "expenses": [str(m["expenses"]) for m in report["monthly"]],
        "currency": report["currency"],
    }
