"""Human approval gate (LangGraph ``interrupt``).

The workflow must pause for a human before any mutating action runs.
``prepare_payloads`` builds the un-executed actions and card; ``human_approval``
interrupts to record the decision; ``execute_actions`` is the only node that
mutates (refuses unless approved); ``handle_rejection`` is the terminal no-op path.

Mutations go through an injected :class:`ActionExecutor` seam (tests use
:class:`RecordingExecutor`; the app injects the DB-backed executor).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Protocol

from langgraph.types import interrupt

from .. import constants as C
from ..instrumentation import EventSink, RunEventRecord, instrument
from ..state import ApprovalState, BookingState, PreparedAction

# Approval card status surfaced to the canvas while paused.
WAITING_APPROVAL = "waiting_approval"
APPROVED = "approved"
REJECTED = "rejected"


# --- Mutation execution seam ---------------------------------------------


class ActionExecutor(Protocol):
    def execute(self, action: PreparedAction) -> dict: ...


@dataclass
class RecordingExecutor:
    """Records executed actions instead of calling real services.

    The recording is the proof for "no mutation before approval": tests assert
    ``executed`` is empty while the graph is paused.
    """

    executed: list[PreparedAction] = field(default_factory=list)

    def execute(self, action: PreparedAction) -> dict:
        self.executed.append(action)
        return {"action": action.action, "ok": True, "ref": f"fake-{action.action}"}


# --- Card -----------------------------------------------------------------


def build_approval_card(state: BookingState) -> dict:
    """The reviewer-facing summary: customer, service, date, time, staff,
    email, and the prepared actions."""
    req = state.get("booking_request")
    avail = state.get("availability")
    slot = avail.chosen_slot if avail and avail.chosen_slot else None

    date = slot.date if slot else (req.date if req else None)
    time = slot.time if slot else (req.time if req else None)
    staff = slot.staff_name if slot else None

    prepared = state.get("prepared_actions", [])
    return {
        "customer": req.customer_name if req else None,
        "service": req.service if req else None,
        "date": date,
        "time": time,
        "staff": staff,
        "staff_assignment_reason": (state.get("job_plan") or {}).get("assignment_reason"),
        "email": req.email if req else None,
        "prepared_actions": [
            a.model_dump() if isinstance(a, PreparedAction) else a for a in prepared
        ],
    }


# --- Nodes ----------------------------------------------------------------


def prepare_payloads(state: BookingState) -> BookingState:
    """Prepare all mutating action payloads — but execute none of them."""
    req = state.get("booking_request")
    if req is None:
        raise ValueError("prepare_payloads requires a booking_request in state")
    run_id = state.get("run_id") or "run"
    avail = state.get("availability")
    slot = avail.chosen_slot if avail and avail.chosen_slot else None
    date = slot.date if slot else req.date
    time = slot.time if slot else req.time
    staff = slot.staff_name if slot else None
    staff_id = slot.staff_id if slot else None

    actions = [
        PreparedAction(
            action="create_client",
            payload={
                "name": req.customer_name,
                "email": req.email,
                "phone": req.phone,
                "address": req.address,
            },
        ),
        PreparedAction(
            action="create_contact",
            payload={"name": req.customer_name, "email": req.email, "phone": req.phone},
        ),
        PreparedAction(
            action="create_job",
            payload={"service": req.service, "address": req.address},
        ),
        PreparedAction(
            action="schedule_job",
            payload={"date": date, "time": time, "staff": staff, "staff_id": staff_id},
        ),
        # NOTE: confirmation email is handled by the email_agent, not prepared here.
    ]
    # Sanity: everything we prepare is a known mutating action.
    assert all(a.action in C.MUTATING_ACTIONS for a in actions)
    # Stable idempotency key per (run, action) so a retry can't duplicate it.
    for a in actions:
        a.idempotency_key = f"{run_id}:{a.action}"
    return {"prepared_actions": actions}


def make_human_approval(sink: EventSink):
    """Build the interrupt-based approval node bound to an event sink."""

    def human_approval(state: BookingState) -> BookingState:
        run_id = state.get("run_id", "")
        card = build_approval_card(state)

        # Surface "pending / waiting_approval" to the canvas, then pause.
        sink.emit(
            RunEventRecord(
                run_id=run_id,
                node=C.HUMAN_APPROVAL,
                status=WAITING_APPROVAL,
                output={"card": card},
            )
        )

        # Pauses here until resumed with Command(resume=...). On resume,
        # `decision` is the resume payload.
        decision = interrupt(card)

        # Fail closed: only an explicit {"approved": true} approves. Any other
        # shape is a rejection, so an ambiguous/forged resume can't auto-approve.
        # Resume contract: {"approved": bool, "by"?, "reason"?}.
        if isinstance(decision, dict):
            approved = decision.get("approved") is True
            decided_by = decision.get("by")
            reason = decision.get("reason")
        else:
            approved = False
            decided_by = None
            reason = "invalid approval resume payload (expected a dict)"

        status = APPROVED if approved else REJECTED
        approval = ApprovalState(
            status=status,
            card=card,
            prepared_actions=state.get("prepared_actions", []),
            decided_by=decided_by,
            reason=reason,
        )
        sink.emit(RunEventRecord(run_id=run_id, node=C.HUMAN_APPROVAL, status=status))
        return {"approval": approval, "approval_route": status}

    return human_approval


def make_execute_actions(executor: ActionExecutor, sink: EventSink):
    """Build the post-approval mutation node. The ONLY place mutations run."""

    def execute_actions(state: BookingState) -> BookingState:
        approval = state.get("approval")
        if approval is None or approval.status != APPROVED:
            # Defence in depth: topology already prevents this.
            raise RuntimeError("execute_actions reached without an approved approval gate")
        # Idempotent re-entry: carry forward what already ran and skip it, so a
        # re-invocation (resume replay, retry) can't duplicate a mutation.
        prior = state.get("execution") or {}
        done_keys = set(prior.get("executed_keys", []))
        executed = list(prior.get("executed", []))
        results = list(prior.get("results", []))
        # Execute as one atomic unit when the executor supports it (the DB-backed
        # one does), so a partial failure can't orphan a client/job. Executors
        # without a batch just run per-action.
        batch = getattr(executor, "batch", None)
        with batch() if batch is not None else contextlib.nullcontext():
            for action in approval.prepared_actions:
                key = action.idempotency_key or action.action
                if key in done_keys:
                    continue
                results.append(executor.execute(action))
                executed.append(action.action)
                done_keys.add(key)
        return {
            "execution": {
                "executed": executed,
                "results": results,
                "executed_keys": sorted(done_keys),
            }
        }

    return instrument(C.EXECUTION, execute_actions, sink)


def make_handle_rejection(sink: EventSink):
    def handle_rejection(state: BookingState) -> BookingState:
        return {"execution": {"executed": [], "results": [], "rejected": True}}

    return instrument(C.HANDLE_REJECTION, handle_rejection, sink)
