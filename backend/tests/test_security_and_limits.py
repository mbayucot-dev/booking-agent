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
from app.core.ratelimit import FixedWindowLimiter, _client_key
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
