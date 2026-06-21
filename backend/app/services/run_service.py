"""WorkflowRunner — drives the full booking graph and owns run lifecycle.

Two execution modes over the same graph:
* synchronous (``start``/``resume``) — runs to the next boundary and returns;
* background (``submit_start``/``submit_resume``) — runs in a thread, streaming
  node events live to the in-process bus, and closing the stream at the boundary.

Run status + events + approvals are persisted, so a run is replayable. A run =
one ``thread_id`` on the checkpointer.
"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy.orm import sessionmaker

from ..config import Settings, get_settings
from ..core.events import BusEventSink, EventBus
from ..core.events import bus as default_bus
from ..graph.audit import AuditWriter
from ..graph.email import DryRunEmailSender, EmailSender
from ..graph.instrumentation import CompositeEventSink
from ..graph.nodes.human_approval import ActionExecutor
from ..graph.workflow import build_workflow_graph
from ..models import Run, RunStatus
from ..persistence import (
    DbAuditWriter,
    DbEventSink,
    DbMemoryStore,
    create_run,
    finalize_run,
    node_status_map,
    replay_events,
    set_run_status,
)

log = logging.getLogger("app.runs")


@dataclass
class RunView:
    run_id: str
    status: str
    node_statuses: dict[str, str] = field(default_factory=dict)
    approval_card: dict | None = None
    final_response: str | None = None
    principal: str | None = None


class WorkflowRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        executor: ActionExecutor,
        email_sender: EmailSender | None = None,
        audit_writer: AuditWriter | None = None,
        provider=None,
        contact_sync=None,
        embedder=None,
        rationale_llm: bool = False,
        checkpointer: BaseCheckpointSaver | None = None,
        event_bus: EventBus | None = None,
        max_workers: int = 8,
        graph_timeout_s: float | None = None,
    ):
        self._sf = session_factory
        self._bus = event_bus or default_bus
        # Overall budget for a synchronous graph invocation (resume/retry run it
        # inline in the request); None → fall back to the configured default.
        self._graph_timeout_s = (
            graph_timeout_s
            if graph_timeout_s is not None
            else get_settings().graph_invocation_timeout_s
        )
        # Bounded pool: a burst of starts queues instead of spawning unbounded
        # threads (each run also drives OpenAI/DB work).
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="run")
        # Separate pool for the timed invocation: a background worker on _pool
        # calls _invoke, and nesting submits on one pool can deadlock.
        self._graph_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="run-graph"
        )
        self._futures: dict[str, Future] = {}
        # Per-run lock so a check-then-resume is atomic (concurrent approve/reject
        # on one run can't both invoke the graph).
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        sink = CompositeEventSink([DbEventSink(session_factory), BusEventSink(self._bus)])
        self._graph = build_workflow_graph(
            executor=executor,
            email_sender=email_sender or DryRunEmailSender(),
            provider=provider,
            sink=sink,
            audit_writer=audit_writer or DbAuditWriter(session_factory),
            memory_store=DbMemoryStore(session_factory),
            contact_sync=contact_sync,
            embedder=embedder,
            rationale_llm=rationale_llm,
            # None → build_workflow_graph applies the allow-listed default saver.
            checkpointer=checkpointer,
        )

    def _config(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    def _invoke(self, run_id: str, *args) -> RunView:
        """Invoke the graph under an overall wall-clock budget, then finalize.

        Runs on a dedicated pool so ``future.result(timeout)`` can abandon a
        wedged node and surface a clean 'failed' instead of pinning the request;
        the orphaned thread is still bounded by the pool's max_workers."""
        future = self._graph_pool.submit(self._graph.invoke, *args, self._config(run_id))
        try:
            result = future.result(self._graph_timeout_s)
        except TimeoutError:
            log.warning("run %s exceeded %ss graph budget", run_id, self._graph_timeout_s)
            with self._sf() as session:
                set_run_status(session, run_id, RunStatus.failed.value)
            return self.get(run_id) or RunView(run_id=run_id, status=RunStatus.failed.value)
        return self._finalize(run_id, result)

    # --- synchronous execution ---------------------------------------------

    def start(
        self, message: str, run_id: str | None = None, principal: str | None = None
    ) -> RunView:
        run_id = run_id or uuid.uuid4().hex
        with self._sf() as session:
            create_run(session, run_id=run_id, raw_message=message, principal=principal)
        return self._run_start(run_id, message)

    def _lock_for(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def _current_status(self, run_id: str) -> str | None:
        with self._sf() as session:
            run = session.get(Run, run_id)
            return run.status if run is not None else None

    def resume(
        self, run_id: str, approved: bool, by: str | None = None, reason: str | None = None
    ) -> RunView:
        # Serialize resumes and re-check status inside the lock, so two concurrent
        # approve/reject calls can't both invoke the graph.
        with self._lock_for(run_id):
            if self._current_status(run_id) != RunStatus.paused.value:
                return self.get(run_id) or RunView(run_id=run_id, status=RunStatus.failed.value)
            return self._invoke(
                run_id, Command(resume={"approved": approved, "by": by, "reason": reason})
            )

    def retry(self, run_id: str) -> RunView:
        """Resume a failed run from its last checkpoint.

        Safe to call repeatedly: already-executed mutations are recognised by the
        idempotency ledger, so a replay never double-books."""
        with self._lock_for(run_id):
            if self._current_status(run_id) != RunStatus.failed.value:
                return self.get(run_id) or RunView(run_id=run_id, status=RunStatus.failed.value)
            with self._sf() as session:
                set_run_status(session, run_id, RunStatus.running.value)
            # Passing None resumes from the checkpoint (re-runs the failed node).
            return self._invoke(run_id, None)

    def _run_start(self, run_id: str, message: str) -> RunView:
        return self._invoke(
            run_id, {"run_id": run_id, "thread_id": run_id, "raw_message": message}
        )

    # --- background execution (live streaming) -----------------------------

    def submit_start(
        self, message: str, run_id: str | None = None, principal: str | None = None
    ) -> str:
        run_id = run_id or uuid.uuid4().hex
        with self._sf() as session:
            create_run(session, run_id=run_id, raw_message=message, principal=principal)
        self._spawn(run_id, lambda: self._run_start(run_id, message))
        return run_id

    def submit_resume(
        self, run_id: str, approved: bool, by: str | None = None, reason: str | None = None
    ) -> None:
        self._spawn(run_id, lambda: self.resume(run_id, approved, by, reason))

    def submit_retry(self, run_id: str) -> None:
        self._spawn(run_id, lambda: self.retry(run_id))

    def _spawn(self, run_id: str, work) -> None:
        def worker() -> None:
            status = RunStatus.failed.value
            try:
                status = work().status
            except Exception:  # pragma: no cover - defensive
                log.exception("run %s failed", run_id)
                with self._sf() as session:
                    set_run_status(session, run_id, RunStatus.failed.value)
            finally:
                self._bus.close(run_id, status)

        self._prune_futures()
        self._futures[run_id] = self._pool.submit(worker)

    def _prune_futures(self) -> None:
        """Drop finished futures so the map tracks ~live runs, not all history."""
        for rid in [rid for rid, f in self._futures.items() if f.done()]:
            self._futures.pop(rid, None)

    def wait(self, run_id: str, timeout: float = 10.0) -> None:
        future = self._futures.get(run_id)
        if future is not None:
            try:
                future.result(timeout)
            except Exception:  # worker already logged/handled; don't re-raise
                pass

    def subscribe(self, run_id: str):
        return self._bus.subscribe(run_id)

    def unsubscribe(self, run_id: str, q) -> None:
        self._bus.unsubscribe(run_id, q)

    # --- finalize / read ---------------------------------------------------

    def _finalize(self, run_id: str, result: dict) -> RunView:
        interrupted = "__interrupt__" in result
        if interrupted:
            status = RunStatus.paused.value
        elif getattr(result.get("availability"), "escalate", False):
            # Availability escalated (no qualified/free staff): a terminal outcome,
            # NOT a successful booking — surface it as 'escalated', not 'completed'.
            status = RunStatus.escalated.value
        else:
            status = RunStatus.completed.value
        card = result["__interrupt__"][0].value if interrupted else None
        approval = None if interrupted else result.get("approval")
        # One transaction: the status change and the approval record commit (or
        # roll back) together, so a run can't be marked done without its decision.
        with self._sf.begin() as session:
            finalize_run(
                session,
                run_id,
                status=status,
                final_response=result.get("final_response"),
                approval=approval,
            )
            statuses = node_status_map(session, run_id)
        return RunView(
            run_id=run_id,
            status=status,
            node_statuses=statuses,
            approval_card=card,
            final_response=result.get("final_response"),
        )

    def node_details(self, run_id: str) -> list[dict]:
        """Latest persisted detail per node (status + output), for the node-preview panel.

        Later events win, so the terminal success/failed event (carrying the
        output) is returned. ``_jsonable`` bounds oversized strings and
        guarantees the ``dict | None`` shape."""
        from ..graph.instrumentation import _jsonable

        latest: dict[str, dict] = {}
        with self._sf() as session:
            for e in replay_events(session, run_id):
                output = _jsonable(e.output) if e.output is not None else None
                if output is not None and not isinstance(output, dict):
                    output = {"value": output}
                latest[e.node] = {
                    "node": e.node,
                    "status": e.status,
                    "duration_ms": e.duration_ms,
                    "tokens": e.tokens,
                    "cost_usd": e.cost_usd,
                    "output": output,
                }
        return list(latest.values())

    def events(self, run_id: str) -> list[dict]:
        """Persisted run_events for replay/SSE, in order."""
        with self._sf() as session:
            return [
                {
                    "node": e.node,
                    "status": e.status,
                    "duration_ms": e.duration_ms,
                    "tokens": e.tokens,
                    "cost_usd": e.cost_usd,
                }
                for e in replay_events(session, run_id)
            ]

    def get(self, run_id: str) -> RunView | None:
        with self._sf() as session:
            run = session.get(Run, run_id)
            if run is None:
                return None
            statuses = node_status_map(session, run_id)
            final = run.final_response
            status = run.status
            owner = run.principal
        card = None
        if status == RunStatus.paused.value:
            snapshot = self._graph.get_state(self._config(run_id))
            for task in snapshot.tasks:
                if task.interrupts:
                    card = task.interrupts[0].value
                    break
        return RunView(
            run_id=run_id,
            status=status,
            node_statuses=statuses,
            approval_card=card,
            final_response=final,
            principal=owner,
        )


def build_default_runner(
    session_factory: sessionmaker, settings: Settings | None = None
) -> WorkflowRunner:
    """App runner: books into the local datastore; SMTP email when configured,
    else dry-run (so dev demos run end-to-end without external credentials)."""
    from ..core.events import build_event_bus
    from ..graph.checkpointing import build_checkpointer
    from .availability import build_availability_provider
    from .booking_store import build_booking_executor
    from .embeddings import build_embedder
    from .hubspot import build_contact_sync

    settings = settings or get_settings()

    executor: ActionExecutor = build_booking_executor(session_factory)
    provider = build_availability_provider(session_factory, settings)
    contact_sync = build_contact_sync(settings)  # real HubSpot when configured
    embedder = build_embedder(settings)  # OpenAI embeddings when a key is configured

    email_sender: EmailSender
    if settings.smtp_configured:
        from .email_smtp import build_email_sender

        email_sender = build_email_sender(settings)
    else:
        email_sender = DryRunEmailSender()

    return WorkflowRunner(
        session_factory=session_factory,
        executor=executor,
        email_sender=email_sender,
        provider=provider,
        contact_sync=contact_sync,
        embedder=embedder,
        rationale_llm=settings.use_real_openai,  # LLM narrates the cleaner choice
        max_workers=settings.max_concurrent_runs,
        # Durable saver + shared bus when configured; in-process defaults otherwise.
        checkpointer=build_checkpointer(settings),
        event_bus=build_event_bus(settings),
    )
