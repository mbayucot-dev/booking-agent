"""End-to-end workflow via WorkflowRunner: happy path with approval pause/resume,
rejection, invalid input, and availability escalation — booking into the local DB."""

from app.graph.availability_provider import FakeAvailabilityProvider
from app.graph.email import DryRunEmailSender
from app.models import Appointment, AuditLog, Client, Contact, CustomerMemory, Job
from app.persistence import replay_events
from app.services.run_service import WorkflowRunner
from tests.helpers import make_booking_executor, make_provider

GOOD_MESSAGE = (
    "Create a booking for John Doe for contact work on June 20 at 10am. "
    "Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."
)


def _runner(Session, email=None, provider=None):
    return WorkflowRunner(
        session_factory=Session,
        executor=make_booking_executor(Session),
        email_sender=email or DryRunEmailSender(),
        provider=provider if provider is not None else make_provider(Session),
    )


def _booking_counts(Session) -> tuple[int, int, int, int]:
    with Session() as s:
        return (
            s.query(Client).count(),
            s.query(Contact).count(),
            s.query(Job).count(),
            s.query(Appointment).count(),
        )


def test_happy_path_pauses_at_approval(Session):
    runner = _runner(Session)
    view = runner.start(GOOD_MESSAGE)

    assert view.status == "paused"
    assert view.approval_card["customer"] == "John Doe"
    assert len(view.approval_card["prepared_actions"]) == 4
    assert view.approval_card["staff"]  # a staff member was assigned
    assert _booking_counts(Session) == (0, 0, 0, 0)  # nothing booked pre-approval
    assert view.node_statuses["human_approval"] == "waiting_approval"


def test_approve_books_into_datastore(Session):
    email = DryRunEmailSender()
    runner = _runner(Session, email=email)
    started = runner.start(GOOD_MESSAGE)

    final = runner.resume(started.run_id, approved=True, by="ops@example.com")

    assert final.status == "completed"
    assert "confirmed" in final.final_response.lower()
    assert _booking_counts(Session) == (1, 1, 1, 1)  # client, contact, job, appointment
    assert len(email.sent) == 1
    with Session() as s:
        appt = s.query(Appointment).one()
        assert appt.staff_id is not None  # job assigned to a staff member
        assert s.query(AuditLog).count() == 4


def test_reject_books_nothing(Session):
    runner = _runner(Session)
    started = runner.start(GOOD_MESSAGE)
    final = runner.resume(started.run_id, approved=False, reason="outside area")
    assert final.status == "completed"
    assert "not approved" in final.final_response.lower()
    assert _booking_counts(Session) == (0, 0, 0, 0)


def test_invalid_request_short_circuits(Session):
    runner = _runner(Session)
    view = runner.start("please make a booking")
    assert view.status == "completed"
    assert "could not be processed" in view.final_response.lower()
    assert view.approval_card is None
    assert _booking_counts(Session) == (0, 0, 0, 0)


def test_no_availability_escalates(Session):
    runner = _runner(Session, provider=FakeAvailabilityProvider())  # nothing free
    view = runner.start(GOOD_MESSAGE)
    assert view.status == "escalated"  # distinct terminal state, not a success
    assert "escalated" in view.final_response.lower()
    assert view.approval_card is None


def test_approve_saves_customer_memory(Session):
    runner = _runner(Session)
    started = runner.start(GOOD_MESSAGE)
    runner.resume(started.run_id, approved=True)
    with Session() as s:
        types = {m.memory_type for m in s.query(CustomerMemory).all()}
    assert types == {"communication", "preference"}


def test_get_unknown_run_returns_none(Session):
    assert _runner(Session).get("does-not-exist") is None


def test_events_persisted_in_order(Session):
    runner = _runner(Session)
    view = runner.start(GOOD_MESSAGE)
    with Session() as s:
        events = replay_events(s, view.run_id)
    assert [e.id for e in events] == sorted(e.id for e in events)
    assert events[0].node == "chat_trigger"
