"""The checkpoint serializer must round-trip the domain models we store in graph
state — otherwise LangGraph logs 'unregistered type' and will block it in a
future version. This guards the msgpack allowlist in workflow.py."""

from app.graph.checkpointing import CHECKPOINT_SERDE
from app.graph.state import (
    ApprovalState,
    AvailabilityResult,
    BookingRequest,
    PreparedAction,
    Slot,
    ValidationResult,
)


def _roundtrip(value):
    return CHECKPOINT_SERDE.loads_typed(CHECKPOINT_SERDE.dumps_typed(value))


def test_serde_roundtrips_domain_models_preserving_types():
    state = {
        "booking_request": BookingRequest(customer_name="John Doe", service="contact work"),
        "validation": ValidationResult(ok=True),
        "availability": AvailabilityResult(
            available=True, chosen_slot=Slot(date="2026-06-20", time="10:00")
        ),
        "prepared_actions": [
            PreparedAction(action="create_job", payload={"a": 1}, idempotency_key="r:create_job")
        ],
        "approval": ApprovalState(status="approved"),
    }
    out = _roundtrip(state)

    assert isinstance(out["booking_request"], BookingRequest)
    assert out["booking_request"].customer_name == "John Doe"
    assert isinstance(out["validation"], ValidationResult)
    assert isinstance(out["availability"].chosen_slot, Slot)
    assert out["availability"].chosen_slot.time == "10:00"
    assert isinstance(out["prepared_actions"][0], PreparedAction)
    assert out["prepared_actions"][0].action == "create_job"
    assert isinstance(out["approval"], ApprovalState)


def test_serde_emits_no_unregistered_type_warning(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus"):
        _roundtrip(
            {
                "booking_request": BookingRequest(customer_name="John"),
                "prepared_actions": [PreparedAction(action="create_job")],
                "availability": AvailabilityResult(
                    available=True, chosen_slot=Slot(date="2026-06-20", time="10:00")
                ),
            }
        )
    noisy = [
        r
        for r in caplog.records
        if "nregistered" in r.getMessage() or "Deserializing" in r.getMessage()
    ]
    assert noisy == []  # the allow-list registers our types → no deprecation chatter
