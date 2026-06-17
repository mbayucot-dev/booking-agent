"""Database engine, session factory, and declarative base.

Synchronous SQLAlchemy 2.0 setup that works against both PostgreSQL (production)
and SQLite (tests); columns use portable types so the same models run on both.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Default to a local SQLite file; docker-compose overrides with a Postgres URL.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./booking.db")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str = DATABASE_URL):
    if url.startswith("sqlite"):
        # SQLite has no real connection pool to size.
        return create_engine(
            url, connect_args={"check_same_thread": False}, future=True, pool_pre_ping=True
        )
    # Pool sized for the thread-per-run model. pool_pre_ping avoids stale
    # connections after DB restarts; statement_timeout stops a slow query from
    # pinning a pooled connection forever.
    from .config import get_settings  # lazy: avoid a config import at module load

    s = get_settings()
    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_recycle=s.db_pool_recycle,
        # Fail fast instead of blocking a worker forever when the pool is drained.
        pool_timeout=s.db_pool_timeout,
        connect_args={"options": f"-c statement_timeout={s.db_statement_timeout_ms}"},
    )


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
