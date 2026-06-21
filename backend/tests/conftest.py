"""Test harness — runs on the SAME engine as production: Postgres + pgvector,
booted once per session via testcontainers. Each test gets a clean database
(all tables truncated), so suites are isolated without per-test containers.
"""

import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register all tables on Base.metadata
from app.db import Base


@pytest.fixture(scope="session")
def pg_engine():
    """One Postgres+pgvector container for the whole test session."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="psycopg") as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


def _truncate_all(engine) -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    if not tables:
        return
    # TRUNCATE takes an ACCESS EXCLUSIVE lock on every table. A pooled app connection (used by
    # a TestClient request) can still briefly hold a conflicting lock, which under CI load
    # surfaces as a deadlock at teardown. Bound the wait with lock_timeout and retry the victim.
    for attempt in range(5):
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            return
        except OperationalError:
            if attempt == 4:
                raise
            time.sleep(0.25 * (attempt + 1))


@pytest.fixture()
def Session(pg_engine):
    """Sessionmaker bound to the shared Postgres engine. Data is wiped after
    each test for isolation."""
    maker = sessionmaker(bind=pg_engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        _truncate_all(pg_engine)


@pytest.fixture()
def db_session(Session):
    """A single Postgres session (tables truncated after the test)."""
    session = Session()
    try:
        yield session
    finally:
        session.close()


EXAMPLE_MESSAGE = (
    "Create a booking for John Doe for contact work on December 20, 2028 at 10am. "
    "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
)


@pytest.fixture()
def example_message() -> str:
    return EXAMPLE_MESSAGE
