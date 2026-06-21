"""Data access for the local booking datastore (clients/contacts/jobs/
appointments/staff)."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import cos, radians

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.exceptions import SlotTakenError
from ..models import Appointment, Client, Contact, ExecutedAction, Job, Staff, StaffSkill


def _bbox(lat: float, lng: float, radius_km: float):
    """Cheap, index-usable lat/lng box (~111 km per degree)."""
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(cos(radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


class BookingRepository:
    def __init__(self, session: Session):
        self.session = session

    # ``commit=False`` lets a caller compose several writes into one transaction:
    # flush to assign ids, but leave the commit to the unit of work.
    def _persist(self, row, *, commit: bool):
        self.session.add(row)
        self.session.flush()  # assign the client-side default PK
        if commit:
            self.session.commit()
        return row

    def get_or_create_client(self, *, name, email, phone, address, commit: bool = True) -> Client:
        """Reuse the existing client for a known email; otherwise create.

        Clients without an email are always created fresh.

        Uses insert-first to close the check-then-insert race: on IntegrityError
        (uq_clients_email) we roll back, re-read the winner, and return it."""
        if not email:
            return self.create_client(
                name=name, email=email, phone=phone, address=address, commit=commit
            )
        client = Client(name=name, email=email, phone=phone, address=address)
        self.session.add(client)
        try:
            self.session.flush()
            if commit:
                self.session.commit()
            return client
        except IntegrityError:
            # Concurrent writer inserted the same email first.
            self.session.rollback()
            existing = self.session.scalar(select(Client).where(Client.email == email))
            if existing is not None:
                return existing
            raise

    def create_client(self, *, name, email, phone, address, commit: bool = True) -> Client:
        return self._persist(
            Client(name=name, email=email, phone=phone, address=address), commit=commit
        )

    def get_or_create_contact(
        self, *, client_id, name, email, phone, commit: bool = True
    ) -> Contact:
        """Reuse the client's contact with the same email; else create."""
        if email:
            existing = self.session.scalar(
                select(Contact).where(Contact.client_id == client_id, Contact.email == email)
            )
            if existing is not None:
                return existing
        return self.create_contact(
            client_id=client_id, name=name, email=email, phone=phone, commit=commit
        )

    def create_contact(self, *, client_id, name, email, phone, commit: bool = True) -> Contact:
        return self._persist(
            Contact(client_id=client_id, name=name, email=email, phone=phone), commit=commit
        )

    def create_job(self, *, client_id, service, address, commit: bool = True) -> Job:
        return self._persist(
            Job(client_id=client_id, service=service, address=address), commit=commit
        )

    def create_appointment(
        self, *, job_id, staff_id, staff_name, start_date, commit: bool = True
    ) -> Appointment:
        try:
            return self._persist(
                Appointment(
                    job_id=job_id, staff_id=staff_id, staff_name=staff_name, start_date=start_date
                ),
                commit=commit,
            )
        except IntegrityError as exc:
            # uq_appt_staff_slot: that staff already holds this start_date. Roll back
            # the poisoned txn and surface a clean domain conflict (not a 500).
            self.session.rollback()
            raise SlotTakenError() from exc

    # --- reads used by availability ---
    def active_staff(self) -> list[Staff]:
        return list(
            self.session.scalars(select(Staff).where(Staff.active.is_(True)).order_by(Staff.name))
        )

    def appointments_on(self, date_iso: str, limit: int = 2000) -> list[Appointment]:
        # Bounded so the query can't return an unbounded result set.
        day = datetime.fromisoformat(f"{date_iso} 00:00:00")
        return list(
            self.session.scalars(
                select(Appointment)
                .where(
                    Appointment.start_date >= day,
                    Appointment.start_date < day + timedelta(days=1),
                )
                .limit(limit)
            )
        )

    def eligible_staff(
        self,
        *,
        date_iso: str,
        time: str,
        skill: str,
        job_lat: float | None = None,
        job_lng: float | None = None,
        radius_km: float = 25.0,
        limit: int = 50,
    ) -> list[Staff]:
        """Hard filter (indexed SQL): active staff who have the skill, are free at
        the requested hour, and (if coords given) are within the geo box.

        The LLM never sees anyone who fails these gates."""
        start = datetime.fromisoformat(f"{date_iso} {time}:00")
        q = (
            select(Staff)
            .where(Staff.active.is_(True))
            .where(exists().where(and_(StaffSkill.staff_id == Staff.id, StaffSkill.skill == skill)))
            .where(
                ~exists().where(
                    and_(Appointment.staff_id == Staff.id, Appointment.start_date == start)
                )
            )
        )
        if job_lat is not None and job_lng is not None:
            min_la, max_la, min_lo, max_lo = _bbox(job_lat, job_lng, radius_km)
            q = q.where(
                Staff.latitude.between(min_la, max_la),
                Staff.longitude.between(min_lo, max_lo),
            )
        return list(self.session.scalars(q.order_by(Staff.name).limit(limit)))

    def seed_staff(self, specs: list[dict], embedder=None) -> int:
        """Insert default staff if the table is empty. Returns rows created.

        When an ``embedder`` is supplied, each bio is embedded on write so the
        semantic preference match needs no embedding call at request time."""
        if self.session.scalar(select(Staff).limit(1)) is not None:
            return 0
        for spec in specs:
            bio = spec.get("bio")
            staff = Staff(
                name=spec["name"],
                skills=spec.get("skills"),
                latitude=spec.get("latitude"),
                longitude=spec.get("longitude"),
                bio=bio,
                bio_embedding=embedder.embed(bio) if embedder and bio else None,
            )
            self.session.add(staff)
            self.session.flush()  # assign staff.id for the skill rows
            for skill in spec.get("skills") or []:
                self.session.add(StaffSkill(staff_id=staff.id, skill=skill))
        self.session.commit()
        return len(specs)


class IdempotencyRepository:
    """Durable idempotency ledger (``executed_actions``), the source of truth
    across restarts so a replayed mutation is recognised instead of duplicated."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, key: str) -> dict | None:
        row = self.session.get(ExecutedAction, key)
        return row.result if row is not None else None

    def record(
        self, *, key: str, run_id: str | None, action: str, result: dict, commit: bool = True
    ) -> None:
        self.session.add(
            ExecutedAction(idempotency_key=key, run_id=run_id, action=action, result=result)
        )
        if not commit:
            # Part of a larger unit of work — the caller commits (and a duplicate
            # key surfaces at that commit, aborting the whole booking).
            return
        try:
            self.session.commit()
        except IntegrityError:
            # A concurrent executor recorded the same key first — that's the
            # idempotent outcome we want, so treat the race as success.
            self.session.rollback()
