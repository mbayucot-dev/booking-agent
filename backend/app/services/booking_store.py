"""Booking datastore service + action executor.

``BookingStore`` performs booking mutations against our own database, and
``BookingActionExecutor`` maps the approval gate's prepared actions onto it
(post-approval only), threading ids through the sequence and de-duplicating by
idempotency key.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from ..graph.state import PreparedAction
from ..repositories.booking import BookingRepository, IdempotencyRepository


class BookingBackend(Protocol):
    def create_client(self, *, name, email, phone, address, session: Session | None = None) -> dict: ...

    def create_contact(
        self, *, client_uuid, name, email, phone, session: Session | None = None
    ) -> dict: ...

    def create_job(self, *, client_uuid, service, address, session: Session | None = None) -> dict: ...

    def schedule_job(
        self, *, job_uuid, date, time, staff, staff_id, session: Session | None = None
    ) -> dict: ...


@dataclass
class BookingStore:
    """Writes booking records to the local datastore.

    Each method commits on its own when called standalone; pass ``session`` to
    enlist the write in a caller-owned transaction (the executor's atomic batch)
    instead — then it flushes but leaves the commit to the unit of work.
    """

    session_factory: sessionmaker

    @contextmanager
    def begin(self):
        """One transaction spanning a whole booking — the unit of work the executor's batch runs inside."""
        with self.session_factory.begin() as session:
            yield session

    @contextmanager
    def _unit(self, session: Session | None):
        # Enlisted in a caller's txn (don't commit), or our own (commit on exit).
        if session is not None:
            yield session, False
        else:
            with self.session_factory() as s:
                yield s, True

    def create_client(self, *, name, email, phone, address, session: Session | None = None) -> dict:
        with self._unit(session) as (s, commit):
            row = BookingRepository(s).get_or_create_client(
                name=name, email=email, phone=phone, address=address, commit=commit
            )
            return {"uuid": row.id, "name": name}

    def create_contact(
        self, *, client_uuid, name, email, phone, session: Session | None = None
    ) -> dict:
        with self._unit(session) as (s, commit):
            row = BookingRepository(s).get_or_create_contact(
                client_id=client_uuid, name=name, email=email, phone=phone, commit=commit
            )
            return {"uuid": row.id, "client_id": client_uuid}

    def create_job(self, *, client_uuid, service, address, session: Session | None = None) -> dict:
        with self._unit(session) as (s, commit):
            row = BookingRepository(s).create_job(
                client_id=client_uuid, service=service, address=address, commit=commit
            )
            return {"uuid": row.id, "client_id": client_uuid}

    def schedule_job(
        self, *, job_uuid, date, time, staff, staff_id, session: Session | None = None
    ) -> dict:
        with self._unit(session) as (s, commit):
            row = BookingRepository(s).create_appointment(
                job_id=job_uuid,
                staff_id=staff_id,
                staff_name=staff,
                start_date=datetime.fromisoformat(f"{date} {time}:00"),
                commit=commit,
            )
            return {"uuid": row.id, "job_id": job_uuid, "staff_id": staff_id}


# --- Durable idempotency seam --------------------------------------------


class IdempotencyStore(Protocol):
    def get_result(self, key: str) -> dict | None: ...

    def record(
        self,
        *,
        key: str,
        run_id: str | None,
        action: str,
        result: dict,
        session: Session | None = None,
    ) -> None: ...


@dataclass
class NullIdempotencyStore:
    """No durable ledger — in-memory dedup only (used by unit tests)."""

    def get_result(self, key: str) -> dict | None:
        return None

    def record(
        self,
        *,
        key: str,
        run_id: str | None,
        action: str,
        result: dict,
        session: Session | None = None,
    ) -> None:
        return None


@dataclass
class DbIdempotencyStore:
    """Persists executed action results to ``executed_actions`` so a retry or a
    post-restart resume is recognised and never duplicates a booking."""

    session_factory: sessionmaker

    def get_result(self, key: str) -> dict | None:
        with self.session_factory() as s:
            return IdempotencyRepository(s).get(key)

    def record(
        self,
        *,
        key: str,
        run_id: str | None,
        action: str,
        result: dict,
        session: Session | None = None,
    ) -> None:
        # When the executor passes its batch session, the ledger row commits in
        # the SAME transaction as the booking writes — so booking + ledger are
        # atomic (no window where one persists without the other).
        if session is not None:
            IdempotencyRepository(session).record(
                key=key, run_id=run_id, action=action, result=result, commit=False
            )
            return
        with self.session_factory() as s:
            IdempotencyRepository(s).record(key=key, run_id=run_id, action=action, result=result)


def _run_id_of(key: str) -> str | None:
    """Prepared keys are ``"<run_id>:<action>"`` — pull the run id back out."""
    return key.split(":", 1)[0] if ":" in key else None


@dataclass
class BookingActionExecutor:
    """Maps prepared mutating actions onto the booking datastore (post-approval).

    Threads ids through the sequence and de-duplicates by idempotency key. Dedup
    is two-layered: an in-memory cache backed by a durable
    :class:`IdempotencyStore` that survives restarts, so a replayed or retried
    action returns the recorded result instead of double-booking.
    """

    backend: BookingBackend
    idempotency: IdempotencyStore = field(default_factory=NullIdempotencyStore)
    # Cross-run dedup cache, promoted from a batch only after it commits.
    _done: dict = field(default_factory=dict)
    # Per-run execution state is thread-local: one executor instance is shared by
    # the compiled graph across runs executing concurrently, so a shared open
    # transaction / ctx would clobber across runs.
    _local: threading.local = field(default_factory=threading.local)

    def _ts(self) -> threading.local:
        loc = self._local
        if not hasattr(loc, "ctx"):
            loc.ctx, loc.session, loc.pending = {}, None, None
        return loc

    @contextmanager
    def batch(self):
        """Run a sequence of actions as one transaction: booking writes + ledger
        rows commit together or none do. The dedup cache is promoted only after
        commit, so a rolled-back batch is fully re-run on retry."""
        ts = self._ts()
        pending: dict = {}
        with self.backend.begin() as session:
            ts.session = session
            ts.pending = pending
            try:
                yield
            finally:
                ts.session = None
                ts.pending = None
        # Reached only on a clean commit → these actions are now durably done.
        self._done.update(pending)

    def execute(self, action: PreparedAction) -> dict:
        ts = self._ts()
        key = action.idempotency_key
        if key is not None:
            cached = self._lookup(key)
            if cached is not None:
                # Re-thread ids from the recorded result so later actions in a
                # partial replay still reference the right client/job.
                self._rehydrate_ctx(action.action, cached)
                return cached
        result = self._dispatch(action.action, action.payload)
        if key is not None:
            # In a batch: buffer the dedup entry (promoted on commit) and write the
            # ledger row in the batch's transaction. Standalone: commit each.
            (ts.pending if ts.session is not None else self._done)[key] = result
            self.idempotency.record(
                key=key,
                run_id=_run_id_of(key),
                action=action.action,
                result=result,
                session=ts.session,
            )
        return result

    def _lookup(self, key: str) -> dict | None:
        if key in self._done:
            return self._done[key]
        cached = self.idempotency.get_result(key)
        if cached is not None:
            self._done[key] = cached
        return cached

    def _rehydrate_ctx(self, name: str, res: dict) -> None:
        ts = self._ts()
        if name == "create_client":
            ts.ctx = {"client_uuid": res.get("uuid")}
        elif name == "create_contact":
            ts.ctx["contact_uuid"] = res.get("uuid")
        elif name == "create_job":
            ts.ctx["job_uuid"] = res.get("uuid")

    def _dispatch(self, name: str, p: dict) -> dict:
        ts = self._ts()
        session = ts.session  # the batch's transaction, or None (standalone)
        if name == "create_client":
            ts.ctx = {}
            res = self.backend.create_client(
                name=p.get("name"),
                email=p.get("email"),
                phone=p.get("phone"),
                address=p.get("address"),
                session=session,
            )
            ts.ctx["client_uuid"] = res["uuid"]
            return res

        if name == "create_contact":
            res = self.backend.create_contact(
                client_uuid=ts.ctx.get("client_uuid"),
                name=p.get("name"),
                email=p.get("email"),
                phone=p.get("phone"),
                session=session,
            )
            ts.ctx["contact_uuid"] = res["uuid"]
            return res

        if name == "create_job":
            res = self.backend.create_job(
                client_uuid=ts.ctx.get("client_uuid"),
                service=p.get("service"),
                address=p.get("address"),
                session=session,
            )
            ts.ctx["job_uuid"] = res["uuid"]
            return res

        if name == "schedule_job":
            return self.backend.schedule_job(
                job_uuid=ts.ctx.get("job_uuid"),
                date=p.get("date"),
                time=p.get("time"),
                staff=p.get("staff"),
                staff_id=p.get("staff_id"),
                session=session,
            )

        raise ValueError(f"unsupported booking action: {name!r}")


def build_booking_executor(session_factory: sessionmaker) -> BookingActionExecutor:
    """App executor: DB-backed booking + a durable idempotency ledger, so a
    retried/replayed mutation is recognised across restarts."""
    return BookingActionExecutor(
        backend=BookingStore(session_factory),
        idempotency=DbIdempotencyStore(session_factory),
    )
