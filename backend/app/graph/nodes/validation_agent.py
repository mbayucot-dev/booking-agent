"""validation_agent node.

Deterministic, rule-based validation of the extracted :class:`BookingRequest`.
This is intentionally *not* an LLM call — booking validity is a hard business
rule, so we keep it auditable and reproducible.

Produces a :class:`ValidationResult` listing every problem found (not just the
first), so the UI can show the user everything at once.
"""

from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser

from ..state import BookingRequest, BookingState, ValidationResult

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


def _validate(req: BookingRequest, *, today: date | None = None) -> ValidationResult:
    today = today or date.today()
    errors: list[str] = []

    if not req.customer_name:
        errors.append("customer_name is required")
    if not req.service:
        errors.append("service is required")

    if not req.email:
        errors.append("email is required")
    elif not EMAIL_RE.match(req.email):
        errors.append(f"email '{req.email}' is not a valid address")

    if not req.phone:
        errors.append("phone is required")
    elif len(re.sub(r"\D", "", req.phone)) < 8:
        errors.append("phone must have at least 8 digits")

    if not req.address:
        errors.append("address is required")

    if not req.time:
        errors.append("time is required")

    if not req.date:
        errors.append("date is required")
    else:
        try:
            parsed = dateparser.parse(req.date).date()
            if parsed < today:
                errors.append(f"date {req.date} is in the past")
        except (ValueError, OverflowError, TypeError):
            errors.append(f"date '{req.date}' could not be parsed")

    return ValidationResult(ok=not errors, errors=errors)


def validation_agent(state: BookingState) -> BookingState:
    req = state.get("booking_request")
    if req is None:
        return {"validation": ValidationResult(ok=False, errors=["no booking_request to validate"])}
    return {"validation": _validate(req)}
