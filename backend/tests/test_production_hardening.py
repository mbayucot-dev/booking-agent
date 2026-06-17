"""Production-readiness: security headers, CORS, docs gating, readiness probe,
run_events size guard, and Alembic migrations."""

import logging

from fastapi.testclient import TestClient

# --- HTTP hardening -------------------------------------------------------


def test_security_headers_present():
    from app.main import create_app

    c = TestClient(create_app())
    r = c.get("/api/v1/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_cors_allows_configured_origin_only(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")
    from app.main import create_app

    c = TestClient(create_app())
    ok = c.get("/api/v1/health", headers={"Origin": "https://app.example"})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example"
    # A foreign origin is NOT reflected (no wildcard).
    foreign = c.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert foreign.headers.get("access-control-allow-origin") is None


def test_cors_wildcard_rejected_in_production(monkeypatch):
    import pytest

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "*")
    from app.config import get_settings

    with pytest.raises(ValueError, match="wildcard"):
        get_settings()


def test_prod_without_auth_token_refuses_to_start(monkeypatch):
    import pytest

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    from app.config import get_settings

    with pytest.raises(ValueError, match="API_AUTH_TOKEN"):
        get_settings()


def test_prod_with_auth_token_starts(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "prod-secret")
    from app.config import get_settings

    s = get_settings()
    assert s.is_production is True
    assert s.api_auth_token == "prod-secret"


def test_dev_without_auth_token_is_allowed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    from app.config import get_settings

    assert get_settings().api_auth_token is None  # dev stays open


def test_docs_hidden_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_AUTH_TOKEN", "prod-secret")  # prod refuses to boot without one
    from app.main import create_app

    c = TestClient(create_app())
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404


def test_docs_visible_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    from app.main import create_app

    c = TestClient(create_app())
    assert c.get("/openapi.json").status_code == 200


# --- readiness ------------------------------------------------------------


def test_readiness_ok():
    from app.main import create_app

    c = TestClient(create_app())
    r = c.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_503_when_db_down(monkeypatch):
    import app.api.v1.health as health

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(health, "SessionLocal", _boom)
    from app.main import create_app

    c = TestClient(create_app())
    r = c.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"


# --- run_events size guard ------------------------------------------------


def test_instrumentation_truncates_oversized_output():
    from app.graph.instrumentation import MAX_STR_LEN, InMemoryEventSink, instrument

    sink = InMemoryEventSink()
    node = instrument("big_node", lambda state: {"blob": "x" * (MAX_STR_LEN + 500)}, sink)
    node({"run_id": "r1"})

    success = [e for e in sink.events if e.status == "success"][0]
    assert success.output["blob"].endswith("…[truncated]")
    assert len(success.output["blob"]) <= MAX_STR_LEN + len("…[truncated]")


# --- migrations -----------------------------------------------------------


def test_alembic_upgrade_creates_expected_schema(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert {
        "runs",
        "run_events",
        "approvals",
        "audit_logs",
        "customer_memories",
        "staff",
        "staff_skills",
        "clients",
        "contacts",
        "jobs",
        "appointments",
    }.issubset(tables)


def test_start_date_migration_preserves_existing_data_on_sqlite(tmp_path, monkeypatch):
    """Regression: the start_date String->DateTime upgrade must NOT corrupt
    existing rows on SQLite (a naive CAST keeps only the leading integer), AND a
    legacy bare-second value must still match the free@hour `==` gate after the
    migration normalises it to the ORM's microsecond precision."""
    from datetime import datetime

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session as OrmSession

    url = f"sqlite:///{tmp_path / 'data.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "b2f1a9c4d7e3")  # parent revision: start_date is VARCHAR text

    eng = create_engine(url)
    with eng.begin() as c:
        # FK enforcement is off by default on SQLite. Seed a skilled, booked staff.
        c.execute(
            text("INSERT INTO staff (id, name, active, created_at) "
                 "VALUES ('s1', 'Z', 1, '2026-06-01 00:00:00')")
        )
        c.execute(text("INSERT INTO staff_skills (staff_id, skill) VALUES ('s1', 'cleaning')"))
        c.execute(
            text(
                "INSERT INTO appointments (id, job_id, staff_id, staff_name, start_date, created_at)"
                " VALUES ('a1', 'j1', 's1', 'Z', '2026-06-20 09:00:00', '2026-06-20 00:00:00')"
            )
        )

    command.upgrade(cfg, "head")  # the start_date / tz migration

    from app.models import Appointment
    from app.repositories.booking import BookingRepository

    with OrmSession(eng) as s:
        assert s.get(Appointment, "a1").start_date == datetime(2026, 6, 20, 9, 0, 0)  # not 2026
        repo = BookingRepository(s)
        free9 = {st.id for st in repo.eligible_staff(date_iso="2026-06-20", time="09:00", skill="cleaning")}
        free10 = {st.id for st in repo.eligible_staff(date_iso="2026-06-20", time="10:00", skill="cleaning")}
    assert "s1" not in free9  # busy at 09:00 — gate matched the normalised legacy row
    assert "s1" in free10  # free at 10:00
    eng.dispose()


def test_appt_slot_partial_unique_index_replaces_old(tmp_path, monkeypatch):
    """The slot migration swaps the non-unique ix_appt_staff_start for the partial
    unique uq_appt_staff_slot, which rejects a duplicate (staff_id, start_date)."""
    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    url = f"sqlite:///{tmp_path / 'slot.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    names = {i["name"] for i in inspect(eng).get_indexes("appointments")}
    assert "uq_appt_staff_slot" in names
    assert "ix_appt_staff_start" not in names

    def _insert(c, aid, staff):
        sid = f"'{staff}'" if staff else "NULL"
        c.execute(
            text(
                f"INSERT INTO appointments (id, job_id, staff_id, staff_name, start_date, created_at)"
                f" VALUES ('{aid}', 'j', {sid}, 'x', '2026-06-20 10:00:00', '2026-06-20 00:00:00')"
            )
        )

    with eng.begin() as c:
        _insert(c, "a1", "s1")
        _insert(c, "a2", None)  # null staff is exempt
        _insert(c, "a3", None)  # second null at same slot is allowed
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            _insert(c, "a4", "s1")  # same (s1, 10:00) → rejected
    eng.dispose()


def test_setup_logging_is_idempotent():
    # setup_logging() should be safe to call repeatedly.
    from app.core.logging import setup_logging

    setup_logging()
    setup_logging()
    assert logging.getLogger().handlers
