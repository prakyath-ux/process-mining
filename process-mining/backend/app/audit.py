"""Audit trail helpers — every sensitive action is recorded."""

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog, User


def record_audit(
    db: Session,
    *,
    action: str,
    user: User | None = None,
    resource: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            resource=resource,
            detail=detail or {},
        )
    )
