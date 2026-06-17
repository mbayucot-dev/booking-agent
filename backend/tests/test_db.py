"""Engine construction: SQLite vs. a pooled Postgres engine."""

from app.db import make_engine


def test_sqlite_engine_has_no_pool_sizing():
    engine = make_engine("sqlite:///:memory:")
    assert engine.dialect.name == "sqlite"
    engine.dispose()


def test_postgres_engine_is_pool_sized(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "20")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "10")
    # create_engine is lazy — no connection is opened here.
    engine = make_engine("postgresql+psycopg://u:p@localhost:5432/db")
    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == 20  # configured pool_size, not the default 5
    engine.dispose()
