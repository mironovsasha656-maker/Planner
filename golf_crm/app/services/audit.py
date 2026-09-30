"""Audit log helper."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.labels import ROLES
from app.models import AuditLog


def log(
    session: Session,
    role: str,
    action: str,
    entity_type: str,
    entity_id: Optional[int],
    description: str,
    when: Optional[datetime] = None,
) -> AuditLog:
    entry = AuditLog(
        created_at=(when or datetime.now()).replace(microsecond=0),
        user=ROLES.get(role, role),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description[:500],
    )
    session.add(entry)
    return entry
