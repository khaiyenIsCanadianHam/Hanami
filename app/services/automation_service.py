"""Persistent, idempotent work suggestions; automatic messages always start as drafts."""

from datetime import timedelta

from app.extensions import db
from app.models.base import utcnow
from app.models.communications import EmailAutomationRule, ScheduledJob
from app.services.common import log_activity
from app.services.email_service import is_paused, prepare_email, process_email_queue


def schedule_job(kind, event_key, payload=None, due_at=None):
    existing = ScheduledJob.query.filter_by(event_key=event_key).first()
    if existing:
        return existing
    if kind not in {"create_task", "create_draft", "event", "reminder_scan"}:
        raise ValueError("Unsupported scheduled job type.")
    job = ScheduledJob(
        kind=kind, event_key=event_key, payload=payload or {}, due_at=due_at or utcnow()
    )
    db.session.add(job)
    return job


def trigger_event(event, project=None, event_key=None):
    """Call in the business transaction; actual rule execution is deferred to the worker."""
    if is_paused():
        return None
    key = event_key or f"{event}:project:{project.id if project else 'none'}"
    return schedule_job(
        "event", key, {"event": event, "project_id": project.id if project else None}
    )


def _task(event_key, title, project=None, client_id=None, due_at=None, description=""):
    from app.models.core import Task

    existing = Task.query.filter_by(event_key=event_key).first()
    if existing:
        return existing, False
    task = Task(
        title=title,
        description=description,
        event_key=event_key,
        project_id=project.id if project else None,
        client_id=project.client_id if project else client_id,
        due_at=due_at or utcnow(),
        status="backlog",
        priority="normal",
    )
    db.session.add(task)
    return task, True


def scan_reminders(now=None):
    from app.models.core import Lead, Project
    from app.models.finance import Invoice

    now = now or utcnow()
    added = 0
    for lead in Lead.query.filter(
        Lead.follow_up_at <= now, ~Lead.status.in_(["converted", "lost", "archived"])
    ).all():
        _, created = _task(
            f"lead-followup:{lead.id}:{lead.follow_up_at.isoformat()}",
            f"Review follow-up: {lead.name}",
            client_id=lead.client_id,
            description="Review communication history and consent before preparing a follow-up email.",
        )
        added += created
    for invoice in Invoice.query.all():
        due = getattr(invoice, "due_date", None) or getattr(invoice, "due_at", None)
        if (
            due is None
            or invoice.balance <= 0
            or str(invoice.status).lower() in {"paid", "void", "cancelled", "draft"}
        ):
            continue
        due_day = due.date() if hasattr(due, "date") else due
        if due_day >= now.date():
            continue
        project = db.session.get(Project, invoice.project_id)
        _, created = _task(
            f"invoice-reminder:{invoice.id}:{due_day.isoformat()}",
            f"Review overdue invoice {invoice.reference}",
            project=project,
            description="Review verified payments and any dispute before drafting a payment reminder.",
        )
        added += created
    # Delivery service owns recurring billing eligibility and period-level idempotency.
    from app.services.delivery_service import process_recurring_maintenance

    maintenance = process_recurring_maintenance(now=now)
    return {"reminders": added, **maintenance}


def _execute_job(job):
    from app.models.core import Project, Notification

    payload = job.payload or {}
    project = (
        db.session.get(Project, payload["project_id"])
        if payload.get("project_id")
        else None
    )
    if payload.get("project_id") and project is None:
        raise ValueError("Scheduled project no longer exists.")
    if job.kind == "create_task":
        _task(
            job.event_key,
            payload.get("title", "Review project"),
            project=project,
            description=payload.get("description", ""),
        )
    elif job.kind == "create_draft":
        if project is None:
            raise ValueError("Email draft jobs require a project.")
        prepare_email(
            project,
            payload["template_key"],
            context=payload.get("context"),
            event_key=job.event_key,
        )
    elif job.kind == "reminder_scan":
        scan_reminders()
    elif job.kind == "event":
        for rule in EmailAutomationRule.query.filter_by(
            trigger_event=payload.get("event"), enabled=True
        ).all():
            conditions = rule.conditions or {}
            if (
                project
                and conditions.get("project_status")
                and project.status != conditions["project_status"]
            ):
                continue
            if (
                project
                and conditions.get("stage")
                and project.current_stage != int(conditions["stage"])
            ):
                continue
            if project and project.status in {"canceled", "cancelled", "archived"}:
                continue
            action_key = f"rule:{rule.id}:{job.event_key}"
            if rule.action == "create_task":
                _task(
                    action_key, rule.name, project=project, description=rule.description
                )
            elif rule.action == "create_draft":
                if project is None:
                    raise ValueError("This rule requires a project.")
                prepare_email(project, rule.template_key, event_key=action_key)
            else:
                raise ValueError("Unsupported rule action.")
            rule.last_executed_at = utcnow()
            rule.execution_result = (
                "Completed; any email requires administrator review."
            )
            db.session.add(
                Notification(
                    title=rule.name,
                    body="Automation action prepared for review.",
                    project_id=project.id if project else None,
                )
            )
    log_activity(
        "automation.completed",
        f"Completed {job.kind} automation.",
        project_id=project.id if project else None,
    )


def run_due_jobs(limit=30, now=None):
    now = now or utcnow()
    if is_paused():
        return {"processed": 0, "failed": 0, "paused": True}
    # Non-SMTP job effects and success are in one transaction, so crashed jobs are safe to reclaim.
    ScheduledJob.query.filter(
        ScheduledJob.status == "running",
        ScheduledJob.claimed_at < now - timedelta(minutes=15),
    ).update({"status": "pending", "due_at": now}, synchronize_session=False)
    db.session.commit()
    ids = [
        job.id
        for job in ScheduledJob.query.filter(
            ScheduledJob.status == "pending", ScheduledJob.due_at <= now
        )
        .order_by(ScheduledJob.due_at)
        .limit(limit)
    ]
    result = {"processed": 0, "failed": 0, "paused": False}
    for job_id in ids:
        claim = db.session.execute(
            db.update(ScheduledJob)
            .where(ScheduledJob.id == job_id, ScheduledJob.status == "pending")
            .values(
                status="running", claimed_at=now, attempts=ScheduledJob.attempts + 1
            )
        )
        db.session.commit()
        if claim.rowcount != 1:
            continue
        job = db.session.get(ScheduledJob, job_id)
        db.session.refresh(job)
        try:
            _execute_job(job)
            job.status, job.completed_at, job.last_error = "completed", utcnow(), ""
            db.session.commit()
            result["processed"] += 1
        except Exception as exc:
            db.session.rollback()
            job = db.session.get(ScheduledJob, job_id)
            job.status = "pending" if job.attempts < job.max_attempts else "failed"
            job.due_at = now + timedelta(minutes=2**job.attempts)
            job.last_error = f"Job failed ({type(exc).__name__}). Review its inputs and application configuration."
            log_activity(
                "automation.failed",
                f"Scheduled job {job.id} failed ({type(exc).__name__}).",
            )
            db.session.commit()
            current = __import__("flask").current_app
            current.logger.warning(
                "Scheduled job %s failed (%s)", job.id, type(exc).__name__
            )
            result["failed"] += 1
    return result


def scheduler_tick():
    if is_paused():
        return
    # Hourly scans find newly due reminders; each generated business action has its own stable key.
    schedule_job("reminder_scan", f"reminder-scan:{utcnow().strftime('%Y-%m-%dT%H')}")
    db.session.commit()
    run_due_jobs()
    process_email_queue()
