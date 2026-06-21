"""Local booking datastore: store, executor (id threading + dedup), availability."""

import threading
from datetime import datetime

import pytest

from app.core.exceptions import SlotTakenError
from app.graph.state import PreparedAction, Slot
from app.models import Appointment, Client, Contact, ExecutedAction, Job, Staff
from app.repositories.booking import BookingRepository, IdempotencyRepository
from app.services.availability import DbAvailabilityProvider, seed_default_staff
from app.services.booking_store import BookingActionExecutor, BookingStore, DbIdempotencyStore
from tests.helpers import make_booking_executor, make_provider, seed_job

REQ_DATE = "2026-06-20"


def _prepared(staff_id=None):
    return [
        PreparedAction(
            action="create_client",
            payload={"name": "A", "email": "a@x", "phone": "1", "address": "z"},
            idempotency_key="r:create_client",
        ),
        PreparedAction(
            action="create_contact",
            payload={"name": "A", "email": "a@x", "phone": "1"},
            idempotency_key="r:create_contact",
        ),
        PreparedAction(
            action="create_job",
            payload={"service": "fix", "address": "z"},
            idempotency_key="r:create_job",
        ),
        PreparedAction(
            action="schedule_job",
            payload={"date": REQ_DATE, "time": "10:00", "staff": "Alex", "staff_id": staff_id},
            idempotency_key="r:schedule_job",
        ),
    ]


def test_executor_threads_ids_and_writes_rows(Session):
    executor = BookingActionExecutor(backend=BookingStore(Session))
    for a in _prepared():
        executor.execute(a)
    with Session() as s:
        client = s.query(Client).one()
        contact = s.query(Contact).one()
        job = s.query(Job).one()
        appt = s.query(Appointment).one()
    assert contact.client_id == client.id  # threaded
    assert job.client_id == client.id
    assert appt.job_id == job.id
    assert appt.start_date == datetime.fromisoformat(f"{REQ_DATE} 10:00:00")


def test_executor_dedups_by_idempotency_key(Session):
    executor = BookingActionExecutor(backend=BookingStore(Session))
    actions = _prepared()
    [executor.execute(a) for a in actions]
    [executor.execute(a) for a in actions]  # replay
    with Session() as s:
        assert s.query(Client).count() == 1
        assert s.query(Appointment).count() == 1


def test_executor_rejects_unknown_action(Session):
    executor = make_booking_executor(Session)
    with pytest.raises(ValueError):
        executor.execute(PreparedAction(action="launch_rocket"))


# --- DB-enforced slot uniqueness (uq_appt_staff_slot) ----------------------


