"""Workflow run endpoints: start a booking run (async), inspect it, approve/reject
the human gate, and stream its events live (SSE)."""

from __future__ import annotations

import json
from queue import Empty

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from ...core.auth import require_principal
from ...core.exceptions import ConflictError, NotFoundError
from ...core.ratelimit import rate_limit_runs
from ...models import RunStatus
from ...schemas.runs import ApprovalDecision, NodeDetail, RunResponse, StartRunRequest
from ...services.run_service import RunView, WorkflowRunner
from ..deps import get_runner

# Auth applies to every run route: a no-op when API_AUTH_TOKEN is unset (dev),
# enforced (401) when it's set.
router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_principal)])

# Statuses at which a run is no longer producing live events.
TERMINAL = {
    RunStatus.paused.value,
    RunStatus.completed.value,
    RunStatus.failed.value,
    RunStatus.escalated.value,
}
STREAM_TIMEOUT_S = 30.0


def _response(view: RunView) -> RunResponse:
    return RunResponse(
        run_id=view.run_id,
        status=view.status,
        node_statuses=view.node_statuses,
        approval_card=view.approval_card,
        final_response=view.final_response,
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    body: StartRunRequest,
    runner: WorkflowRunner = Depends(get_runner),
    _: None = Depends(rate_limit_runs),
) -> RunResponse:
    run_id = runner.submit_start(body.message)
    return RunResponse(run_id=run_id, status=RunStatus.running.value)


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, runner: WorkflowRunner = Depends(get_runner)) -> RunResponse:
    view = runner.get(run_id)
    if view is None:
        raise NotFoundError("Run not found")
    return _response(view)


@router.get("/{run_id}/nodes", response_model=list[NodeDetail])
def run_nodes(run_id: str, runner: WorkflowRunner = Depends(get_runner)) -> list[NodeDetail]:
    """Per-node execution detail (status + produced output) for the clickable
    node-preview panel."""
    if runner.get(run_id) is None:
        raise NotFoundError("Run not found")
    return [NodeDetail(**d) for d in runner.node_details(run_id)]


def _require_paused(run_id: str, runner: WorkflowRunner) -> None:
    view = runner.get(run_id)
    if view is None:
        raise NotFoundError("Run not found")
    if view.status != RunStatus.paused.value:
        raise ConflictError("Run is not awaiting approval")


@router.post(
    "/{run_id}/approve",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def approve_run(
    run_id: str,
    decision: ApprovalDecision | None = None,
    runner: WorkflowRunner = Depends(get_runner),
    principal: str | None = Depends(require_principal),
) -> RunResponse:
    _require_paused(run_id, runner)
    decision = decision or ApprovalDecision()
    # The authenticated principal is the recorded actor; a client-supplied `by`
    # is only a fallback when auth is disabled (dev), never a trusted identity.
    runner.submit_resume(run_id, approved=True, by=principal or decision.by)
    return RunResponse(run_id=run_id, status=RunStatus.running.value)


@router.post(
    "/{run_id}/reject",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reject_run(
    run_id: str,
    decision: ApprovalDecision | None = None,
    runner: WorkflowRunner = Depends(get_runner),
    principal: str | None = Depends(require_principal),
) -> RunResponse:
    _require_paused(run_id, runner)
    decision = decision or ApprovalDecision()
    runner.submit_resume(
        run_id, approved=False, by=principal or decision.by, reason=decision.reason
    )
    return RunResponse(run_id=run_id, status=RunStatus.running.value)


def _require_failed(run_id: str, runner: WorkflowRunner) -> None:
    view = runner.get(run_id)
    if view is None:
        raise NotFoundError("Run not found")
    if view.status != RunStatus.failed.value:
        raise ConflictError("Only a failed run can be retried")


@router.post(
    "/{run_id}/retry",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_run(run_id: str, runner: WorkflowRunner = Depends(get_runner)) -> RunResponse:
    """Resume a failed run from its last checkpoint.

    Idempotent at the data layer (the ledger dedupes), so retrying never double-books."""
    _require_failed(run_id, runner)
    runner.submit_retry(run_id)
    return RunResponse(run_id=run_id, status=RunStatus.running.value)


def _sse(event: dict) -> str:
    payload = {
        "node": event["node"],
        "status": event["status"],
        "duration_ms": event.get("duration_ms"),
    }
    return f"data: {json.dumps(payload)}\n\n"


def event_stream(runner: WorkflowRunner, run_id: str):
    """Replay persisted events, then stream live until the run hits a boundary.

    If the run already finished, buffered events are drained without blocking."""
    q = runner.subscribe(run_id)
    try:
        for event in runner.events(run_id):
            yield _sse(event)
        view = runner.get(run_id)
        already_done = view is not None and view.status in TERMINAL
        while True:
            if already_done:
                try:
                    event = q.get_nowait()
                except Empty:
                    break
            else:
                try:
                    event = q.get(timeout=STREAM_TIMEOUT_S)
                except Empty:
                    # Idle keep-alive: an SSE comment frame so a proxy doesn't
                    # close the connection while a run waits (e.g. for approval).
                    yield ": keep-alive\n\n"
                    continue
            if event.get("type") == "end":
                break
            yield _sse(event)
    finally:
        runner.unsubscribe(run_id, q)
    yield "event: end\ndata: {}\n\n"


@router.get("/{run_id}/events")
def stream_events(run_id: str, runner: WorkflowRunner = Depends(get_runner)):
    """Server-Sent Events: live node transitions for the React Flow canvas."""
    if runner.get(run_id) is None:
        raise NotFoundError("Run not found")
    return StreamingResponse(
        event_stream(runner, run_id),
        media_type="text/event-stream",
        headers={
            # Keep the stream from being buffered/transformed by a reverse proxy
            # (nginx/CDN) — without this, events sit in the proxy until it times
            # out and the canvas never animates.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
