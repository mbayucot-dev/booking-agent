"""appointments: partial unique (staff_id, start_date) slot index

Replaces the non-unique ``ix_appt_staff_start`` with a PARTIAL UNIQUE index
``uq_appt_staff_slot`` on ``(staff_id, start_date) WHERE staff_id IS NOT NULL``,
so the same staff can't be double-booked at one start_date (unassigned/null-staff
rows stay exempt). Postgres and SQLite (>=3.8) both support the partial index.

Revision ID: a1c4e8f2b9d6
Revises: f3a7c1d9e2b4
Create Date: 2026-06-20 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c4e8f2b9d6"
down_revision: str | None = "f3a7c1d9e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_appt_staff_start", table_name="appointments")
    # Preflight: the new index is UNIQUE, so abort with an actionable message if existing
    # data already double-books a staff slot — rather than a cryptic index-build failure.
    dupes = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT 1 FROM appointments WHERE staff_id IS NOT NULL "
            "GROUP BY staff_id, start_date HAVING COUNT(*) > 1) d"
        )
    ).scalar()
    if dupes:
        raise RuntimeError(
            f"Cannot create uq_appt_staff_slot: {dupes} staff/start_date slot(s) are already "
            "double-booked. Resolve duplicates before deploying:\n"
            "  SELECT staff_id, start_date, COUNT(*) FROM appointments WHERE staff_id IS NOT NULL "
            "GROUP BY staff_id, start_date HAVING COUNT(*) > 1;"
        )
    where = sa.text("staff_id IS NOT NULL")
    op.create_index(
        "uq_appt_staff_slot",
        "appointments",
        ["staff_id", "start_date"],
        unique=True,
        postgresql_where=where,
        sqlite_where=where,
    )


def downgrade() -> None:
    op.drop_index("uq_appt_staff_slot", table_name="appointments")
    op.create_index(
        "ix_appt_staff_start", "appointments", ["staff_id", "start_date"], unique=False
    )
