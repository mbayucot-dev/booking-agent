"""Human approval gate: interrupt/pause, card contents, approve/reject resume,
and the guarantee that no mutation runs before approval."""

import pytest
from langgraph.types import Command

from app.graph import constants as C
from app.graph.approval_graph import build_approval_graph
from app.graph.instrumentation import InMemoryEventSink
from app.graph.nodes.human_approval import (
    APPROVED,
    REJECTED,
    WAITING_APPROVAL,
    RecordingExecutor,
    build_approval_card,
    make_execute_actions,
    prepare_payloads,
)
from app.graph.state import (
    ApprovalState,
    AvailabilityResult,
    BookingRequest,
    PreparedAction,
    Slot,
)

REQ = BookingRequest(
    customer_name="John Doe",
    service="contact work",
    date="2026-06-20",
    time="10:00",
    email="john@example.com",
    phone="0400000000",
    address="12 Queen St Brisbane",
)
SLOT = Slot(date="2026-06-20", time="10:00", staff_id="s1", staff_name="Alex Taylor")
AVAIL = AvailabilityResult(available=True, chosen_slot=SLOT)
STATE_IN = {"run_id": "r1", "booking_request": REQ, "availability": AVAIL}


def _interrupt_value(result):
    interrupts = result["__interrupt__"]
    return interrupts[0].value


# --- prepare_payloads: prepare only, never execute -----------------------


def test_prepare_payloads_prepares_known_mutating_actions_unexecuted():
    out = prepare_payloads(STATE_IN)
    actions = out["prepared_actions"]
    assert [a.action for a in actions] == [
        "create_client",
        "create_contact",
        "create_job",
        "schedule_job",
    ]
    assert all(isinstance(a, PreparedAction) for a in actions)
    assert all(not a.executed for a in actions)
    assert all(a.action in C.MUTATING_ACTIONS for a in actions)
    sched = next(a for a in actions if a.action == "schedule_job")
    assert sched.payload["staff"] == "Alex Taylor"


# --- approval card --------------------------------------------------------


def test_card_shows_all_required_fields():
    prepared = prepare_payloads(STATE_IN)["prepared_actions"]
    card = build_approval_card({**STATE_IN, "prepared_actions": prepared})
    for key in ("customer", "service", "date", "time", "staff", "email", "prepared_actions"):
        assert key in card
    assert card["customer"] == "John Doe"
    assert card["service"] == "contact work"
    assert card["date"] == "2026-06-20"
    assert card["time"] == "10:00"
    assert card["staff"] == "Alex Taylor"
    assert card["email"] == "john@example.com"
    assert len(card["prepared_actions"]) == 4


# --- interrupt: pause with no mutation -----------------------------------


def test_graph_pauses_at_approval_with_no_mutation():
    executor = RecordingExecutor()
    sink = InMemoryEventSink()
    graph = build_approval_graph(executor=executor, sink=sink)
    config = {"configurable": {"thread_id": "t-pause"}}

    result = graph.invoke(STATE_IN, config)

    # Paused at the interrupt, card surfaced.
    assert "__interrupt__" in result
    card = _interrupt_value(result)
    assert card["customer"] == "John Doe"
    assert len(card["prepared_actions"]) == 4

    # status pending -> waiting_approval surfaced, decision not yet made.
    assert WAITING_APPROVAL in sink.statuses(C.HUMAN_APPROVAL)
    assert APPROVED not in sink.statuses(C.HUMAN_APPROVAL)

    # No mutation node ran, nothing executed.
    assert executor.executed == []
    assert sink.by_node(C.EXECUTION) == []


# --- resume: approve then mutate -----------------------------------------


def test_resume_approved_executes_mutations_after_approval():
    executor = RecordingExecutor()
    sink = InMemoryEventSink()
    graph = build_approval_graph(executor=executor, sink=sink)
    config = {"configurable": {"thread_id": "t-approve"}}

    graph.invoke(STATE_IN, config)
    assert executor.executed == []  # still nothing before the decision

    result = graph.invoke(Command(resume={"approved": True, "by": "ops@example.com"}), config)

    approval = result["approval"]
    assert approval.status == APPROVED
    assert approval.decided_by == "ops@example.com"
    # Mutations executed only now, in order, and exactly the prepared ones.
    assert [a.action for a in executor.executed] == [
        "create_client",
        "create_contact",
        "create_job",
        "schedule_job",
    ]
    assert result["execution"]["executed"] == [a.action for a in executor.executed]
    assert APPROVED in sink.statuses(C.HUMAN_APPROVAL)


# --- resume: reject, no mutation -----------------------------------------


def test_resume_rejected_runs_no_mutation():
    executor = RecordingExecutor()
    sink = InMemoryEventSink()
    graph = build_approval_graph(executor=executor, sink=sink)
    config = {"configurable": {"thread_id": "t-reject"}}

    graph.invoke(STATE_IN, config)
    result = graph.invoke(
        Command(resume={"approved": False, "reason": "outside service area"}), config
    )

    approval = result["approval"]
    assert approval.status == REJECTED
    assert approval.reason == "outside service area"
    assert executor.executed == []  # never mutated
    assert result["execution"]["rejected"] is True
    assert REJECTED in sink.statuses(C.HUMAN_APPROVAL)


# --- defence in depth: execute node refuses without approval -------------


def test_execute_node_refuses_without_approval():
    node = make_execute_actions(RecordingExecutor(), InMemoryEventSink())
    with pytest.raises(RuntimeError):
        node({"run_id": "r", "approval": ApprovalState(status="pending")})


def test_prepare_payloads_requires_booking_request():
    with pytest.raises(ValueError):
        prepare_payloads({"run_id": "r"})
