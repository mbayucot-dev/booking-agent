"""/api/v1/runs endpoints (async background execution + live SSE)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.v1 import api_router
from app.core.events import EventBus
from app.core.exceptions import register_exception_handlers
from app.graph.email import DryRunEmailSender
from app.models import Appointment, Client, Job
from app.services.booking_store import build_booking_executor
from app.services.run_service import WorkflowRunner
from tests.helpers import FailOnceExecutor, make_booking_executor, make_provider

GOOD_MESSAGE = (
    "Create a booking for John Doe for contact work on December 20, 2028 at 10am. "
    "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
)


@pytest.fixture()
def client(Session):
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
    return TestClient(app), runner, Session


def _start(c, runner) -> str:
    run_id = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}).json()["run_id"]
    runner.wait(run_id)
    return run_id


def test_start_is_accepted_then_pauses(client):
    c, runner, _ = client
    r = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE})
    assert r.status_code == 202
    assert r.json()["status"] == "running"
    run_id = r.json()["run_id"]

    runner.wait(run_id)
    view = c.get(f"/api/v1/runs/{run_id}").json()
    assert view["status"] == "paused"
    assert view["approval_card"]["customer"] == "John Doe"
    assert view["node_statuses"]["human_approval"] == "waiting_approval"


def test_full_approve_flow(client):
    c, runner, Session = client
    run_id = _start(c, runner)

    r = c.post(f"/api/v1/runs/{run_id}/approve", json={"by": "ops@example.com"})
    assert r.status_code == 202
    runner.wait(run_id)

    view = c.get(f"/api/v1/runs/{run_id}").json()
    assert view["status"] == "completed"
    assert "confirmed" in view["final_response"].lower()
    with Session() as s:
        assert s.query(Appointment).count() == 1  # booked into the datastore


def test_reject_flow(client):
    c, runner, Session = client
    run_id = _start(c, runner)
    c.post(f"/api/v1/runs/{run_id}/reject", json={"reason": "no"})
    runner.wait(run_id)
    assert c.get(f"/api/v1/runs/{run_id}").json()["status"] == "completed"
    with Session() as s:
        assert s.query(Client).count() == 0


def test_get_unknown_run_404(client):
    c, _, _ = client
    assert c.get("/api/v1/runs/nope").status_code == 404


def test_node_details_expose_per_node_output(client):
    c, runner, _ = client
    run_id = _start(c, runner)  # runs through to the approval pause
    rows = c.get(f"/api/v1/runs/{run_id}/nodes").json()
    by_node = {r["node"]: r for r in rows}
    # The extraction step's output carries the structured booking_request.
    extract = by_node["extract_booking_request"]
    assert extract["status"] == "success"
    assert extract["output"]["booking_request"]["customer_name"] == "John Doe"
    # The approval node is paused (waiting), surfaced with its card output.
    assert by_node["human_approval"]["status"] == "waiting_approval"
    # Every executed node is present; nodes that haven't run are excluded.
    assert "chat_trigger" in by_node and "validation_agent" in by_node
    assert "email_agent" not in by_node  # post-approval, not run yet
    # Full NodeDetail shape on each row.
    assert set(extract) == {"node", "status", "duration_ms", "tokens", "cost_usd", "output"}


def test_node_details_unknown_run_404(client):
    c, _, _ = client
    assert c.get("/api/v1/runs/nope/nodes").status_code == 404


def test_approve_unknown_run_404(client):
    c, _, _ = client
    assert c.post("/api/v1/runs/nope/approve").status_code == 404


def test_approve_after_completion_conflicts(client):
    c, runner, _ = client
    run_id = _start(c, runner)
    c.post(f"/api/v1/runs/{run_id}/approve")
    runner.wait(run_id)
    r = c.post(f"/api/v1/runs/{run_id}/approve")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_empty_message_422(client):
    c, _, _ = client
    assert c.post("/api/v1/runs", json={"message": ""}).status_code == 422


def test_over_length_message_422(client):
    # An unbounded paste must be rejected before it reaches the regexes / DB.
    from app.schemas.runs import _MAX_MESSAGE_CHARS

    c, _, _ = client
    oversized = "x" * (_MAX_MESSAGE_CHARS + 1)
    assert c.post("/api/v1/runs", json={"message": oversized}).status_code == 422


def test_sse_streams_the_node_timeline(client):
    # Wait for the run to reach the approval boundary, then stream — the SSE
    # replays the full persisted timeline and terminates. (The live blocking
    # path is covered deterministically by test_event_stream_blocking_path_*.)
    c, runner, _ = client
    run_id = _start(c, runner)
    r = c.get(f"/api/v1/runs/{run_id}/events")
    assert r.status_code == 200
    assert "human_approval" in r.text
    assert "event: end" in r.text
    # Anti-buffering headers so a reverse proxy doesn't hold the stream.
    assert r.headers.get("x-accel-buffering") == "no"
    assert "no-cache" in (r.headers.get("cache-control") or "")


def test_sse_unknown_run_404(client):
    c, _, _ = client
    assert c.get("/api/v1/runs/nope/events").status_code == 404


# --- retry ----------------------------------------------------------------


def test_retry_unknown_run_404(client):
    c, _, _ = client
    assert c.post("/api/v1/runs/nope/retry").status_code == 404


def test_retry_paused_run_conflicts(client):
    c, runner, _ = client
    run_id = _start(c, runner)  # paused, not failed
    r = c.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_retry_endpoint_recovers_a_failed_run(Session):
    runner = WorkflowRunner(
        session_factory=Session,
        executor=FailOnceExecutor(build_booking_executor(Session), "schedule_job"),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
        event_bus=EventBus(),
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[deps.get_runner] = lambda: runner
    app.include_router(api_router)
    c = TestClient(app)

    run_id = c.post("/api/v1/runs", json={"message": GOOD_MESSAGE}).json()["run_id"]
    runner.wait(run_id)
    c.post(f"/api/v1/runs/{run_id}/approve")  # fails mid-execution
    runner.wait(run_id)
    assert c.get(f"/api/v1/runs/{run_id}").json()["status"] == "failed"

    r = c.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 202
    runner.wait(run_id)
    view = c.get(f"/api/v1/runs/{run_id}").json()
    assert view["status"] == "completed"
    with Session() as s:
        assert s.query(Job).count() == 1  # ledger prevented a duplicate on retry
        assert s.query(Appointment).count() == 1


def test_event_stream_blocking_path_drains_live_events():
    import queue as _queue

    from app.api.v1.runs import event_stream
    from app.services.run_service import RunView

    q: _queue.Queue = _queue.Queue()
    q.put({"type": "event", "node": "extract_booking_request", "status": "running"})
    q.put({"type": "end", "status": "paused"})

    class FakeRunner:
        def subscribe(self, run_id):
            return q

        def unsubscribe(self, run_id, _q):
            pass

        def events(self, run_id):
            return []

        def get(self, run_id):
            return RunView(run_id=run_id, status="running")

    out = "".join(event_stream(FakeRunner(), "r1"))
    assert "extract_booking_request" in out
    assert "event: end" in out


def test_event_stream_emits_heartbeat_while_running_and_idle():
    import queue as _queue

    from app.api.v1.runs import event_stream
    from app.services.run_service import RunView

    class IdleThenEndQueue:
        """First live poll times out (idle) → heartbeat; second yields the end."""

        def __init__(self):
            self.calls = 0

        def get(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise _queue.Empty
            return {"type": "end"}

        def get_nowait(self):  # pragma: no cover - not used on the running path
            raise _queue.Empty

    class FakeRunner:
        def subscribe(self, run_id):
            return IdleThenEndQueue()

        def unsubscribe(self, run_id, _q):
            pass

        def events(self, run_id):
            return []

        def get(self, run_id):
            return RunView(run_id=run_id, status="running")  # not terminal → live wait

    out = "".join(event_stream(FakeRunner(), "r1"))
    assert ": keep-alive" in out  # idle heartbeat keeps the connection open
    assert "event: end" in out
