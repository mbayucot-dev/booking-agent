"""Runner wiring (build_default_runner) and node branch coverage."""

import time
from concurrent.futures import Future

from app.graph.email import DryRunEmailSender
from app.graph.nodes.final_response import final_response
from app.graph.nodes.risk_review_agent import risk_review_agent
from app.models import Appointment, Job
from app.services.booking_store import build_booking_executor
from app.services.run_service import WorkflowRunner, build_default_runner
from tests.helpers import FailOnceExecutor, make_booking_executor, make_provider

GOOD_MESSAGE = (
    "Create a booking for John Doe for contact work on June 20 at 10am. "
    "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
)


def _runner(Session) -> WorkflowRunner:
    return WorkflowRunner(
        session_factory=Session,
        executor=make_booking_executor(Session),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
    )


def test_build_default_runner_dry_run(Session, monkeypatch):
    for var in ("SMTP_HOST", "MAIL_FROM"):
        monkeypatch.delenv(var, raising=False)
    runner = build_default_runner(Session)
    assert isinstance(runner, WorkflowRunner)


def test_build_default_runner_with_smtp(Session, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("MAIL_FROM", "bookings@example")
    runner = build_default_runner(Session)
    assert isinstance(runner, WorkflowRunner)


def test_final_response_fallback():
    assert final_response({})["final_response"] == "Workflow complete."


def test_risk_flags_out_of_hours_and_no_staff():
    out = risk_review_agent({"job_plan": {"time": "20:00", "staff": None}})
    assert set(out["risk"]["flags"]) == {"out_of_hours", "no_staff_assigned"}
    assert out["risk"]["score"] == 2
    assert out["risk"]["requires_approval"] is True


def test_double_resume_books_once_and_guards_status(Session):
    runner = _runner(Session)
    started = runner.start(GOOD_MESSAGE)
    first = runner.resume(started.run_id, approved=True)
    assert first.status == "completed"
    # Second resume must NOT re-invoke the graph (status is no longer paused).
    second = runner.resume(started.run_id, approved=True)
    assert second.status == "completed"
    with Session() as s:
        assert s.query(Appointment).count() == 1  # not double-booked


def test_wait_swallows_a_failed_future(Session):
    runner = _runner(Session)
    failed: Future = Future()
    failed.set_exception(RuntimeError("worker boom"))
    runner._futures["r-x"] = failed
    runner.wait("r-x")  # the worker's error is logged elsewhere; wait must not raise


def test_retry_resumes_failed_run_without_double_booking(Session):
    # Executor fails the first time it reaches schedule_job → the run fails AFTER
    # client/contact/job are committed (and recorded in the idempotency ledger).
    runner = WorkflowRunner(
        session_factory=Session,
        executor=FailOnceExecutor(build_booking_executor(Session), "schedule_job"),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
    )
    started = runner.start(GOOD_MESSAGE)
    runner.submit_resume(started.run_id, approved=True)  # background so failure → "failed"
    runner.wait(started.run_id)
    assert runner.get(started.run_id).status == "failed"
    with Session() as s:
        assert s.query(Job).count() == 1
        assert s.query(Appointment).count() == 0  # failed before scheduling

    # Retry resumes from the checkpoint; the ledger dedupes the already-created
    # job, and schedule_job now succeeds.
    runner.submit_retry(started.run_id)
    runner.wait(started.run_id)
    assert runner.get(started.run_id).status == "completed"
    with Session() as s:
        assert s.query(Job).count() == 1  # NOT a second job
        assert s.query(Appointment).count() == 1


def test_graph_invocation_timeout_marks_run_failed(Session):
    # A wedged node must not pin the request: the overall budget abandons the
    # invocation and surfaces a clean 'failed' instead of blocking forever.
    runner = WorkflowRunner(
        session_factory=Session,
        executor=make_booking_executor(Session),
        email_sender=DryRunEmailSender(),
        provider=make_provider(Session),
        graph_timeout_s=0.05,
    )

    def _wedged(*_args, **_kwargs):
        time.sleep(5)  # longer than the 0.05s budget

    runner._graph.invoke = _wedged
    view = runner.start(GOOD_MESSAGE)
    assert view.status == "failed"
    assert runner.get(view.run_id).status == "failed"


def test_retry_noops_when_run_not_failed(Session):
    runner = _runner(Session)
    started = runner.start(GOOD_MESSAGE)  # paused, not failed
    view = runner.retry(started.run_id)
    assert view.status == "paused"  # guard: a non-failed run is not resumed


def test_node_details_wraps_non_dict_output(Session):
    from app.persistence import create_run
    from app.repositories.run import RunRepository

    runner = _runner(Session)
    with Session() as s:
        create_run(s, run_id="rx", raw_message="m")
        RunRepository(s).add_event(run_id="rx", node="weird", status="success", output=["a", "b"])
    details = {d["node"]: d for d in runner.node_details("rx")}
    # A non-dict output is wrapped so it satisfies the NodeDetail dict|None shape.
    assert details["weird"]["output"] == {"value": ["a", "b"]}
