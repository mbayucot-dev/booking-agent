"""Alembic environment — migrations target the app's SQLAlchemy metadata.

The DB URL comes from DATABASE_URL (same as the running app), so `alembic
upgrade head` provisions exactly the schema the ORM expects.
"""

from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.getcwd())

import app.models  # noqa: F401 — register all tables on Base.metadata
from app.db import DATABASE_URL, Base

config = context.config
config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", DATABASE_URL))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # sqlite-friendly ALTERs
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
