"""durable idempotency ledger + clients.email index

Adds the ``executed_actions`` table (durable idempotency ledger so a retried or
post-restart resume never double-books) and an index on ``clients.email``
(returning-customer get-or-create lookup).

Revision ID: b2f1a9c4d7e3
Revises: c5bfbbc672f9
Create Date: 2026-06-13 22:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2f1a9c4d7e3'
down_revision: Union[str, None] = 'c5bfbbc672f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'executed_actions',
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('idempotency_key'),
    )
    with op.batch_alter_table('executed_actions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_executed_actions_run_id'), ['run_id'], unique=False
        )
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_clients_email'), ['email'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_clients_email'))
    with op.batch_alter_table('executed_actions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_executed_actions_run_id'))
    op.drop_table('executed_actions')
