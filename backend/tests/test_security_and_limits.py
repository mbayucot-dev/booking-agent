"""Auth on the run endpoints + the in-process rate limiter."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import api_router
from app.core.auth import API_PRINCIPAL, require_principal
from app.core.events import EventBus
from app.core.exceptions import AuthError, register_exception_handlers
from app.core.ratelimit import FixedWindowLimiter, _client_key, rate_limit_runs
from app.graph.email import DryRunEmailSender
from app.models import Approval
from app.services.run_service import WorkflowRunner
from tests.helpers import make_booking_executor, make_provider
from tests.test_runs_api import GOOD_MESSAGE


def _app(Session):
    runner = WorkflowRunner(
        session_factory=Session,
        executor=make_booking_executor(Session),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
        event_bus=EventBus(),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[deps.get_runner] = lambda: runner
    app.include_router(api_router)
    return TestClient(app), runner


# --- auth dependency (unit) -----------------------------------------------


class _S:
    def __init__(self, token):
        self.api_auth_token = token


def test_require_principal_open_when_no_token():
    assert require_principal(creds=None, settings=_S(None)) is None


def test_require_principal_rejects_missing_and_wrong():
    with pytest.raises(AuthError):
        require_principal(creds=None, settings=_S("secret"))
    bad = SimpleNamespace(scheme="Bearer", credentials="nope")
    with pytest.raises(AuthError):
        require_principal(creds=bad, settings=_S("secret"))
    wrong_scheme = SimpleNamespace(scheme="Basic", credentials="secret")
    with pytest.raises(AuthError):
        require_principal(creds=wrong_scheme, settings=_S("secret"))


def test_require_principal_accepts_valid_bearer():
    ok = SimpleNamespace(scheme="Bearer", credentials="secret")
    assert require_principal(creds=ok, settings=_S("secret")) == API_PRINCIPAL


# --- auth enforced on the API ---------------------------------------------


def test_runs_require_bearer_when_token_set(monkeypatch, Session):
    monkeypatch.setenv("API_AUTH_TOKEN", "secret")
    c, _ = _app(Session)
    assert c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}).status_code == 401
    auth = {"Authorization": "Bearer secret"}
    assert c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}, headers=auth).status_code == 202


def test_approver_identity_is_the_principal_not_client_supplied(monkeypatch, Session):
    monkeypatch.setenv("API_AUTH_TOKEN", "secret")
    c, runner = _app(Session)
    auth = {"Authorization": "Bearer secret"}
    run_id = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}, headers=auth).json()["run_id"]
    runner.wait(run_id)
    # Forge an identity in the body — it must be ignored in favour of the token.
    c.post(f"/api/v1/runs/{run_id}/approve", json={"by": "forged@evil"}, headers=auth)
    runner.wait(run_id)
    with Session() as s:
        approval = s.query(Approval).filter_by(run_id=run_id).one()
    assert approval.decided_by == API_PRINCIPAL  # not "forged@evil"


# --- rate limiting ---------------------------------------------------------


def test_rate_limit_blocks_after_window(monkeypatch, Session):
    monkeypatch.setenv("API_AUTH_TOKEN", "secret")
    monkeypatch.setenv("RATE_LIMIT_RUNS", "1")
    c, runner = _app(Session)
    auth = {"Authorization": "Bearer secret"}
    first = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}, headers=auth)
    assert first.status_code == 202
    runner.wait(first.json()["run_id"])
    second = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}, headers=auth)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


def test_rate_limit_disabled_when_zero(monkeypatch, Session):
    monkeypatch.setenv("RATE_LIMIT_RUNS", "0")
    c, runner = _app(Session)
    for _ in range(3):
        r = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE})
        assert r.status_code == 202
        runner.wait(r.json()["run_id"])


def test_fixed_window_limiter_allows_then_blocks_then_recovers():
    t = {"v": 1000.0}
    lim = FixedWindowLimiter(limit=2, window_s=10, clock=lambda: t["v"])
    assert lim.allow("k") is True
    assert lim.allow("k") is True
    assert lim.allow("k") is False  # at limit within the window
    t["v"] += 11  # window elapsed
    assert lim.allow("k") is True


def test_client_key_falls_back_to_anonymous():
    assert _client_key(SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))) == "1.2.3.4"
    assert _client_key(SimpleNamespace(client=None)) == "anonymous"


def test_rate_limit_keys_by_ip_for_shared_principal(monkeypatch, Session):
    """Shared static API_PRINCIPAL must not collapse all callers into one bucket.

    When the static token is in use every authenticated request looks like the
    same principal (``"api"``), so we must rate-limit by client IP instead."""
    from app.core.auth import API_PRINCIPAL
    from app.core.ratelimit import FixedWindowLimiter

    hit_keys: list[str] = []
    limiter = FixedWindowLimiter(limit=100, window_s=60)
    orig_allow = limiter.allow

    def spy_allow(key: str) -> bool:
        hit_keys.append(key)
        return orig_allow(key)

    limiter.allow = spy_allow

    req = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        app=SimpleNamespace(state=SimpleNamespace(rate_limiter=limiter)),
    )
    settings = SimpleNamespace(rate_limit_runs=100)
    rate_limit_runs.__wrapped__ if hasattr(rate_limit_runs, "__wrapped__") else None
    rate_limit_runs(req, principal=API_PRINCIPAL, settings=settings)  # type: ignore[call-arg]
    assert hit_keys == ["10.0.0.1"], "shared principal must key by IP, not by principal name"


def test_run_records_principal(monkeypatch, Session):
    """The initiating principal is persisted on the run row for future ownership checks."""
    from app.models import Run

    monkeypatch.setenv("API_AUTH_TOKEN", "secret")
    c, runner = _app(Session)
    auth = {"Authorization": "Bearer secret"}
    r = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}, headers=auth)
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    runner.wait(run_id)
    with Session() as s:
        run = s.get(Run, run_id)
    assert run is not None
    assert run.principal == API_PRINCIPAL


# --- ownership enforcement ---------------------------------------------------


def _app_with_principal(Session, principal: str | None):
    """Build a test app that always resolves require_principal to `principal`."""
    from app.core.auth import require_principal

    c, runner = _app(Session)
    c.app.dependency_overrides[require_principal] = lambda: principal
    return c, runner


def test_ownership_blocks_wrong_principal(Session):
    """Principal B cannot read or mutate a run owned by principal A."""
    c_a, runner = _app_with_principal(Session, "user-a")
    r = c_a.post("/api/v1/runs", json={"message": GOOD_MESSAGE})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    runner.wait(run_id)

    c_b, _ = _app_with_principal(Session, "user-b")
    assert c_b.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert c_b.get(f"/api/v1/runs/{run_id}/nodes").status_code == 404
    # approve/reject/retry all 404 (ownership) before the status check fires
    assert c_b.post(f"/api/v1/runs/{run_id}/approve").status_code == 404
    assert c_b.post(f"/api/v1/runs/{run_id}/reject").status_code == 404
    assert c_b.post(f"/api/v1/runs/{run_id}/retry").status_code == 404


def test_ownership_allows_correct_principal(Session):
    """Principal A can read their own run."""
    c, runner = _app_with_principal(Session, "user-a")
    r = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    runner.wait(run_id)
    assert c.get(f"/api/v1/runs/{run_id}").status_code == 200


def test_ownership_skipped_without_principal(Session):
    """With no principal (dev/open mode) every caller can access any run."""
    c_anon, runner = _app_with_principal(Session, None)
    r = c_anon.post("/api/v1/runs", json={"message": GOOD_MESSAGE})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    runner.wait(run_id)
    # Another anon client can still read the run
    c_other, _ = _app_with_principal(Session, None)
    assert c_other.get(f"/api/v1/runs/{run_id}").status_code == 200
