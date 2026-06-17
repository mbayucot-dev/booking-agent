"""Validation agent rules."""

from datetime import date

from app.graph.nodes.validation_agent import _validate, validation_agent
from app.graph.state import BookingRequest

TODAY = date(2026, 6, 13)


def _valid_request(**overrides) -> BookingRequest:
    base = dict(
        customer_name="John Doe",
        service="contact work",
        date="2026-06-20",
        time="10:00",
        email="john@example.com",
        phone="0400000000",
        address="12 Queen St Brisbane",
    )
    base.update(overrides)
    return BookingRequest(**base)


def test_complete_request_is_valid():
    result = _validate(_valid_request(), today=TODAY)
    assert result.ok is True
    assert result.errors == []


def test_missing_fields_collected():
    result = _validate(BookingRequest(), today=TODAY)
    assert result.ok is False
    # all 7 required fields flagged
    assert len(result.errors) == 7


def test_invalid_email_flagged():
    result = _validate(_valid_request(email="not-an-email"), today=TODAY)
    assert result.ok is False
    assert any("email" in e for e in result.errors)


def test_past_date_flagged():
    result = _validate(_valid_request(date="2020-01-01"), today=TODAY)
    assert result.ok is False
    assert any("past" in e for e in result.errors)


def test_short_phone_flagged():
    result = _validate(_valid_request(phone="123"), today=TODAY)
    assert any("phone" in e for e in result.errors)


def test_unparseable_date_flagged():
    result = _validate(_valid_request(date="bananas"), today=TODAY)
    assert result.ok is False
    assert any("could not be parsed" in e for e in result.errors)


def test_node_handles_missing_booking_request():
    out = validation_agent({})
    assert out["validation"].ok is False
    assert "no booking_request" in out["validation"].errors[0]
