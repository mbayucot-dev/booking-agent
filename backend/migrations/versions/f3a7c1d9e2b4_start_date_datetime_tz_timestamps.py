"""appointments.start_date -> DateTime; timestamps -> timezone-aware

Promotes ``appointments.start_date`` from a sortable VARCHAR to a real temporal
column (range/ordering queries become first-class) and makes the instant
timestamp columns timezone-aware (they store ``datetime.now(UTC)``, so the UTC
offset is now preserved rather than dropped).

Uses ``batch_alter_table`` so it runs on SQLite (table-recreate) as well as
Postgres; ``postgresql_using`` supplies the Postgres type cast.

Revision ID: f3a7c1d9e2b4
Revises: b2f1a9c4d7e3
Create Date: 2026-06-15 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7c1d9e2b4"
down_revision: str | None = "b2f1a9c4d7e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Instant timestamps (stored as UTC) that become timezone-aware. appointments is
# handled separately (it also gets the start_date type change).
_TZ: dict[str, list[str]] = {
    "runs": ["created_at", "updated_at"],
    "run_events": ["created_at"],
    "approvals": ["decided_at", "created_at"],
    "audit_logs": ["created_at"],
    "customer_memories": ["created_at", "updated_at"],
    "executed_actions": ["created_at"],
    "staff": ["created_at"],
    "clients": ["created_at"],
    "contacts": ["created_at"],
    "jobs": ["created_at"],
}


def _is_sqlite() -> bool:
    # SQLite (the dev default) has dynamic typing: the declared column type is
    # advisory and SQLAlchemy's DateTime already parses the stored ISO text on
    # read, so the type change is a runtime no-op there. We MUST skip the DDL:
    # the batch-recreate's implicit CAST('2026-06-20 09:00:00' AS DATETIME) keeps
    # only the leading integer (2026) under NUMERIC affinity, silently corrupting
    # existing rows. Postgres (the deployment target) enforces types and applies
    # the postgresql_using cast correctly.
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        # Don't run the type DDL (see _is_sqlite). One data touch-up: the ORM now
        # binds start_date with microsecond precision ("...:00.000000"), so
        # normalise legacy bare-second text values to match — otherwise the
        # free@hour `==` gate would miss them on SQLite. Idempotent (rows with a
        # '.' are skipped); value is unchanged (microseconds = 0).
        op.execute(
            "UPDATE appointments SET start_date = start_date || '.000000' "
            "WHERE start_date NOT LIKE '%.%'"
        )
        return
    with op.batch_alter_table("appointments") as batch:
        batch.alter_column(
            "start_date",
            existing_type=sa.String(length=32),
            type_=sa.DateTime(),
            existing_nullable=False,
            postgresql_using="start_date::timestamp",
        )
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            postgresql_using="created_at AT TIME ZONE 'UTC'",
        )
    for table, columns in _TZ.items():
        with op.batch_alter_table(table) as batch:
            for col in columns:
                batch.alter_column(
                    col,
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    postgresql_using=f"{col} AT TIME ZONE 'UTC'",
                )


def downgrade() -> None:
    if _is_sqlite():
        return
    for table, columns in _TZ.items():
        with op.batch_alter_table(table) as batch:
            for col in columns:
                batch.alter_column(
                    col, existing_type=sa.DateTime(timezone=True), type_=sa.DateTime()
                )
    with op.batch_alter_table("appointments") as batch:
        batch.alter_column(
            "created_at", existing_type=sa.DateTime(timezone=True), type_=sa.DateTime()
        )
        batch.alter_column(
            "start_date",
            existing_type=sa.DateTime(),
            type_=sa.String(length=32),
            existing_nullable=False,
            postgresql_using="to_char(start_date, 'YYYY-MM-DD HH24:MI:SS')",
        )
