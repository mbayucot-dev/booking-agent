"""Node instrumentation — emits a run event for every workflow step.

:func:`instrument` wraps a node so it emits ``running`` on entry and
``success``/``failed`` on exit (with duration) to a pluggable :class:`EventSink`.

Status strings match ``app.models.NodeStatus`` values (kept in lockstep), but
this module stays free of the ORM so the graph layer has no DB dependency.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

# Status string literals — must match app.models.NodeStatus and the React Flow
# NodeStatus union.
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"


@dataclass
class RunEventRecord:
    run_id: str
    node: str
    status: str
    input: dict | None = None
    output: dict | None = None
    duration_ms: int | None = None
    tokens: int | None = None
    cost_usd: float | None = None


class EventSink(Protocol):
    def emit(self, record: RunEventRecord) -> None: ...


class NullEventSink:
    """Discards events (default when observability isn't wired in)."""

    def emit(self, record: RunEventRecord) -> None:  # noqa: D401
        return None


@dataclass
class CompositeEventSink:
    """Fans an event out to several sinks (e.g. DB + live bus)."""

    sinks: list[EventSink]

    def emit(self, record: RunEventRecord) -> None:
        for sink in self.sinks:
            sink.emit(record)


@dataclass
class InMemoryEventSink:
    """Collects events in a list — used by tests and quick demos."""

    events: list[RunEventRecord] = field(default_factory=list)

    def emit(self, record: RunEventRecord) -> None:
        self.events.append(record)

    def by_node(self, node: str) -> list[RunEventRecord]:
        return [e for e in self.events if e.node == node]

    def statuses(self, node: str) -> list[str]:
        return [e.status for e in self.by_node(node)]


# Bound a single string field so a pathological node output can't bloat a
# run_events row (and the SSE payload) unboundedly.
MAX_STR_LEN = 8_000


def _jsonable(value: Any) -> Any:
    """Coerce node output (which may contain Pydantic models or dataclasses) to
    plain JSON, truncating oversized strings."""
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, str) and len(value) > MAX_STR_LEN:
        return value[:MAX_STR_LEN] + "…[truncated]"
    return value


NodeFn = Callable[[dict], dict]


def instrument(node_name: str, fn: NodeFn, sink: EventSink) -> NodeFn:
    """Wrap ``fn`` so it emits running/success/failed run events."""

    def wrapped(state: dict) -> dict:
        run_id = state.get("run_id", "")
        sink.emit(RunEventRecord(run_id=run_id, node=node_name, status=RUNNING))
        start = time.perf_counter()
        try:
            out = fn(state) or {}
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            sink.emit(
                RunEventRecord(
                    run_id=run_id,
                    node=node_name,
                    status=FAILED,
                    output={"error": str(exc)},
                    duration_ms=duration_ms,
                )
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        sink.emit(
            RunEventRecord(
                run_id=run_id,
                node=node_name,
                status=SUCCESS,
                output=_jsonable(out),
                duration_ms=duration_ms,
            )
        )
        return out

    return wrapped
