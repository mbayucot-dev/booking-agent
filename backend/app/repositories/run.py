"""Repository for runs, run_events, and approvals."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..graph.state import ApprovalState
from ..models import Approval, Run, RunEvent, RunStatus


class RunRepository:
    def __init__(self, session: Session):
        self.session = session

    # --- runs ---
    def create(self, *, run_id: str, thread_id: str | None = None, raw_message: str = "") -> Run:
        run = Run(
            id=run_id,
            thread_id=thread_id or run_id,
            raw_message=raw_message,
            status=RunStatus.running.value,
        )
        self.session.add(run)
        self.session.commit()
        return run

    def set_status(self, run_id: str, status: str, final_response: str | None = None) -> None:
        run = self.session.get(Run, run_id)
        if run is None:
            return
        run.status = status
        if final_response is not None:
            run.final_response = final_response
        self.session.commit()

    # --- run_events ---
    def add_event(self, **fields) -> RunEvent:
        event = RunEvent(**fields)
        self.session.add(event)
        self.session.commit()
        return event

    def events(self, run_id: str) -> list[RunEvent]:
        return list(
            self.session.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
            )
        )

    def node_status_map(self, run_id: str) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for event in self.events(run_id):
            statuses[event.node] = event.status
        return statuses

    # --- approvals ---
    def _new_approval(self, run_id: str, node: str, approval: ApprovalState) -> Approval:
        return Approval(
            run_id=run_id,
            node=node,
            status=approval.status,
            card=approval.card,
            prepared_payloads=[a.model_dump() for a in approval.prepared_actions],
            decided_by=approval.decided_by,
            reason=approval.reason,
            decided_at=datetime.now(UTC) if approval.status != "pending" else None,
        )

    def add_approval(self, run_id: str, node: str, approval: ApprovalState) -> Approval:
        row = self._new_approval(run_id, node, approval)
        self.session.add(row)
        self.session.commit()
        return row

    def finalize(
        self,
        run_id: str,
        *,
        status: str,
        final_response: str | None = None,
        node: str | None = None,
        approval: ApprovalState | None = None,
    ) -> None:
        """Status + optional approval as one unit of work; does not commit (the
        caller's transaction owns the boundary, so both writes succeed or fail together)."""
        run = self.session.get(Run, run_id)
        if run is not None:
            run.status = status
            if final_response is not None:
                run.final_response = final_response
        if approval is not None:
            self.session.add(self._new_approval(run_id, node or "", approval))
