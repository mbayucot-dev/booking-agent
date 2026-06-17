"""final_response — composes the user-facing closing message for every branch
(invalid input, escalation, rejection, or a confirmed booking)."""

from __future__ import annotations

from ..state import BookingState


def final_response(state: BookingState) -> BookingState:
    validation = state.get("validation")
    availability = state.get("availability")
    approval = state.get("approval")
    req = state.get("booking_request")

    if validation is not None and not validation.ok:
        msg = "Booking could not be processed: " + "; ".join(validation.errors)
    elif availability is not None and availability.escalate:
        msg = (
            "We couldn't find availability within the search window; "
            "your request has been escalated to our team."
        )
    elif approval is not None and approval.status == "rejected":
        reason = f" ({approval.reason})" if approval.reason else ""
        msg = f"Your booking was not approved{reason}."
    elif state.get("execution"):
        slot = availability.chosen_slot if availability else None
        name = req.customer_name if req else "you"
        when = f" on {slot.date} at {slot.time}" if slot else ""
        msg = f"Booking confirmed for {name}{when}. A confirmation email is on its way."
    else:
        msg = "Workflow complete."

    return {"final_response": msg}
