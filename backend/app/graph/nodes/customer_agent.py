"""customer_agent — resolves the customer, loads long-term memory, and derives
the requested slot.

Read-only: no mutations here (the customer record is created post-approval by the
execution node). Loads prior memories so downstream steps and the approval card
can use them, and seeds ``requested_slot`` for the availability subgraph.
"""

from __future__ import annotations

from ..memory import InMemoryMemoryStore, MemoryStore
from ..state import BookingState, Slot


def make_customer_agent(store: MemoryStore | None = None):
    store = store or InMemoryMemoryStore()

    def customer_agent(state: BookingState) -> BookingState:
        req = state["booking_request"]
        memories = store.load(req.email) if req.email else []
        out: BookingState = {
            "customer": {
                "name": req.customer_name,
                "email": req.email,
                "phone": req.phone,
                "matched": bool(memories),  # seen before if we have memory
            },
            "customer_memories": [{"type": m.memory_type, "content": m.content} for m in memories],
        }
        # Backfill the preference from memory for a returning customer who didn't
        # restate it, so the semantic cleaner match still applies.
        if not req.preferences:
            for m in memories:
                if m.memory_type == "preference" and m.content.get("note"):
                    out["booking_request"] = req.model_copy(
                        update={"preferences": m.content["note"]}
                    )
                    break
        if req.date and req.time:
            out["requested_slot"] = Slot(date=req.date, time=req.time)
        return out

    return customer_agent
