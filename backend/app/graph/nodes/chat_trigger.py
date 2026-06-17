"""chat_trigger node — the workflow entry point.

Normalises the inbound chat message into ``raw_message``. Kept as its own node so
the React Flow canvas has an explicit "trigger" source.
"""

from __future__ import annotations

from ..state import BookingState


def chat_trigger(state: BookingState) -> BookingState:
    raw = state.get("raw_message", "")
    return {"raw_message": raw.strip()}
