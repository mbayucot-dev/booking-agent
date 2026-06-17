"""email_agent node — sends the booking confirmation email.

Runs after execution on the approved path, so the job exists and the email can
quote its reference. Sends through the injected :class:`EmailSender` seam
(DryRun in dev/tests, SMTP in prod).
"""

from __future__ import annotations

from ...services.email_template import (
    BookingEmailContext,
    build_ics,
    render_confirmation,
)
from .. import constants as C
from ..email import EmailMessage, EmailSender
from ..instrumentation import EventSink, NullEventSink, instrument
from ..state import BookingState


def _job_reference(execution: dict) -> str | None:
    """The create_job result UUID, if the mutation ran — used as the booking ref."""
    executed = execution.get("executed", [])
    results = execution.get("results", [])
    for action, result in zip(executed, results, strict=False):
        if action == "create_job" and result:
            return result.get("uuid")
    return None


def make_email_agent(
    sender: EmailSender,
    sink: EventSink | None = None,
    *,
    business_name: str = "Your Service Team",
    tz: str = "Australia/Brisbane",
    duration_min: int = 60,
):
    sink = sink or NullEventSink()

    def email_agent(state: BookingState) -> BookingState:
        req = state.get("booking_request")
        if req is None or not req.email:
            # Nothing to send to — skip without invoking the sender.
            return {"email": {"sent": False, "skipped": "no recipient"}}

        avail = state.get("availability")
        slot = avail.chosen_slot if avail and avail.chosen_slot else None
        date = slot.date if slot else req.date
        time = slot.time if slot else req.time
        staff = slot.staff_name if slot else None

        execution = state.get("execution") or {}
        ctx = BookingEmailContext(
            customer_name=req.customer_name,
            service=req.service,
            date=date,
            time=time,
            staff=staff,
            address=req.address,
            email=req.email,
            reference=_job_reference(execution),
            business_name=business_name,
            tz=tz,
            duration_min=duration_min,
        )
        rendered = render_confirmation(ctx)
        message = EmailMessage(
            to=req.email,
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            ics=build_ics(ctx),
        )
        result = sender.send(message)
        return {
            "email": {
                "sent": True,
                "to": req.email,
                "id": result.get("id"),
                "provider": result.get("provider"),
            }
        }

    return instrument(C.EMAIL, email_agent, sink)
