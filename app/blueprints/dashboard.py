"""Authenticated overview, operational reports, calendar and workspace preferences."""

import calendar as calendar_module
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    ActivityLog,
    ApplicationSetting,
    Client,
    Lead,
    Project,
    ProjectMilestone,
    ProjectStage,
    Task,
    Notification,
    Inquiry,
    Proposal,
    Contract,
    Invoice,
    EmailDraft,
    Document,
)
from app.models.delivery import (
    Meeting,
    MaintenanceTask,
    MaintenanceAgreement,
    HandoverRecord,
    TrainingRecord,
    SupportTicket,
)
from app.models.base import utcnow
from app.services.common import admin_required, setting, audit, log_activity
from app.services.reporting_service import (
    CURRENCIES,
    ZERO,
    business_timezone,
    local_date,
    today,
    month_start,
    date_range,
    financial_report,
    project_report,
    chart_data,
)

bp = Blueprint("dashboard", __name__)


@bp.app_template_filter("currency")
def format_currency(value, code=None):
    if value is None or value == "":
        return "—"
    code = code or setting(
        "currency", current_app.config.get("DEFAULT_CURRENCY", "PHP")
    )
    symbols = {
        "PHP": "₱",
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "CAD": "CA$",
        "AUD": "A$",
        "SGD": "S$",
    }
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
        if not amount.is_finite():
            return "—"
        return f"{symbols.get(code, code + ' ')}{amount:,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "—"


@bp.app_template_filter("localtime")
def format_localtime(value, fmt="%b %d, %Y"):
    if not value:
        return "—"
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(business_timezone()).strftime(fmt)
    if isinstance(value, date):
        return value.strftime(fmt)
    return str(value)


@bp.app_context_processor
def ui_context():
    # Error/login pages must remain usable before the first database migration.
    if not current_user.is_authenticated:
        return {}
    return {
        "ui_company": setting("company_name", "My Studio"),
        "ui_currency": setting(
            "currency", current_app.config.get("DEFAULT_CURRENCY", "PHP")
        ),
        "ui_timezone": setting(
            "business_timezone",
            current_app.config.get("BUSINESS_TIMEZONE", "Asia/Manila"),
        ),
        "ui_demo_mode": setting("demo_mode", "false") == "true",
        "ui_unread_notifications": db.session.scalar(
            db.select(func.count(Notification.id)).where(Notification.read.is_(False))
        ),
    }


def count(model, *criteria):
    return db.session.scalar(db.select(func.count(model.id)).where(*criteria)) or 0


