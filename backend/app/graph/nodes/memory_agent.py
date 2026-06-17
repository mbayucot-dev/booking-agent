"""memory_agent — persists durable customer facts after a completed booking.

Derives memories from the run and saves only whitelisted types via the injected
store (logs / tool output / transient slots are never saved). VIP status is
inferred from prior memory or left absent.
"""

from __future__ import annotations

from .. import constants as C
from ..instrumentation import EventSink, NullEventSink, instrument
from ..memory import InMemoryMemoryStore, Memory, MemoryStore
from ..state import BookingState


def _derive(state: BookingState) -> list[Memory]:
    req = state.get("booking_request")
    if req is None or not req.email:
        return []
    key = req.email
    memories: list[Memory] = []
    # communication preference: they reached us by chat and gave an email.
    memories.append(Memory(key, "communication", {"channel": "email", "address": req.email}))
    if req.service or req.preferences:
        content: dict = {}
        if req.service:
            content["last_service"] = req.service
        if req.preferences:  # durable free-text note, e.g. "calm with anxious dogs"
            content["note"] = req.preferences
        memories.append(Memory(key, "preference", content))
    return memories


def make_memory_agent(store: MemoryStore | None = None, sink: EventSink | None = None):
    store = store or InMemoryMemoryStore()
    sink = sink or NullEventSink()

    def memory_agent(state: BookingState) -> BookingState:
        saved = 0
        for memory in _derive(state):
            if store.save(memory):
                saved += 1
        return {"memory": {"saved": saved}}

    return instrument(C.MEMORY, memory_agent, sink)
