"""Shared test helpers for the local booking datastore."""

from __future__ import annotations

from app.services.availability import DbAvailabilityProvider, seed_default_staff
from app.services.booking_store import BookingActionExecutor, BookingStore


def seed_staff(Session) -> None:
    seed_default_staff(Session)


def make_booking_executor(Session) -> BookingActionExecutor:
    """A real DB-backed booking executor, with staff seeded so jobs can be
    assigned."""
    seed_default_staff(Session)
    return BookingActionExecutor(backend=BookingStore(Session))


def make_provider(Session) -> DbAvailabilityProvider:
    seed_default_staff(Session)
    return DbAvailabilityProvider(session_factory=Session)


def seed_job(Session) -> str:
    """Create a real client + job (so appointment FKs resolve) and return job id."""
    store = BookingStore(Session)
    client = store.create_client(name="C", email="c@x.com", phone="1", address="z")
    job = store.create_job(client_uuid=client["uuid"], service="cleaning", address="z")
    return job["uuid"]


def first_staff_id(Session) -> str:
    from app.models import Staff

    with Session() as s:
        return s.query(Staff).first().id


class FailOnceExecutor:
    """Wraps a real executor and raises the FIRST time a given action runs, to
    simulate a transient mid-execution failure for retry tests."""

    def __init__(self, inner, fail_action: str):
        self.inner = inner
        self.fail_action = fail_action
        self.tripped = False

    def execute(self, action):
        if action.action == self.fail_action and not self.tripped:
            self.tripped = True
            raise RuntimeError("transient failure")
        return self.inner.execute(action)