@bp.get("/dashboard")
@admin_required
def index():
    current_date = today()
    now = utcnow()
    currency = setting("currency", current_app.config.get("DEFAULT_CURRENCY", "PHP"))
    month_report = financial_report(month_start(current_date), current_date, currency)
    invoices = db.session.scalars(
        db.select(Invoice).where(
            Invoice.issued_at.is_not(None),
            Invoice.status != "void",
            Invoice.currency == currency,
        )
    ).all()
    outstanding = sum((max(invoice.balance, ZERO) for invoice in invoices), ZERO)
    counts = {
        "clients": count(Client, Client.status != "archived"),
        "leads": count(Lead, Lead.status.notin_(["converted", "lost", "archived"])),
        "projects": count(Project, Project.status == "active"),
        "overdue": count(
            Task,
            Task.due_at < now,
            Task.status.notin_(["completed", "done", "canceled"]),
        ),
        "drafts": count(EmailDraft, EmailDraft.status == "draft"),
        "approvals": count(ProjectStage, ProjectStage.status == "submitted"),
        "invoices": sum(invoice.balance > ZERO for invoice in invoices),
    }
    active_projects = db.session.scalars(
        db.select(Project)
        .where(Project.status.in_(["active", "paused"]))
        .order_by(Project.updated_at.desc())
        .limit(5)
    ).all()
    tasks = db.session.scalars(
        db.select(Task)
        .where(Task.status.notin_(["completed", "done", "canceled"]))
        .order_by(Task.due_at.is_(None), Task.due_at, Task.id.desc())
        .limit(5)
    ).all()
    milestone = db.session.scalar(
        db.select(ProjectMilestone)
        .where(ProjectMilestone.completed.is_(False), ProjectMilestone.due_at >= now)
        .order_by(ProjectMilestone.due_at)
    )
    activity = db.session.scalars(
        db.select(ActivityLog)
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(5)
    ).all()
    notifications = db.session.scalars(
        db.select(Notification)
        .where(Notification.read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(10)
    ).all()
    return render_template(
        "dashboard/index.html",
        title="Dashboard",
        counts=counts,
        report=month_report,
        month_report=month_report,
        outstanding=outstanding,
        projects=active_projects,
        tasks=tasks,
        milestone=milestone,
        activity=activity,
        notifications=notifications,
    )


@bp.post("/notifications/<int:notification_id>/read")
@admin_required
def notification_read(notification_id):
    notification = db.get_or_404(Notification, notification_id)
    notification.read = True
    db.session.commit()
    return redirect(url_for("dashboard.index", _anchor="activity"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        data = request.form
        try:
            company = data.get("company_name", "").strip()
            if not company or len(company) > 120:
                raise ValueError("Enter a company name between 1 and 120 characters.")
            currency = data.get("currency", "PHP").upper()
            if currency not in CURRENCIES:
                raise ValueError("Select a supported currency.")
            tz = data.get("business_timezone", "").strip()
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(
                    "Enter a valid timezone, such as Asia/Manila or America/Toronto."
                ) from None
            values = {
                "company_name": company,
                "currency": currency,
                "business_timezone": tz,
                "automations_paused": "true"
                if data.get("automations_paused")
                else "false",
                "email_test_mode": "true" if data.get("email_test_mode") else "false",
            }
            for key, value in values.items():
                record = db.session.scalar(
                    db.select(ApplicationSetting).where(ApplicationSetting.key == key)
                )
                if record is None:
                    record = ApplicationSetting(key=key)
                    db.session.add(record)
                record.value = value
            audit(
                "settings.updated", "ApplicationSetting", None, {"keys": list(values)}
            )
            log_activity("settings.updated", "Workspace preferences updated")
            db.session.commit()
            flash("Your workspace preferences are saved.", "success")
            return redirect(url_for("dashboard.settings"))
        except (ValueError, IntegrityError) as exc:
            db.session.rollback()
            flash(
                str(exc)
                if isinstance(exc, ValueError)
                else "Settings could not be saved. Please try again.",
                "error",
            )
            return render_template(
                "dashboard/settings.html",
                title="Settings",
                currencies=CURRENCIES,
                values=data,
                config_test_mode=current_app.config.get("EMAIL_TEST_MODE", True),
            ), 400
    values = {
        "company_name": setting("company_name", "My Studio"),
        "currency": setting(
            "currency", current_app.config.get("DEFAULT_CURRENCY", "PHP")
        ),
        "business_timezone": setting(
            "business_timezone",
            current_app.config.get("BUSINESS_TIMEZONE", "Asia/Manila"),
        ),
        "automations_paused": setting("automations_paused", "false") == "true",
        "email_test_mode": setting("email_test_mode", "true") == "true",
    }
    return render_template(
        "dashboard/settings.html",
        title="Settings",
        currencies=CURRENCIES,
        values=values,
        config_test_mode=current_app.config.get("EMAIL_TEST_MODE", True),
    )


@bp.get("/analytics")
@bp.get("/analytics/export.csv")
@admin_required
def analytics():
    try:
        start, end = date_range(request.args)
        currency = request.args.get(
            "currency",
            setting("currency", current_app.config.get("DEFAULT_CURRENCY", "PHP")),
        ).upper()
        if currency not in CURRENCIES:
            raise ValueError("Select a supported currency.")
    except ValueError as exc:
        return render_template(
            "dashboard/report_error.html", title="Analytics", message=str(exc)
        ), 400
    report = financial_report(start, end, currency)
    projects = project_report(start, end)
    if request.path.endswith(".csv") or request.args.get("format") == "csv":
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "Operational business report",
                "Currency",
                currency,
                "Start",
                start,
                "End",
                end,
            ]
        )
        writer.writerow(["Metric", "Amount"])
        for key in (
            "proposed",
            "contracted",
            "invoiced",
            "receipts",
            "expenses",
            "cash_net",
            "outstanding",
            "overdue",
            "maintenance_receipts",
            "maintenance_mrr",
        ):
            writer.writerow([key, str(report[key])])
        writer.writerow([])
        writer.writerow(
            ["Month", "Verified receipts", "Expenses", "Currently overdue by due month"]
        )
        for month in report["monthly"]:
            writer.writerow(
                [
                    month["key"],
                    str(month["receipts"]),
                    str(month["expenses"]),
                    str(month["overdue"]),
                ]
            )
        for dimension in ("by_client", "by_project", "by_service"):
            writer.writerow([])
            writer.writerow([dimension, "Verified receipts"])
            for label, amount in report[dimension]:
                # CSV cells originating from client data must not become spreadsheet formulas.
                safe_label = (
                    "'" + label
                    if label.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                    else label
                )
                writer.writerow([safe_label, str(amount)])
        writer.writerow([])
        writer.writerow(["Lead conversion percent", projects["conversion_rate"]])
        writer.writerow(["Project completion percent", projects["completion_rate"]])
        return Response(
            buffer.getvalue(),
            content_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="hanami-report-{start}-{end}.csv"',
                "Cache-Control": "no-store",
            },
        )
    return render_template(
        "dashboard/analytics.html",
        title="Analytics",
        report=report,
        projects=projects,
        chart=chart_data(report),
        currencies=CURRENCIES,
    )


