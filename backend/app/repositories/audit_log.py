"""Repository for the immutable audit trail."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog


class AuditLogRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, entry: dict) -> AuditLog:
        row = AuditLog(
            run_id=entry.get("run_id"),
            actor=entry.get("actor"),
            action=entry["action"],
            target_type=entry.get("target_type"),
            target_id=entry.get("target_id"),
            payload=entry.get("payload"),
            result=entry.get("result"),
        )
        self.session.add(row)
        self.session.commit()
        return row
