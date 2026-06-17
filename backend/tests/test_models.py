"""run_events / runs persistence and schema."""

from app.models import NodeStatus, Run, RunEvent, RunStatus


def test_run_and_event_roundtrip(db_session):
    run = Run(raw_message="hello", status=RunStatus.running.value)
    db_session.add(run)
    db_session.flush()  # assigns run.id

    event = RunEvent(
        run_id=run.id,
        node="extract_booking_request",
        status=NodeStatus.success.value,
        input={"raw_message": "hello"},
        output={"booking_request": {"customer_name": "John Doe"}},
        duration_ms=12,
        tokens=0,
        cost_usd=0.0,
    )
    db_session.add(event)
    db_session.commit()

    fetched = db_session.get(Run, run.id)
    assert fetched is not None
    assert len(fetched.events) == 1
    ev = fetched.events[0]
    assert ev.node == "extract_booking_request"
    assert ev.status == "success"
    assert ev.output["booking_request"]["customer_name"] == "John Doe"


def test_node_status_values_match_react_flow_contract():
    # The 8 statuses the React Flow canvas renders, kept in lockstep.
    assert {s.value for s in NodeStatus} == {
        "idle",
        "running",
        "success",
        "failed",
        "waiting_approval",
        "approved",
        "rejected",
        "skipped",
    }


def test_cascade_delete_removes_events(db_session):
    run = Run(raw_message="x")
    run.events.append(RunEvent(node="chat_trigger", status="success"))
    db_session.add(run)
    db_session.commit()
    assert db_session.query(RunEvent).count() == 1

    db_session.delete(run)
    db_session.commit()
    assert db_session.query(RunEvent).count() == 0
