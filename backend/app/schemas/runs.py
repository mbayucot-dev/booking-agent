"""Request/response schemas for the workflow run endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..core.config import get_settings

# Bound the inbound message (ReDoS via the rules-path regexes / storage abuse).
# Reuse the same cap the extraction node truncates to.
_MAX_MESSAGE_CHARS = get_settings().max_message_chars

# Mirror the backend enums (app.models.RunStatus / NodeStatus) so the public API
# contract is enumerated in OpenAPI and validated, not a free-form string.
RunStatusLiteral = Literal["running", "paused", "completed", "failed", "escalated"]
NodeStatusLiteral = Literal[
    "idle",
    "running",
    "success",
    "failed",
    "waiting_approval",
    "approved",
    "rejected",
    "skipped",
]


class StartRunRequest(BaseModel):
    message: str = Field(
        min_length=1,
        max_length=_MAX_MESSAGE_CHARS,
        description="Natural-language booking request",
    )


class ApprovalDecision(BaseModel):
    by: str | None = None
    reason: str | None = None


class RunResponse(BaseModel):
    run_id: str
    status: RunStatusLiteral
    node_statuses: dict[str, NodeStatusLiteral] = Field(default_factory=dict)
    approval_card: dict | None = None
    final_response: str | None = None


class NodeDetail(BaseModel):
    """Per-node execution detail for the clickable node-preview panel: the
    latest status + the output the node contributed to state (and timing/cost)."""

    node: str
    status: NodeStatusLiteral
    duration_ms: int | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    output: dict | None = None