def test_duplicate_staff_slot_is_rejected_as_slot_taken(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        staff_id = s.query(Staff).first().id
        repo = BookingRepository(s)
        start = f"{REQ_DATE} 10:00"
        repo.create_appointment(
            job_id=job_id, staff_id=staff_id, staff_name="x",
            start_date=datetime.fromisoformat(f"{start}:00"),
        )
        # Same (staff, start_date) → DB unique violation surfaced as a domain error.
        with pytest.raises(SlotTakenError):
            repo.create_appointment(
                job_id=job_id, staff_id=staff_id, staff_name="x",
                start_date=datetime.fromisoformat(f"{start}:00"),
            )
    with Session() as s:
        assert s.query(Appointment).count() == 1  # the rejected insert rolled back


def test_null_staff_appointments_are_exempt_from_slot_uniqueness(Session):
    job_id = seed_job(Session)
    with Session() as s:
        repo = BookingRepository(s)
        start = datetime.fromisoformat(f"{REQ_DATE} 10:00:00")
        repo.create_appointment(job_id=job_id, staff_id=None, staff_name="x", start_date=start)
        repo.create_appointment(job_id=job_id, staff_id=None, staff_name="y", start_date=start)
    with Session() as s:
        assert s.query(Appointment).count() == 2  # null-staff rows aren't constrained


# --- durable idempotency (survives a process restart) ----------------------


def _ledgered_executor(Session) -> BookingActionExecutor:
    return BookingActionExecutor(
        backend=BookingStore(Session), idempotency=DbIdempotencyStore(Session)
    )


def test_durable_idempotency_survives_executor_restart(Session):
    actions = _prepared()
    first = _ledgered_executor(Session)
    for a in actions:
        first.execute(a)
    # "Restart": a brand-new executor (empty in-memory dedup + ctx), same DB
    # ledger. The replay must NOT create duplicate rows.
    second = _ledgered_executor(Session)
    for a in actions:
        second.execute(a)
    with Session() as s:
        assert s.query(Client).count() == 1
        assert s.query(Contact).count() == 1
        assert s.query(Job).count() == 1
        assert s.query(Appointment).count() == 1
        assert s.query(ExecutedAction).count() == 4  # one ledger row per action


def test_durable_idempotency_completes_after_partial_crash(Session):
    actions = _prepared()
    crashed = _ledgered_executor(Session)
    for a in actions[:2]:  # only client + contact committed before the "crash"
        crashed.execute(a)
    # Resume on a fresh executor replays everything; the first two are recognised
    # from the ledger (ids re-threaded), the rest run exactly once.
    resumed = _ledgered_executor(Session)
    for a in actions:
        resumed.execute(a)
    with Session() as s:
        counts = (
            s.query(Client).count(),
            s.query(Contact).count(),
            s.query(Job).count(),
            s.query(Appointment).count(),
        )
    assert counts == (1, 1, 1, 1)


def test_batch_commits_booking_and_ledger_atomically(Session):
    seed_default_staff(Session)
    ex = _ledgered_executor(Session)
    with ex.batch():
        for a in _prepared():
            ex.execute(a)
    with Session() as s:
        assert s.query(Client).count() == 1
        assert s.query(Appointment).count() == 1
        assert s.query(ExecutedAction).count() == 4  # ledger committed in the SAME txn
    assert len(ex._done) == 4  # dedup cache promoted only after a clean commit


def test_batch_rolls_back_booking_and_ledger_on_failure(Session):
    seed_default_staff(Session)

    class _FailSchedule(BookingStore):
        def schedule_job(self, **kw):  # fail at the last step, after 3 writes flushed
            raise RuntimeError("transient failure mid-booking")

    ex = BookingActionExecutor(
        backend=_FailSchedule(Session), idempotency=DbIdempotencyStore(Session)
    )
    with pytest.raises(RuntimeError):  # noqa: PT012 - asserting the whole batch unwinds
        with ex.batch():
            for a in _prepared():
                ex.execute(a)
    with Session() as s:
        assert s.query(Client).count() == 0  # client/contact/job rolled back, not orphaned
        assert s.query(Job).count() == 0
        assert s.query(ExecutedAction).count() == 0  # ledger rolled back with them
    assert ex._done == {}  # nothing promoted from a rolled-back batch → full re-run on retry


def test_concurrent_batches_are_isolated(Session):
    """Two runs hitting the SHARED executor's batch at the same time must not
    clobber each other's transaction / id-threading (regression: per-run state
    is thread-local)."""
    ex = BookingActionExecutor(backend=BookingStore(Session), idempotency=DbIdempotencyStore(Session))
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def run_one(tag: str) -> None:
        actions = [
            PreparedAction(
                action="create_client",
                payload={"name": tag, "email": f"{tag}@x", "phone": "1", "address": "z"},
                idempotency_key=f"{tag}:create_client",
            ),
            PreparedAction(
                action="create_contact",
                payload={"name": tag, "email": f"{tag}@x", "phone": "1"},
                idempotency_key=f"{tag}:create_contact",
            ),
            PreparedAction(
                action="create_job",
                payload={"service": "fix", "address": "z"},
                idempotency_key=f"{tag}:create_job",
            ),
            PreparedAction(
                action="schedule_job",
                payload={"date": REQ_DATE, "time": "10:00", "staff": "X", "staff_id": None},
                idempotency_key=f"{tag}:schedule_job",
            ),
        ]
        try:
            with ex.batch():
                barrier.wait(timeout=5)  # force both runs inside their batch at once
                for a in actions:
                    ex.execute(a)
        except Exception as e:  # pragma: no cover - only fires if the isolation regresses
            errors.append(e)

    threads = [threading.Thread(target=run_one, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    with Session() as s:
        clients = {c.name: c.id for c in s.query(Client).all()}
        assert set(clients) == {"A", "B"}  # each run booked its OWN client
        job_client = {j.id: j.client_id for j in s.query(Job).all()}
        assert len(job_client) == 2
        # FK integrity: every job/contact/appointment chains back to a real client
        # (no cross-run id leakage from a shared ctx).
        assert all(cid in clients.values() for cid in job_client.values())
        assert all(ct.client_id in clients.values() for ct in s.query(Contact).all())
        appts = s.query(Appointment).all()
        assert len(appts) == 2
        assert all(job_client[a.job_id] in clients.values() for a in appts)


def test_idempotency_repo_records_and_ignores_duplicate(Session):
    with Session() as s:
        repo = IdempotencyRepository(s)
        assert repo.get("k1") is None
        repo.record(key="k1", run_id="r", action="create_client", result={"uuid": "u1"})
        assert repo.get("k1") == {"uuid": "u1"}
        # A racing duplicate insert is swallowed; the first result wins.
        repo.record(key="k1", run_id="r", action="create_client", result={"uuid": "u2"})
        assert repo.get("k1") == {"uuid": "u1"}


# --- returning-customer dedup (one client per email) -----------------------


def test_returning_customer_reuses_one_client(Session):
    store = BookingStore(Session)
    first = store.create_client(name="Priya", email="p@x.com", phone="1", address="z")
    second = store.create_client(name="Priya", email="p@x.com", phone="1", address="z")
    assert first["uuid"] == second["uuid"]
    with Session() as s:
        assert s.query(Client).count() == 1


def test_clients_without_email_are_not_deduped(Session):
    store = BookingStore(Session)
    store.create_client(name="X", email=None, phone="1", address="z")
    store.create_client(name="Y", email=None, phone="2", address="z")
    with Session() as s:
        assert s.query(Client).count() == 2


def test_get_or_create_client_reraises_when_row_gone_after_conflict(Session):
    """If the conflicting client row disappears between the error and the re-read,
    the IntegrityError is re-raised rather than silently swallowed."""
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    with Session() as s:
        repo = BookingRepository(s)
        calls = {"n": 0}
        orig_flush = s.flush

        def fake_flush(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                s.rollback()
                raise IntegrityError("simulated", {}, Exception())
            return orig_flush(*a, **kw)

        with patch.object(s, "flush", fake_flush), patch.object(s, "scalar", return_value=None):
            with pytest.raises(IntegrityError):
                repo.get_or_create_client(name="Ghost", email="ghost@x.com", phone="1", address="z")


def test_get_or_create_client_insert_first_recovers_from_race(Session):
    """On IntegrityError (uq_clients_email) the method rolls back and returns
    the row that a concurrent writer inserted — no duplicate client is created."""
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError

    with Session() as s:
        repo = BookingRepository(s)
        # Seed the "winner" row that the concurrent writer would have inserted.
        existing = repo.create_client(name="Priya", email="race@x.com", phone="1", address="z")

    # Simulate a second caller whose commit races and loses.
    with Session() as s:
        repo = BookingRepository(s)
        original_flush = s.flush

        called = {"n": 0}

        def fake_flush(*a, **kw):
            called["n"] += 1
            if called["n"] == 1:
                raise IntegrityError("simulated", {}, Exception())
            return original_flush(*a, **kw)

        with patch.object(s, "flush", fake_flush):
            result = repo.get_or_create_client(
                name="Priya", email="race@x.com", phone="1", address="z"
            )

    assert result.id == existing.id
    with Session() as s:
        assert s.query(Client).count() == 1


def test_returning_contact_is_reused(Session):
    store = BookingStore(Session)
    client = store.create_client(name="Priya", email="p@x.com", phone="1", address="z")
    first = store.create_contact(
        client_uuid=client["uuid"], name="Priya", email="p@x.com", phone="1"
    )
    second = store.create_contact(
        client_uuid=client["uuid"], name="Priya", email="p@x.com", phone="1"
    )
    assert first["uuid"] == second["uuid"]
    with Session() as s:
        assert s.query(Contact).count() == 1


def test_appointments_on_respects_limit(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        for hour in range(8, 12):
            s.add(
                Appointment(
                    job_id=job_id,
                    staff_name="x",
                    start_date=datetime.fromisoformat(f"{REQ_DATE} {hour:02d}:00:00"),
                )
            )
        s.commit()
        capped = BookingRepository(s).appointments_on(REQ_DATE, limit=2)
    assert len(capped) == 2


# --- availability ---------------------------------------------------------


def test_seed_default_staff_is_idempotent(Session):
    assert seed_default_staff(Session) == 3
    assert seed_default_staff(Session) == 0  # already seeded
    with Session() as s:
        assert s.query(Staff).count() == 3


def test_availability_all_free_when_no_appointments(Session):
    provider = make_provider(Session)
    assert provider.is_available(Slot(date=REQ_DATE, time="10:00")) is True
    staff = provider.staff_for_day(REQ_DATE)
    slots = provider.slots_for_day(REQ_DATE, staff)
    assert len(slots) == len(staff) * (17 - 8)  # business hours per staff


def test_availability_excludes_booked_times(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        staff_id = s.query(Staff).first().id
        s.add(
            Appointment(
                job_id=job_id, staff_id=staff_id, staff_name="x", start_date=datetime.fromisoformat(f"{REQ_DATE} 10:00:00")
            )
        )
        s.commit()
    provider = DbAvailabilityProvider(session_factory=Session)
    slots = provider.slots_for_day(REQ_DATE, provider.staff_for_day(REQ_DATE))
    booked_staff_at_10 = [s for s in slots if s.staff_id == staff_id and s.time == "10:00"]
    assert booked_staff_at_10 == []  # that staff is busy at 10:00


# --- eligible_staff hard gate (skill / free@hour / geo, in indexed SQL) ----


def test_eligible_staff_filters_by_skill(Session):
    seed_default_staff(Session)  # Alex+Sam: cleaning; Jordan: plumbing
    with Session() as s:
        names = {
            st.name
            for st in BookingRepository(s).eligible_staff(
                date_iso=REQ_DATE, time="10:00", skill="cleaning"
            )
        }
    assert names == {"Alex Taylor", "Sam Rivers"}  # Jordan lacks the cleaning skill


def test_eligible_staff_excludes_busy_at_the_hour(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        alex = s.query(Staff).filter(Staff.name == "Alex Taylor").one()
        s.add(
            Appointment(
                job_id=job_id,
                staff_id=alex.id,
                staff_name=alex.name,
                start_date=datetime.fromisoformat(f"{REQ_DATE} 10:00:00"),
            )
        )
        s.commit()
        names = {
            st.name
            for st in BookingRepository(s).eligible_staff(
                date_iso=REQ_DATE, time="10:00", skill="cleaning"
            )
        }
    assert "Alex Taylor" not in names and "Sam Rivers" in names  # Alex booked at 10:00


def test_eligible_staff_geo_box_excludes_distant_staff(Session):
    seed_default_staff(Session)
    with Session() as s:
        names = {
            st.name
            for st in BookingRepository(s).eligible_staff(
                date_iso=REQ_DATE,
                time="10:00",
                skill="cleaning",
                job_lat=-27.47,
                job_lng=153.02,  # at Alex's home base
                radius_km=2.0,  # tight box: Sam (~4km away) falls outside
            )
        }
    assert names == {"Alex Taylor"}


def test_availability_false_when_all_staff_busy(Session):
    seed_default_staff(Session)
    job_id = seed_job(Session)
    with Session() as s:
        for staff in s.query(Staff).all():
            s.add(
                Appointment(
                    job_id=job_id,
                    staff_id=staff.id,
                    staff_name=staff.name,
                    start_date=datetime.fromisoformat(f"{REQ_DATE} 10:00:00"),
                )
            )
        s.commit()
    provider = DbAvailabilityProvider(session_factory=Session)
    assert provider.is_available(Slot(date=REQ_DATE, time="10:00")) is False
