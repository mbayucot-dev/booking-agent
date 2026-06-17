"""email_agent node: sends via the seam, skips when there's no recipient, and
picks the booking reference from the create_job result."""

from app.graph import constants as C
from app.graph.email import DryRunEmailSender
from app.graph.instrumentation import InMemoryEventSink
from app.graph.nodes.email_agent import make_email_agent
from app.graph.state import AvailabilityResult, BookingRequest, Slot

REQ = BookingRequest(
    customer_name="John Doe",
    service="contact work",
    date="2026-06-20",
    time="10:00",
    email="john@example.com",
    address="12 Queen St Brisbane",
)
AVAIL = AvailabilityResult(
    available=True,
    chosen_slot=Slot(date="2026-06-20", time="10:00", staff_name="Alex Taylor"),
)
EXECUTION = {
    "executed": ["create_client", "create_job", "schedule_job"],
    "results": [{"uuid": "rec-0001"}, {"uuid": "rec-0003"}, {"uuid": "rec-0004"}],
}


def test_node_sends_confirmation_with_html_and_ics():
    sender = DryRunEmailSender()
    sink = InMemoryEventSink()
    node = make_email_agent(sender, sink, business_name="Acme")
    out = node(
        {"run_id": "r1", "booking_request": REQ, "availability": AVAIL, "execution": EXECUTION}
    )["email"]

    assert out == {"sent": True, "to": "john@example.com", "id": None, "provider": "dry-run"}
    assert len(sender.sent) == 1
    msg = sender.sent[0]
    assert msg.to == "john@example.com"
    assert msg.html and "Acme" in msg.html
    assert msg.ics and "BEGIN:VEVENT" in msg.ics
    # reference picked from the create_job result uuid.
    assert "rec-0003" in msg.html
    # node was instrumented.
    assert C.EMAIL in {e.node for e in sink.events}


def test_node_skips_without_recipient_and_never_sends():
    sender = DryRunEmailSender()
    node = make_email_agent(sender)
    no_email = BookingRequest(customer_name="J", service="x")
    out = node({"run_id": "r1", "booking_request": no_email})["email"]
    assert out == {"sent": False, "skipped": "no recipient"}
    assert sender.sent == []

    # Also skips when booking_request is missing entirely.
    out2 = node({"run_id": "r1"})["email"]
    assert out2["sent"] is False
    assert sender.sent == []


def test_node_falls_back_to_request_schedule_without_slot_or_job():
    sender = DryRunEmailSender()
    node = make_email_agent(sender)
    out = node({"run_id": "r1", "booking_request": REQ})["email"]
    assert out["sent"] is True
    msg = sender.sent[0]
    # date/time come from the request when no chosen_slot.
    assert "2026-06-20" in msg.html
    # no create_job result -> no reference row.
    assert "Reference" not in msg.html
