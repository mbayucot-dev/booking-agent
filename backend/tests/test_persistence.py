"""Persistence layer: run_events replay and audit_logs.

Runs the approval graph with the DB-backed sink + audit writer + booking
executor, then asserts the trail is durable and replayable."""

from langgraph.types import Command

from app.graph import constants as C
from app.graph.approval_graph import build_approval_graph
from app.graph.state import AvailabilityResult, BookingRequest, Slot
from app.models import AuditLog, Client, Run
from app.persistence import (
    DbAuditWriter,
    DbEventSink,
    create_run,
    node_status_map,
    record_approval,
    replay_events,
    set_run_status,
)
from tests.helpers import make_booking_executor

REQ = BookingRequest(
    customer_name="John Doe",
    service="contact work",
    date="2026-06-20",
    time="10:00",
    email="john@example.com",
    phone="0400000000",
    address="12 Queen St Brisbane",
)
AVAIL = AvailabilityResult(
    available=True,
    chosen_slot=Slot(date="2026-06-20", time="10:00"),
)
BOOKING_ACTIONS = {"create_client", "create_contact", "create_job", "schedule_job"}


def _run_approved(Session, run_id="r1"):
    graph = build_approval_graph(
        executor=make_booking_executor(Session),
        sink=DbEventSink(Session),
        audit_writer=DbAuditWriter(Session),
    )
    config = {"configurable": {"thread_id": run_id}}
    state_in = {"run_id": run_id, "booking_request": REQ, "availability": AVAIL}
    graph.invoke(state_in, config)  # pause at approval
    return graph.invoke(Command(resume={"approved": True, "by": "ops@x.com"}), config)


# --- replayability (S4) ---------------------------------------------------


def test_run_events_persisted_and_replayable(Session):
    with Session() as s:
        create_run(s, run_id="r1", raw_message="book it")
    _run_approved(Session)

    with Session() as s:
        events = replay_events(s, "r1")
        nodes = [e.node for e in events]
        assert C.PREPARE_PAYLOADS in nodes
        assert C.HUMAN_APPROVAL in nodes
        assert C.EXECUTION in nodes
        assert C.AUDIT_LOG in nodes
        assert [e.id for e in events] == sorted(e.id for e in events)

        statuses = node_status_map(s, "r1")
        assert statuses[C.HUMAN_APPROVAL] == "approved"
        assert statuses[C.EXECUTION] == "success"
        assert any(e.node == C.HUMAN_APPROVAL and e.status == "waiting_approval" for e in events)


def test_event_rows_carry_duration(Session):
    with Session() as s:
        create_run(s, run_id="r1")
    _run_approved(Session)
    with Session() as s:
        successes = [e for e in replay_events(s, "r1") if e.status == "success"]
        assert successes
        assert all(e.duration_ms is not None for e in successes)


# --- auditability (S3) ----------------------------------------------------


def test_audit_logs_written_per_mutation(Session):
    with Session() as s:
        create_run(s, run_id="r1")
    _run_approved(Session)
    with Session() as s:
        logs = s.query(AuditLog).all()
        assert len(logs) == 4  # one per booking mutation (no email)
        assert {log.action for log in logs} == BOOKING_ACTIONS
        assert all(log.actor == "ops@x.com" for log in logs)
        assert all(log.target_id for log in logs)


def test_no_audit_logs_on_rejection(Session):
    with Session() as s:
        create_run(s, run_id="rej")
    graph = build_approval_graph(
        executor=make_booking_executor(Session),
        sink=DbEventSink(Session),
        audit_writer=DbAuditWriter(Session),
    )
    config = {"configurable": {"thread_id": "rej"}}
    state_in = {"run_id": "rej", "booking_request": REQ, "availability": AVAIL}
    graph.invoke(state_in, config)
    graph.invoke(Command(resume={"approved": False}), config)

    with Session() as s:
        assert s.query(AuditLog).count() == 0
        assert s.query(Client).count() == 0


def test_set_run_status_updates_and_noops_on_missing(Session):
    with Session() as s:
        create_run(s, run_id="r1", raw_message="x")
        set_run_status(s, "r1", "completed", final_response="done")
        run = s.get(Run, "r1")
        assert run.status == "completed"
        assert run.final_response == "done"
        set_run_status(s, "does-not-exist", "failed")  # safe no-op


def test_record_approval_persists_decision(Session):
    from app.graph.nodes.human_approval import prepare_payloads
    from app.graph.state import ApprovalState

    with Session() as s:
        create_run(s, run_id="r1")
    prepared = prepare_payloads({"run_id": "r1", "booking_request": REQ, "availability": AVAIL})[
        "prepared_actions"
    ]
    approval = ApprovalState(status="approved", prepared_actions=prepared, decided_by="ops@x.com")
    with Session() as s:
        row = record_approval(s, "r1", approval)
        assert row.status == "approved"
        assert row.decided_by == "ops@x.com"
        assert row.decided_at is not None
        assert len(row.prepared_payloads) == 4


def test_audit_log_node_writes_via_in_memory_writer():
    from app.graph.audit import InMemoryAuditWriter
    from app.graph.nodes.audit_log import make_audit_log
    from app.graph.state import ApprovalState

    writer = InMemoryAuditWriter()
    node = make_audit_log(writer)
    state = {
        "run_id": "r1",
        "approval": ApprovalState(status="approved", decided_by="ops@x.com"),
        "execution": {
            "executed": ["create_client", "schedule_job"],
            "results": [{"uuid": "client-1"}, {"uuid": "sched-1"}],
        },
    }
    out = node(state)
    assert out["audit"]["written"] == 2
    assert writer.entries[0]["actor"] == "ops@x.com"
    assert writer.entries[0]["target_id"] == "client-1"
