"""clients: add unique constraint on email

Converts the plain index on clients.email to a unique constraint so that
get_or_create_client can use insert-first + IntegrityError to close the
check-then-insert race window. NULL emails remain freely duplicated (each
NULL is distinct in both SQLite and Postgres).

Revision ID: f8a2c6d1e9b5
Revises: e7b3d1f5a8c2
Create Date: 2026-06-20 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "f8a2c6d1e9b5"
down_revision: str | None = "e7b3d1f5a8c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_index("ix_clients_email")
        batch.create_unique_constraint("uq_clients_email", ["email"])


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_constraint("uq_clients_email", type_="unique")
        batch.create_index("ix_clients_email", ["email"])
