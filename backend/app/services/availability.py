"""Availability over the local booking datastore.

Implements the graph's ``AvailabilityProvider`` protocol: staff come from the
``staff`` table, busy times from existing ``appointments``, free slots are
business-hours minus busy.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker

from ..config import Settings, get_settings
from ..graph.availability_provider import Staff
from ..graph.state import Slot
from ..repositories.booking import BookingRepository
from .staff_ranking import StaffCandidate

# Default cleaners with skills + home-base coords (Brisbane-ish) so proximity,
# load, and skill matching all work out of the box.
DEFAULT_STAFF = [
    {
        "name": "Alex Taylor",
        "skills": ["cleaning", "contact work"],
        "latitude": -27.47,
        "longitude": 153.02,
        "bio": "Detail-oriented; great with pets and nervous animals.",
    },
    {
        "name": "Sam Rivers",
        "skills": ["cleaning", "gardening"],
        "latitude": -27.50,
        "longitude": 153.05,
        "bio": "Fast, eco-friendly products.",
    },
    {
        "name": "Jordan Lee",
        "skills": ["plumbing", "contact work"],
        "latitude": -27.45,
        "longitude": 152.98,
        "bio": "Deep cleans; calm and patient, good with anxious dogs.",
    },
]


def seed_default_staff(session_factory: sessionmaker, embedder=None) -> int:
    """Idempotently seed default staff so jobs can be assigned out of the box.
    Bios are embedded on write when an ``embedder`` is supplied."""
    with session_factory() as session:
        return BookingRepository(session).seed_staff(DEFAULT_STAFF, embedder=embedder)


@dataclass
class DbAvailabilityProvider:
    session_factory: sessionmaker
    open_hour: int = 8
    close_hour: int = 17

    def _staff_rows(self):
        with self.session_factory() as session:
            return BookingRepository(session).active_staff()

    def staff_for_day(self, date_iso: str) -> list[Staff]:
        return [
            Staff(
                id=s.id,
                name=s.name,
                skills=tuple(s.skills or ()),
                latitude=s.latitude,
                longitude=s.longitude,
            )
            for s in self._staff_rows()
        ]

    def _busy_by_staff(self, date_iso: str) -> dict[str, set[str]]:
        busy: dict[str, set[str]] = {}
        with self.session_factory() as session:
            for appt in BookingRepository(session).appointments_on(date_iso):
                # start_date is a datetime now; format the wall-clock "HH:MM".
                busy.setdefault(appt.staff_id or "", set()).add(appt.start_date.strftime("%H:%M"))
        return busy

    def free_staff_at(
        self,
        date_iso: str,
        time: str,
        service: str | None = None,
        job_lat: float | None = None,
        job_lng: float | None = None,
    ) -> list[StaffCandidate]:
        """Candidate cleaners for ranking.

        With ``service``, the hard gates (skill + free@hour + geo box) are pushed
        into one indexed SQL query; otherwise all active staff free at the hour."""
        busy = self._busy_by_staff(date_iso)  # all assigned cleaners' booked hours that day
        with self.session_factory() as session:
            repo = BookingRepository(session)
            if service:
                rows = repo.eligible_staff(
                    date_iso=date_iso, time=time, skill=service, job_lat=job_lat, job_lng=job_lng
                )
            else:
                rows = repo.active_staff()
            staff = [
                (
                    s.id,
                    s.name,
                    tuple(s.skills or ()),
                    s.latitude,
                    s.longitude,
                    s.bio,
                    s.bio_embedding,
                )
                for s in rows
            ]
        candidates: list[StaffCandidate] = []
        for sid, name, skills, lat, lng, bio, emb in staff:
            booked = tuple(sorted(busy.get(sid, set())))
            if service is None and time in booked:
                continue  # active-staff path: drop those busy at the hour
            candidates.append(
                StaffCandidate(
                    staff_id=sid,
                    staff_name=name,
                    skills=skills,
                    latitude=lat,
                    longitude=lng,
                    day_load=len(booked),
                    booked_times=booked,
                    bio=bio,
                    bio_embedding=emb,
                )
            )
        return candidates

    def slots_for_day(self, date_iso: str, staff: list[Staff]) -> list[Slot]:
        busy = self._busy_by_staff(date_iso)
        slots: list[Slot] = []
        for member in staff:
            taken = busy.get(member.id, set())
            for hour in range(self.open_hour, self.close_hour):
                time = f"{hour:02d}:00"
                if time not in taken:
                    slots.append(
                        Slot(date=date_iso, time=time, staff_id=member.id, staff_name=member.name)
                    )
        return slots

    def is_available(self, slot: Slot) -> bool:
        busy = self._busy_by_staff(slot.date)
        staff = self.staff_for_day(slot.date)
        return any(slot.time not in busy.get(member.id, set()) for member in staff)


def build_availability_provider(
    session_factory: sessionmaker, settings: Settings | None = None
) -> DbAvailabilityProvider:
    settings = settings or get_settings()
    return DbAvailabilityProvider(
        session_factory=session_factory,
        open_hour=settings.business_open_hour,
        close_hour=settings.business_close_hour,
    )
