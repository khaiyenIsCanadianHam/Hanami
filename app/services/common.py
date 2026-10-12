"""Shared transactional helpers. Callers own commit and rollback."""

from functools import wraps
import json
from flask import abort, has_request_context
from flask_login import current_user, login_required
from app.extensions import db
from app.models.core import ActivityLog, AuditLog, ApplicationSetting


def log_activity(action, description, client_id=None, project_id=None):
    record = ActivityLog(
        action=action,
        description=description,
        client_id=client_id,
        project_id=project_id,
    )
    db.session.add(record)
    return record


def audit(action, entity, entity_id, details=""):
    actor_id = (
        current_user.id
        if has_request_context() and current_user.is_authenticated
        else None
    )
    record = AuditLog(
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=json.dumps(details, default=str)
        if isinstance(details, (dict, list))
        else str(details or ""),
    )
    db.session.add(record)
    return record


def setting(key, default=""):
    record = db.session.scalar(
        db.select(ApplicationSetting).where(ApplicationSetting.key == key)
    )
    return record.value if record else default


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.active or current_user.role != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped
