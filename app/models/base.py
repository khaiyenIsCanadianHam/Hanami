"""Shared SQLAlchemy base and exact decimal helpers."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4
from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def money(value):
    try:
        result = Decimal(str(value if value is not None else 0))
        if not result.is_finite():
            raise ValueError("Amount must be a finite number.")
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Enter a valid monetary amount.") from exc


def reference(prefix):
    return f"{prefix}-{uuid4().hex[:10].upper()}"


class BaseModel(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
