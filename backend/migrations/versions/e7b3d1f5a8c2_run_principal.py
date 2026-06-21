"""runs: add principal column for run ownership tracking

Records the initiating authenticated identity (token alias, user-id, etc.) on
each run row so ownership checks and per-principal audit queries are possible
without scanning audit_logs. Nullable — existing rows and open (dev) deployments
have no principal on file.

Revision ID: e7b3d1f5a8c2
Revises: a1c4e8f2b9d6
Create Date: 2026-06-20 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3d1f5a8c2"
down_revision: str | None = "a1c4e8f2b9d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("principal", sa.String(length=128), nullable=True))
    op.create_index("ix_runs_principal", "runs", ["principal"])


def downgrade() -> None:
    op.drop_index("ix_runs_principal", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("principal")
