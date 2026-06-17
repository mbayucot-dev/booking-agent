"""Regression tests for the approval gate's safety guarantees:
1. approval fails closed on ambiguous/forged resume payloads;
2. execution is idempotent — a retry cannot duplicate a booking.

Driven through the real DB-backed booking executor."""

from langgraph.types import Command

from app.graph.approval_graph import build_approval_graph
from app.graph.instrumentation import InMemoryEventSink
from app.graph.nodes.human_approval import (
    APPROVED,
    REJECTED,
    make_execute_actions,
    prepare_payloads,
)
from app.graph.state import ApprovalState, AvailabilityResult, BookingRequest, Slot
from app.models import Client
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
STATE_IN = {"run_id": "r1", "booking_request": REQ, "availability": AVAIL}


def _clients(Session) -> int:
    with Session() as s:
        return s.query(Client).count()


# --- fail-closed approval -------------------------------------------------


def test_bare_truthy_resume_does_not_approve(Session):
    graph = build_approval_graph(executor=make_booking_executor(Session))
    config = {"configurable": {"thread_id": "fc-truthy"}}
    graph.invoke(STATE_IN, config)
    result = graph.invoke(Command(resume="yes please"), config)
    assert result["approval"].status == REJECTED
    assert _clients(Session) == 0


def test_dict_without_approved_true_is_rejected(Session):
    graph = build_approval_graph(executor=make_booking_executor(Session))
    config = {"configurable": {"thread_id": "fc-missing"}}
    graph.invoke(STATE_IN, config)
    result = graph.invoke(Command(resume={"approve": "yep"}), config)
    assert result["approval"].status == REJECTED
    assert _clients(Session) == 0


def test_explicit_true_still_approves(Session):
    graph = build_approval_graph(executor=make_booking_executor(Session))
    config = {"configurable": {"thread_id": "fc-true"}}
    graph.invoke(STATE_IN, config)
    result = graph.invoke(Command(resume={"approved": True}), config)
    assert result["approval"].status == APPROVED
    assert _clients(Session) == 1


# --- idempotent execution -------------------------------------------------


def test_executor_dedups_repeated_action(Session):
    executor = make_booking_executor(Session)
    actions = prepare_payloads(STATE_IN)["prepared_actions"]
    first = [executor.execute(a) for a in actions]
    second = [executor.execute(a) for a in actions]  # replay
    assert _clients(Session) == 1  # not 2
    assert first == second


def test_execute_actions_node_is_idempotent_on_reentry(Session):
    node = make_execute_actions(make_booking_executor(Session), sink=InMemoryEventSink())
    prepared = prepare_payloads(STATE_IN)["prepared_actions"]
    approval = ApprovalState(status=APPROVED, prepared_actions=prepared)

    out1 = node({"run_id": "r1", "approval": approval})
    out2 = node({"run_id": "r1", "approval": approval, "execution": out1["execution"]})

    assert _clients(Session) == 1  # second pass booked nothing new
    assert out2["execution"]["executed_keys"] == out1["execution"]["executed_keys"]
