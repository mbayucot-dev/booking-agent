"""Property-based tests using Hypothesis.

These tests verify invariants that unit tests with hand-crafted inputs often
miss — malformed strings, unicode edge cases, off-by-one dates, extreme phone
formats, and arbitrary message inputs that should never crash the parser.

Run: pytest tests/test_property.py -x
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.ratelimit import FixedWindowLimiter
from app.graph.nodes.extract_booking_request import (
    _extract_with_rules,
    _normalize_date,
)
from app.graph.nodes.validation_agent import EMAIL_RE, _validate
from app.graph.state import BookingRequest

# ---------------------------------------------------------------------------
# Validation agent: deterministic business rules
# ---------------------------------------------------------------------------


def _valid_future_request(**overrides) -> BookingRequest:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    defaults = dict(
        customer_name="Jane Doe",
        service="cleaning",
        email="jane@example.com",
        phone="0400000000",
        address="12 Main St",
        time="09:00",
        date=tomorrow,
    )
    return BookingRequest(**{**defaults, **overrides})


@given(st.dates(min_value=date(2000, 1, 1), max_value=date.today() - timedelta(days=1)))
def test_past_date_always_rejected(past_date):
    """Any date strictly before today must produce a validation error."""
    req = _valid_future_request(date=past_date.isoformat())
    result = _validate(req, today=date.today())
    assert not result.ok
    assert any("past" in e for e in result.errors), result.errors


@given(st.dates(min_value=date.today() + timedelta(days=1), max_value=date(2099, 12, 31)))
def test_future_date_never_rejected_for_being_past(future_date):
    """A date in the future must never be rejected solely for being in the past."""
    req = _valid_future_request(date=future_date.isoformat())
    result = _validate(req, today=date.today())
    assert not any("past" in e for e in result.errors), (
        f"Future date {future_date} incorrectly rejected as past: {result.errors}"
    )


@given(
    st.text(
        alphabet=st.characters(
            blacklist_categories=("Cs",),  # exclude surrogates
            min_codepoint=0x20,
        ),
        max_size=20,
    )
)
def test_email_regex_never_crashes(candidate: str):
    """EMAIL_RE.match must not throw on any string input."""
    try:
        EMAIL_RE.match(candidate)
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"EMAIL_RE.match raised {exc!r} on input {candidate!r}")


@given(
    st.integers(min_value=0, max_value=7),
    st.integers(min_value=0, max_value=100),
)
def test_phone_digit_rule(valid_digits: int, prefix_digits: int):
    """Phones with < 8 digits fail; 8+ digits pass the digit count check."""
    digits = "0" * valid_digits
    # Pad with some non-digit prefix so re.sub(r"\D", ...) strips it correctly.
    phone = f"+{prefix_digits:03d}-{digits}"
    req = _valid_future_request(phone=phone)
    result = _validate(req, today=date.today())
    digit_count = len([c for c in phone if c.isdigit()])
    if digit_count < 8:
        assert any("phone" in e for e in result.errors), (
            f"Expected phone error for {phone!r} ({digit_count} digits), got: {result.errors}"
        )
    else:
        assert not any("phone" in e for e in result.errors), (
            f"Unexpected phone error for {phone!r} ({digit_count} digits): {result.errors}"
        )


# ---------------------------------------------------------------------------
# Extraction helpers: must not raise on arbitrary input
# ---------------------------------------------------------------------------


@given(st.text(max_size=500))
@settings(max_examples=200)
def test_extract_with_rules_never_crashes(message: str):
    """The rule-based extractor must never raise an exception for any input."""
    _extract_with_rules(message)


@given(st.text(max_size=200))
def test_normalize_date_returns_iso_or_none(text: str):
    """_normalize_date returns either a valid ISO date string or None, never raises."""
    result = _normalize_date(text)
    if result is not None:
        # Must be parseable as an ISO date.
        try:
            date.fromisoformat(result)
        except ValueError as exc:  # pragma: no cover
            pytest.fail(f"_normalize_date returned non-ISO {result!r} for {text!r}: {exc}")


# ---------------------------------------------------------------------------
# Rate limiter: limit is always honoured
# ---------------------------------------------------------------------------


@given(
    limit=st.integers(min_value=1, max_value=20),
    extra=st.integers(min_value=0, max_value=10),
)
def test_fixed_window_limiter_never_exceeds_limit(limit: int, extra: int):
    """FixedWindowLimiter must allow exactly `limit` hits and block all beyond."""
    lim = FixedWindowLimiter(limit=limit, window_s=60)
    allowed = sum(1 for _ in range(limit + extra) if lim.allow("key"))
    assert allowed == limit, (
        f"Expected {limit} allowed, got {allowed} (extra={extra})"
    )


@given(
    limit=st.integers(min_value=1, max_value=10),
    keys=st.lists(st.text(min_size=1, max_size=8), min_size=2, max_size=5, unique=True),
)
def test_fixed_window_limiter_isolates_keys(limit: int, keys: list[str]):
    """Each key gets its own independent bucket."""
    lim = FixedWindowLimiter(limit=limit, window_s=60)
    for key in keys:
        for _ in range(limit):
            assert lim.allow(key), f"Key {key!r} blocked before reaching limit"
        assert not lim.allow(key), f"Key {key!r} should be blocked at limit"


# ---------------------------------------------------------------------------
# Sanitisation: max_message_chars cap from config
# ---------------------------------------------------------------------------


@given(st.text(max_size=10_000))
def test_extract_with_rules_returns_booking_request(message: str):
    """The extractor always returns a BookingRequest, never raises, never returns None."""
    result = _extract_with_rules(message)
    assert result is not None
    assert isinstance(result, BookingRequest)
