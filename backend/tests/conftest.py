"""Test harness — runs on the SAME engine as production: Postgres + pgvector,
booted once per session via testcontainers. Each test gets a clean database
(all tables truncated), so suites are isolated without per-test containers.
"""

import pytest
from sqlalchemy import create_engine, text
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
    if tables:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


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
    "Create a booking for John Doe for contact work on June 20 at 10am. "
    "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
)


@pytest.fixture()
def example_message() -> str:
    return EXAMPLE_MESSAGE
