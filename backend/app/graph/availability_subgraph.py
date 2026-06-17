"""Availability subgraph.

Flow::

    check_requested_slot
        available?  yes -> END (chosen = requested)
                    no  -> search_same_day_staff
                           -> search_same_day_slots
                           -> search_next_day_slots
                           -> rank_alternative_slots
                           -> alternative_decision
                                alternative found -> END (chosen = best)
                                none, within limits -> loop to search_same_day_staff
                                none, limits hit    -> END (escalate)

Each attempt searches two days (``base+offset`` and ``base+offset+1``); a failed
attempt advances ``offset`` by 2. Bounded by ``AV_MAX_ATTEMPTS`` (3) and
``AV_MAX_SEARCH_DAYS`` (7). Every node is instrumented to emit run events.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import constants as C
from .availability_provider import (
    AvailabilityProvider,
    GenerativeFakeProvider,
    Staff,
    add_days,
)
from .instrumentation import EventSink, NullEventSink, instrument
from .state import AvailabilityResult, BookingState, Slot


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _rank(candidates: list[Slot], requested: Slot) -> list[Slot]:
    """Best first: earliest date, then closest to the requested time."""
    target = _minutes(requested.time)
    return sorted(candidates, key=lambda s: (s.date, abs(_minutes(s.time) - target)))


def build_availability_subgraph(
    provider: AvailabilityProvider | None = None,
    sink: EventSink | None = None,
):
    """Build and compile the availability subgraph with an injected provider."""
    provider = provider or GenerativeFakeProvider()
    sink = sink or NullEventSink()

    def check_requested_slot(state: BookingState) -> BookingState:
        requested = state["requested_slot"]
        result = AvailabilityResult(attempts=1, searched_days=0)
        if provider.is_available(requested):
            result.available = True
            # Assign a free staff member to the requested time, if any.
            staff = provider.staff_for_day(requested.date)
            free = [
                s for s in provider.slots_for_day(requested.date, staff) if s.time == requested.time
            ]
            result.chosen_slot = free[0] if free else requested
            return {"availability": result, "av_route": "found"}
        return {
            "availability": result,
            "av_offset": 0,
            "av_candidates": [],
            "av_route": "search",
        }

    def search_same_day_staff(state: BookingState) -> BookingState:
        requested = state["requested_slot"]
        offset = state.get("av_offset", 0)
        day = add_days(requested.date, offset)
        staff = provider.staff_for_day(day)
        return {"av_day": day, "av_staff": staff}

    def search_same_day_slots(state: BookingState) -> BookingState:
        day = state["av_day"]
        staff: list[Staff] = state.get("av_staff", [])
        found = provider.slots_for_day(day, staff)
        return {"av_candidates": list(state.get("av_candidates", [])) + found}

    def search_next_day_slots(state: BookingState) -> BookingState:
        requested = state["requested_slot"]
        offset = state.get("av_offset", 0)
        day = add_days(requested.date, offset + 1)
        staff = provider.staff_for_day(day)
        found = provider.slots_for_day(day, staff)
        return {"av_candidates": list(state.get("av_candidates", [])) + found}

    def rank_alternative_slots(state: BookingState) -> BookingState:
        candidates = state.get("av_candidates", [])
        ranked = _rank(candidates, state["requested_slot"])
        avail = state["availability"].model_copy(update={"alternatives": ranked})
        return {"availability": avail}

    def alternative_decision(state: BookingState) -> BookingState:
        avail = state["availability"]
        offset = state.get("av_offset", 0)
        covered_days = offset + 2  # days searched so far from the requested date

        if avail.alternatives:
            best = avail.alternatives[0]
            updated = avail.model_copy(update={"chosen_slot": best, "searched_days": covered_days})
            return {"availability": updated, "av_route": "found"}

        # No alternative this attempt — loop if within both limits, else escalate.
        next_window = covered_days + 2
        within_limits = avail.attempts < C.AV_MAX_ATTEMPTS and next_window <= C.AV_MAX_SEARCH_DAYS
        if within_limits:
            updated = avail.model_copy(
                update={"attempts": avail.attempts + 1, "searched_days": covered_days}
            )
            return {
                "availability": updated,
                "av_offset": offset + 2,
                "av_candidates": [],
                "av_route": "search",
            }

        escalated = avail.model_copy(
            update={
                "escalate": True,
                "searched_days": min(covered_days, C.AV_MAX_SEARCH_DAYS),
            }
        )
        return {"availability": escalated, "av_route": "escalate"}

    g = StateGraph(BookingState)
    g.add_node(C.AV_CHECK_REQUESTED, instrument(C.AV_CHECK_REQUESTED, check_requested_slot, sink))
    g.add_node(C.AV_SEARCH_STAFF, instrument(C.AV_SEARCH_STAFF, search_same_day_staff, sink))
    g.add_node(C.AV_SEARCH_SAME_DAY, instrument(C.AV_SEARCH_SAME_DAY, search_same_day_slots, sink))
    g.add_node(C.AV_SEARCH_NEXT_DAY, instrument(C.AV_SEARCH_NEXT_DAY, search_next_day_slots, sink))
    g.add_node(C.AV_RANK, instrument(C.AV_RANK, rank_alternative_slots, sink))
    g.add_node(C.AV_DECISION, instrument(C.AV_DECISION, alternative_decision, sink))

    g.add_edge(START, C.AV_CHECK_REQUESTED)
    g.add_conditional_edges(
        C.AV_CHECK_REQUESTED,
        lambda s: s["av_route"],
        {"found": END, "search": C.AV_SEARCH_STAFF},
    )
    g.add_edge(C.AV_SEARCH_STAFF, C.AV_SEARCH_SAME_DAY)
    g.add_edge(C.AV_SEARCH_SAME_DAY, C.AV_SEARCH_NEXT_DAY)
    g.add_edge(C.AV_SEARCH_NEXT_DAY, C.AV_RANK)
    g.add_edge(C.AV_RANK, C.AV_DECISION)
    g.add_conditional_edges(
        C.AV_DECISION,
        lambda s: s["av_route"],
        {"found": END, "search": C.AV_SEARCH_STAFF, "escalate": END},
    )

    return g.compile()


# Module-level default (demo/wiring); tests build their own with a custom
# provider + InMemoryEventSink.
availability_subgraph = build_availability_subgraph()
