"""Deterministic rule-based extraction."""

from app.graph.nodes.extract_booking_request import (
    _extract_with_rules,
    extract_booking_request,
)


def test_extracts_all_fields_from_example(example_message):
    req = _extract_with_rules(example_message)
    assert req.customer_name == "John Doe"
    assert req.service == "contact work"
    assert req.date == "2028-12-20"
    assert req.time == "10:00"
    assert req.email == "john@example.com"
    assert req.phone == "0400000000"
    assert req.address == "12 Queen St Brisbane"


def test_node_returns_booking_request_in_state(example_message):
    out = extract_booking_request({"raw_message": example_message})
    assert "booking_request" in out
    assert out["booking_request"].email == "john@example.com"


def test_pm_time_normalised():
    req = _extract_with_rules(
        "Booking for Jane Roe for plumbing on July 1 at 2:30pm. "
        "Email jane@x.com, phone 0411111111, address 5 King St."
    )
    assert req.time == "14:30"


def test_missing_fields_are_none():
    req = _extract_with_rules("just some text with no booking details")
    assert req.email is None
    assert req.customer_name is None
    assert req.date is None
