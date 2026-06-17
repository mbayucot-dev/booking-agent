"""job_planning_agent — finalizes the plan and picks the best cleaner.

Re-ranks the staff who are free at the chosen slot by skill match, workload,
proximity, and semantic match of the customer's preference to each cleaner's bio
(deterministic, optional LLM rerank), assigns the winner, and records a
rationale. Falls back to whatever the availability step picked if the provider
can't supply candidates (e.g. synthetic providers in tests).
"""

from __future__ import annotations

from ...services.embeddings import Embedder, NullEmbedder
from ...services.staff_ranking import StaffRanker
from ..state import BookingState


def make_job_planning_agent(
    provider=None,
    ranker: StaffRanker | None = None,
    embedder: Embedder | None = None,
    *,
    use_llm: bool = False,
):
    ranker = ranker or StaffRanker()
    embedder = embedder or NullEmbedder()

    def job_planning_agent(state: BookingState) -> BookingState:
        req = state["booking_request"]
        avail = state.get("availability")
        slot = avail.chosen_slot if avail and avail.chosen_slot else None

        out: BookingState = {}
        reason = None
        if slot is not None and hasattr(provider, "free_staff_at"):
            # Embed the customer's note once so the ranker can score the
            # semantic match against each cleaner's bio embedding.
            pref_embedding = embedder.embed(req.preferences) if req.preferences else None
            candidates = provider.free_staff_at(
                slot.date,
                slot.time,
                service=req.service,
                job_lat=req.latitude,
                job_lng=req.longitude,
            )
            chosen, reason = ranker.select(
                candidates,
                service=req.service,
                slot_time=slot.time,
                job_latitude=req.latitude,
                job_longitude=req.longitude,
                preference=req.preferences,
                preference_embedding=pref_embedding,
                use_llm=use_llm,
            )
            if chosen is not None:
                slot = slot.model_copy(
                    update={"staff_id": chosen.staff_id, "staff_name": chosen.staff_name}
                )
                out["availability"] = avail.model_copy(update={"chosen_slot": slot})

        out["job_plan"] = {
            "service": req.service,
            "date": slot.date if slot else req.date,
            "time": slot.time if slot else req.time,
            "staff": slot.staff_name if slot else None,
            "staff_id": slot.staff_id if slot else None,
            "address": req.address,
            "assignment_reason": reason,
        }
        return out

    return job_planning_agent