@bp.get("/calendar")
@admin_required
def calendar():
    try:
        month = date.fromisoformat(
            request.args.get("month", today().strftime("%Y-%m")) + "-01"
        )
        if not 1901 <= month.year <= 9998:
            raise ValueError
    except ValueError:
        return render_template(
            "dashboard/report_error.html",
            title="Calendar",
            message="Choose a valid calendar month.",
        ), 400
    days = list(
        calendar_module.Calendar(firstweekday=0).itermonthdates(month.year, month.month)
    )
    start, end = days[0], days[-1]
    events = {}

    def add(value, label, kind, url):
        day = local_date(value) if value else None
        if day and start <= day <= end:
            events.setdefault(day, []).append(
                {"label": label, "kind": kind, "url": url}
            )

    for task in db.session.scalars(
        db.select(Task).where(
            Task.due_at.is_not(None), Task.status.notin_(["completed", "canceled"])
        )
    ):
        add(task.due_at, task.title, "task", f"/tasks/{task.id}")
    for item in db.session.scalars(
        db.select(ProjectMilestone).where(ProjectMilestone.completed.is_(False))
    ):
        add(item.due_at, item.title, "milestone", f"/projects/{item.project_id}")
    for invoice in db.session.scalars(
        db.select(Invoice).where(
            Invoice.due_at.is_not(None),
            Invoice.issued_at.is_not(None),
            Invoice.status != "void",
        )
    ):
        if invoice.balance > ZERO:
            add(
                invoice.due_at,
                f"{invoice.reference} due",
                "invoice",
                f"/invoices/{invoice.id}",
            )
    for lead in db.session.scalars(
        db.select(Lead).where(
            Lead.follow_up_at.is_not(None),
            Lead.status.notin_(["converted", "lost", "archived"]),
        )
    ):
        add(
            lead.follow_up_at,
            f"Follow up: {lead.business_name or lead.name}",
            "follow-up",
            f"/leads/{lead.id}",
        )
    for project in db.session.scalars(
        db.select(Project).where(
            Project.deadline.is_not(None), Project.status == "active"
        )
    ):
        add(project.deadline, project.title, "milestone", f"/projects/{project.id}")
    for meeting in db.session.scalars(
        db.select(Meeting).where(Meeting.status == "scheduled")
    ):
        add(
            meeting.scheduled_at,
            meeting.title,
            "follow-up",
            f"/projects/{meeting.project_id}/discovery",
        )
    for item in db.session.scalars(
        db.select(MaintenanceTask).where(MaintenanceTask.status != "completed")
    ):
        add(
            item.due_at,
            item.title,
            "task",
            f"/maintenance?project_id={item.project_id}",
        )
    for item in db.session.scalars(
        db.select(MaintenanceAgreement).where(MaintenanceAgreement.status == "active")
    ):
        add(
            item.renewal_date,
            f"Renewal: {item.name}",
            "invoice",
            f"/maintenance?project_id={item.project_id}",
        )
    for item in db.session.scalars(
        db.select(HandoverRecord).where(HandoverRecord.warranty_expires_at.is_not(None))
    ):
        add(
            item.warranty_expires_at,
            "Warranty ends",
            "milestone",
            f"/projects/{item.project_id}/handover",
        )
    for item in db.session.scalars(
        db.select(TrainingRecord).where(TrainingRecord.status == "scheduled")
    ):
        add(
            item.scheduled_at,
            f"Training: {item.participants}",
            "follow-up",
            f"/projects/{item.project_id}/handover",
        )
    return render_template(
        "dashboard/calendar.html",
        title="Calendar",
        month=month,
        days=days,
        events=events,
        today=today(),
        previous=month_start(month, -1).strftime("%Y-%m"),
        following=month_start(month, 1).strftime("%Y-%m"),
    )


