"""Demo data seeding for local development and standalone testing.

Idempotent: safe to run repeatedly (existing rows are skipped). Seeds the whole
booking datastore — staff fleet, clients/contacts, an already-occupied schedule
(so workload/proximity differentiate cleaners), and memories for a returning
customer — so the flow is demoable end-to-end. Run with ``python -m app.seeds``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .models import Appointment, Client
from .repositories.booking import BookingRepository
from .repositories.memory import MemoryRepository
from .services.availability import seed_default_staff

log = logging.getLogger("app.seeds")

# The demo's reference day (kept fixed so seeds + tests are deterministic).
SEED_DATE = "2026-06-20"

DEMO_CLIENTS = [
    {
        "name": "Priya Nair",
        "email": "priya@example.com",
        "phone": "0400111222",
        "address": "5 Park Rd, Brisbane",
    },
    {
        "name": "Liam O'Brien",
        "email": "liam@example.com",
        "phone": "0400333444",
        "address": "88 River St, Brisbane",
    },
]

# A returning customer with durable facts: a re-run shows "matched", backfills
# the preference when omitted, and the dog-friendly cleaner wins on semantics.
DEMO_MEMORIES = [
    (
        "priya@example.com",
        "preference",
        {"last_service": "cleaning", "note": "calm with anxious dogs"},
    ),
    ("priya@example.com", "communication", {"channel": "email", "address": "priya@example.com"}),
    ("priya@example.com", "vip", {"tier": "gold"}),
]

# Pre-occupy the schedule so load/proximity differentiate cleaners during
# ranking. Each tuple is (staff_name, service, "HH:MM") on SEED_DATE.
DEMO_APPOINTMENTS = [
    ("Alex Taylor", "cleaning", "09:00"),
    ("Alex Taylor", "contact work", "10:00"),
    ("Sam Rivers", "gardening", "09:00"),
]


@dataclass
class SeedSummary:
    """Rows created on this run (idempotent re-runs report zeros)."""

    staff: int = 0
    clients: int = 0
    contacts: int = 0
    memories: int = 0
    appointments: int = 0


def seed_all(session_factory: sessionmaker, embedder=None, base_date: str = SEED_DATE) -> dict:
    """Idempotently seed staff + demo clients/contacts/jobs/appointments/memories.

    Returns a count summary of rows created *this* run (zeros if already seeded).
    """
    summary = SeedSummary(staff=seed_default_staff(session_factory, embedder=embedder))

    with session_factory() as session:
        repo = BookingRepository(session)
        memory = MemoryRepository(session)
        staff_by_name = {s.name: s for s in repo.active_staff()}

        # clients + a primary contact each (idempotent by email)
        client_by_email: dict[str, Client] = {}
        for spec in DEMO_CLIENTS:
            existing = session.scalar(select(Client).where(Client.email == spec["email"]))
            if existing is not None:
                client_by_email[spec["email"]] = existing
                continue
            client = repo.create_client(
                name=spec["name"],
                email=spec["email"],
                phone=spec["phone"],
                address=spec["address"],
            )
            repo.create_contact(
                client_id=client.id, name=spec["name"], email=spec["email"], phone=spec["phone"]
            )
            client_by_email[spec["email"]] = client
            summary.clients += 1
            summary.contacts += 1

        # long-term memories for the returning customer (upsert is idempotent)
        for key, mtype, content in DEMO_MEMORIES:
            already = any(m.memory_type == mtype for m in memory.list_for(key))
            memory.upsert(key, mtype, content)
            if not already:
                summary.memories += 1

        # occupied schedule: one job per appointment, anchored to the first client
        anchor = client_by_email.get(DEMO_CLIENTS[0]["email"])
        for staff_name, service, hhmm in DEMO_APPOINTMENTS:
            staff = staff_by_name.get(staff_name)
            if staff is None or anchor is None:
                continue
            start = datetime.fromisoformat(f"{base_date} {hhmm}:00")
            booked = session.scalar(
                select(Appointment).where(
                    Appointment.staff_id == staff.id, Appointment.start_date == start
                )
            )
            if booked is not None:
                continue
            job = repo.create_job(client_id=anchor.id, service=service, address=anchor.address)
            repo.create_appointment(
                job_id=job.id, staff_id=staff.id, staff_name=staff.name, start_date=start
            )
            summary.appointments += 1

    return asdict(summary)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    logging.basicConfig(level=logging.INFO)
    from .db import SessionLocal
    from .services.embeddings import build_embedder

    summary = seed_all(SessionLocal, embedder=build_embedder())
    log.info("seeded (rows created this run): %s", summary)


if __name__ == "__main__":  # pragma: no cover
    main()
