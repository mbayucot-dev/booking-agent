"""LangGraph state schema for the booking workflow.

``BookingState`` is the dict threaded through every node. Domain payloads are
typed with Pydantic models so extraction/validation output has a stable shape.
``total=False``: every key is optional — nodes contribute their slice and the
supervisor routes on presence.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class BookingRequest(BaseModel):
    """Structured booking intent extracted from the raw chat message.

    Every field is optional: extraction records what it found, and the
    validation agent (not extraction) is responsible for flagging gaps.
    """

    customer_name: str | None = None
    service: str | None = None
    date: str | None = None  # ISO date, e.g. "2026-06-20"
    time: str | None = None  # 24h "HH:MM", e.g. "10:00"
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    # Optional job location for proximity-based staff selection.
    latitude: float | None = None
    longitude: float | None = None
    # Free-text customer note, matched semantically against staff bios.
    preferences: str | None = None


class ValidationResult(BaseModel):
    """Outcome of the validation agent."""

    ok: bool = False
    errors: list[str] = Field(default_factory=list)


class Slot(BaseModel):
    """A bookable time slot, optionally attributed to a staff member."""

    date: str  # ISO date, e.g. "2026-06-20"
    time: str  # 24h "HH:MM"
    staff_id: str | None = None
    staff_name: str | None = None


class AvailabilityResult(BaseModel):
    """Outcome of the availability subgraph."""

    available: bool = False  # the requested slot itself was free
    chosen_slot: Slot | None = None
    alternatives: list[Slot] = Field(default_factory=list)
    attempts: int = 0
    searched_days: int = 0
    escalate: bool = False  # no slot found within the limits; needs human escalation


class PreparedAction(BaseModel):
    """A mutating action that has been *prepared* but not yet executed.

    These are built before the approval gate and only run after approval.
    """

    action: str  # e.g. "create_job", "schedule_job", "send_confirmation_email"
    payload: dict = Field(default_factory=dict)
    executed: bool = False
    # Stable per-run key so retries can't duplicate a mutation (used by the
    # executor for in-process dedup and forwarded to real APIs as their
    # idempotency key).
    idempotency_key: str | None = None


ApprovalStatus = Literal["pending", "approved", "rejected"]


class ApprovalState(BaseModel):
    """Human-in-the-loop approval gate state."""

    status: ApprovalStatus = "pending"
    # The approval card shown to the reviewer.
    card: dict = Field(default_factory=dict)
    prepared_actions: list[PreparedAction] = Field(default_factory=list)
    decided_by: str | None = None
    reason: str | None = None


class BookingState(TypedDict, total=False):
    # identity
    run_id: str
    thread_id: str
    # input
    raw_message: str
    # node outputs
    booking_request: BookingRequest
    validation: ValidationResult
    # availability
    requested_slot: Slot
    availability: AvailabilityResult
    # availability subgraph internals (transient)
    av_offset: int  # days from requested date for the current attempt
    av_day: str  # ISO date currently being searched
    # bare list on purpose: typing as list[Staff] forces a runtime import of
    # availability_provider → a cycle LangGraph's get_type_hints() would trip on.
    av_staff: list  # staff available on av_day this attempt
    av_candidates: list[Slot]  # Slot candidates gathered this attempt
    av_route: str  # subgraph routing control: found | search | escalate
    # customer / planning / risk
    customer: dict
    customer_memories: list[dict]  # long-term memories loaded for this customer
    job_plan: dict
    risk: dict
    # conversation / compaction
    summary: str
    # memory write result (transient)
    memory: dict
    # approval gate
    prepared_actions: list[PreparedAction]  # prepared pre-approval, executed post-approval
    approval: ApprovalState
    approval_route: str  # approved | rejected
    execution: dict  # results of post-approval mutations
    hubspot: dict  # HubSpot contact-sync result (transient)
    email: dict  # confirmation-email send result (transient)
    # final
    final_response: str
    # routing / control
    next: str
    error: str | None
