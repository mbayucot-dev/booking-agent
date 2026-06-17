"""SQLAlchemy ORM models.

``runs`` is one row per workflow execution; ``run_events`` is one row per node
transition — the source of truth the React Flow canvas replays / streams from.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class NodeStatus(enum.StrEnum):
    """Status of a single workflow node, mirrored 1:1 on the React Flow side."""

    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"
    waiting_approval = "waiting_approval"
    approved = "approved"
    rejected = "rejected"
    skipped = "skipped"


class RunStatus(enum.StrEnum):
    """Status of a whole run."""

    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    escalated = "escalated"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, default=_uuid)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.running.value)
    raw_message: Mapped[str] = mapped_column(Text)
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunEvent.id",
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    # Autoincrement PK gives a deterministic insertion order for replay/SSE.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    run: Mapped[Run] = relationship(back_populates="events")


class Approval(Base):
    """Persisted record of a human approval decision (auditability)."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))  # pending|approved|rejected
    card: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prepared_payloads: Mapped[list | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Immutable audit trail of executed mutations (who/what/when/result)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CustomerMemory(Base):
    """Long-term memory about a customer (durable preferences only).

    One row per (customer_key, memory_type); re-saving updates it."""

    __tablename__ = "customer_memories"
    __table_args__ = (UniqueConstraint("customer_key", "memory_type", name="uq_customer_memory"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_key: Mapped[str] = mapped_column(String(255), index=True)  # email/phone
    memory_type: Mapped[str] = mapped_column(String(32))  # preference|communication|vip|constraint
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ExecutedAction(Base):
    """Durable idempotency ledger: one row per executed mutation key.

    The executor checks this before running a prepared action, so a retry or a
    resume after a restart returns the recorded result instead of duplicating."""

    __tablename__ = "executed_actions"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- Local booking datastore ------------------------------------------------
# Mirrors the resources a field-service backend exposes (client / contact / job
# / appointment / staff), so the workflow books against our own database.


class Staff(Base):
    """A staff member jobs can be assigned to."""

    __tablename__ = "staff"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(default=True)
    # Services this cleaner can perform (for skill matching / display).
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Home-base location for proximity scoring (nullable).
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Free-text specialties + its embedding (JSON list) for semantic preference match.
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StaffSkill(Base):
    """Normalized skill rows so the skill gate is an indexed seek, not a scan."""

    __tablename__ = "staff_skills"

    staff_id: Mapped[str] = mapped_column(
        ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True
    )
    skill: Mapped[str] = mapped_column(String(64), primary_key=True)


# Indexes that turn the hard-filter gates into seeks.
Index("ix_staff_skills_skill", StaffSkill.skill)
Index("ix_staff_lat_lng", Staff.latitude, Staff.longitude)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Indexed: a returning customer is looked up by email (get-or-create) so we
    # don't create a duplicate client row per booking.
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Appointment(Base):
    """A job assigned to a staff member at a start time (the schedule)."""

    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    staff_id: Mapped[str | None] = mapped_column(ForeignKey("staff.id"), index=True, nullable=True)
    staff_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Local wall-clock start of the appointment. A real temporal column (not a
    # sortable string), so range/ordering queries are first-class.
    start_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# Partial unique index: one staff can't hold two appointments at the same
# start_date (DB-enforces the free@hour gate); null-staff rows are exempt.
Index(
    "uq_appt_staff_slot",
    Appointment.staff_id,
    Appointment.start_date,
    unique=True,
    postgresql_where=Appointment.staff_id.isnot(None),
)
