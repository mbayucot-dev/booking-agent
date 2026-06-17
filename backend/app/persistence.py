"""Infrastructure adapters bridging the graph's observability seams to the DB.

The data access itself lives in :mod:`app.repositories`; this module provides:

* :class:`DbEventSink`  — ``EventSink`` -> ``run_events`` rows (replayability)
* :class:`DbAuditWriter`— ``AuditWriter`` -> ``audit_logs`` rows (auditability)
* thin run-repository convenience functions used by callers/tests.

The graph layer never imports this module; it only knows the abstract sinks.
"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from .graph.instrumentation import RunEventRecord
from .graph.state import ApprovalState
from .models import Run, RunEvent
from .repositories import AuditLogRepository, RunRepository
from .repositories.memory import MemoryRepository

# --- run repository convenience functions ---------------------------------


def create_run(session, *, run_id: str, thread_id: str | None = None, raw_message: str = "") -> Run:
    return RunRepository(session).create(
        run_id=run_id, thread_id=thread_id, raw_message=raw_message
    )


def set_run_status(session, run_id: str, status: str, final_response: str | None = None) -> None:
    RunRepository(session).set_status(run_id, status, final_response)


def replay_events(session, run_id: str) -> list[RunEvent]:
    return RunRepository(session).events(run_id)


def node_status_map(session, run_id: str) -> dict[str, str]:
    return RunRepository(session).node_status_map(run_id)


def record_approval(session, run_id: str, approval: ApprovalState):
    from .graph import constants as C

    return RunRepository(session).add_approval(run_id, C.HUMAN_APPROVAL, approval)


def finalize_run(session, run_id, *, status, final_response=None, approval=None) -> None:
    """Status + optional approval as one transaction (no commit; caller owns it)."""
    from .graph import constants as C

    RunRepository(session).finalize(
        run_id,
        status=status,
        final_response=final_response,
        node=C.HUMAN_APPROVAL,
        approval=approval,
    )


# --- observability sinks (graph protocols) --------------------------------


class DbEventSink:
    """Writes every emitted run event as a ``run_events`` row."""

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def emit(self, record: RunEventRecord) -> None:
        with self._sf() as session:
            RunRepository(session).add_event(
                run_id=record.run_id,
                node=record.node,
                status=record.status,
                input=record.input,
                output=record.output,
                duration_ms=record.duration_ms,
                tokens=record.tokens,
                cost_usd=record.cost_usd,
            )


class DbAuditWriter:
    """Writes every executed mutation as an ``audit_logs`` row."""

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def write(self, entry: dict) -> None:
        with self._sf() as session:
            AuditLogRepository(session).add(entry)


class DbMemoryStore:
    """Persists long-term memory (whitelist enforced) to ``customer_memories``."""

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def save(self, memory) -> bool:
        from .graph.memory import is_savable

        if not is_savable(memory):
            return False
        with self._sf() as session:
            MemoryRepository(session).upsert(
                memory.customer_key, memory.memory_type, memory.content
            )
        return True

    def load(self, customer_key: str) -> list:
        from .graph.memory import Memory

        with self._sf() as session:
            return [
                Memory(
                    customer_key=r.customer_key,
                    memory_type=r.memory_type,
                    content=r.content,
                )
                for r in MemoryRepository(session).list_for(customer_key)
            ]
