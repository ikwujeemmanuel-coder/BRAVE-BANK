"""Audit logging and in-app notification helpers."""

import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.models.support import AuditLog, Notification


def log_audit(
    db: Session,
    action: str,
    resource_type: str,
    user_id: Optional[uuid.UUID] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        details_json=details,
    )
    db.add(entry)
    return entry


def create_notification(
    db: Session,
    user_id: uuid.UUID,
    category: str,
    title: str,
    message: str,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        category=category,
        title=title,
        message=message,
    )
    db.add(notification)
    return notification