@bp.get("/search")
@admin_required
def search():
    query = request.args.get("q", "").strip()[:200]
    results = []
    if query:
        # Literal search: '%' and '_' in a business name are not wildcard operators.
        needle = (
            "%"
            + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        sources = [
            (
                Client,
                ["name", "business_name", "email", "reference"],
                "Client",
                "clients",
                "/clients",
                "business_name",
            ),
            (
                Lead,
                ["name", "business_name", "email", "reference"],
                "Lead",
                "leads",
                "/leads",
                "business_name",
            ),
            (
                Project,
                ["title", "reference", "description"],
                "Project",
                "projects",
                "/projects",
                "title",
            ),
            (Task, ["title", "description"], "Task", "tasks", "/tasks", "title"),
            (
                Inquiry,
                ["reference", "website_type", "business_description"],
                "Inquiry",
                "inquiries",
                "/inquiries",
                "reference",
            ),
            (
                Proposal,
                ["reference", "title"],
                "Proposal",
                "proposals",
                "/proposals",
                "title",
            ),
            (
                Contract,
                ["reference"],
                "Contract",
                "contracts",
                "/contracts",
                "reference",
            ),
            (Invoice, ["reference"], "Invoice", "invoices", "/invoices", "reference"),
            (Document, ["title"], "Document", "documents", "/documents", "title"),
            (
                EmailDraft,
                ["subject", "recipient"],
                "Email draft",
                "email",
                "/email",
                "subject",
            ),
            (
                SupportTicket,
                ["title", "description"],
                "Support ticket",
                "clients",
                "/support",
                "title",
            ),
        ]
        for model, fields, category, icon, path, label in sources:
            rows = db.session.scalars(
                db.select(model)
                .where(
                    or_(
                        *[
                            getattr(model, field).ilike(needle, escape="\\")
                            for field in fields
                        ]
                    )
                )
                .limit(20)
            ).all()
            for row in rows:
                results.append(
                    {
                        "title": getattr(row, label) or getattr(row, "name", category),
                        "subtitle": getattr(row, "reference", "")
                        or getattr(row, "status", ""),
                        "category": category,
                        "icon": icon,
                        "url": f"{path}/{row.id}"
                        if model is not SupportTicket
                        else f"/support?project_id={row.project_id}",
                    }
                )
    return render_template(
        "dashboard/search.html", title="Search", search_query=query, results=results
    )
