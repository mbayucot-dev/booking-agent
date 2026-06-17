"""audit_log node — writes one audit entry per executed mutation.

Runs after the execution node on the approved path. Reads the approval (for the
actor that approved) and the execution results, and emits an audit entry per
mutation through the injected :class:`AuditWriter`.
"""

from __future__ import annotations

from .. import constants as C
from ..audit import AuditWriter, NullAuditWriter
from ..instrumentation import EventSink, NullEventSink, instrument
from ..state import BookingState


def make_audit_log(writer: AuditWriter | None = None, sink: EventSink | None = None):
    writer = writer or NullAuditWriter()
    sink = sink or NullEventSink()

    def audit_log(state: BookingState) -> BookingState:
        run_id = state.get("run_id", "")
        approval = state.get("approval")
        actor = approval.decided_by if approval else None
        execution = state.get("execution") or {}
        executed = execution.get("executed", [])
        results = execution.get("results", [])

        written = 0
        for action, result in zip(executed, results, strict=False):
            result = result or {}
            writer.write(
                {
                    "run_id": run_id,
                    "actor": actor,
                    "action": action,
                    "target_type": "booking",
                    "target_id": result.get("uuid"),
                    "payload": result,
                    "result": {"ok": result.get("ok", True)},
                }
            )
            written += 1
        return {"audit": {"written": written}}

    return instrument(C.AUDIT_LOG, audit_log, sink)
