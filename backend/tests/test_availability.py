"""Availability subgraph: requested-slot check, alternative search, ranking,
loop bounds (3 attempts / 7 days), escalation, and run-event emission."""

from app.graph import constants as C
from app.graph.availability_provider import FakeAvailabilityProvider, Staff
from app.graph.availability_subgraph import build_availability_subgraph
from app.graph.instrumentation import InMemoryEventSink
from app.graph.state import Slot

REQ_DATE = "2026-06-20"
REQ_TIME = "10:00"


def _requested() -> Slot:
    return Slot(date=REQ_DATE, time=REQ_TIME)


def _run(provider, sink=None):
    sink = sink or InMemoryEventSink()
    graph = build_availability_subgraph(provider=provider, sink=sink)
    final = graph.invoke({"run_id": "r1", "requested_slot": _requested()})
    return final["availability"], sink


def test_requested_slot_available_returns_it():
    provider = FakeAvailabilityProvider(available_slots={(REQ_DATE, REQ_TIME)})
    avail, sink = _run(provider)

    assert avail.available is True
    assert avail.chosen_slot == _requested()
    assert avail.escalate is False
    # Only the requested check ran; no search steps fired.
    assert sink.statuses(C.AV_CHECK_REQUESTED) == ["running", "success"]
    assert sink.by_node(C.AV_SEARCH_STAFF) == []


def test_picks_closest_same_day_alternative():
    staff = [Staff("s1", "Alex")]
    provider = FakeAvailabilityProvider(
        available_slots=set(),  # requested unavailable
        staff_by_day={REQ_DATE: staff},
        slots_by_day={
            REQ_DATE: [
                Slot(date=REQ_DATE, time="14:00", staff_id="s1", staff_name="Alex"),
                Slot(date=REQ_DATE, time="09:00", staff_id="s1", staff_name="Alex"),
            ]
        },
    )
    avail, _ = _run(provider)

    assert avail.available is False
    assert avail.escalate is False
    # 09:00 is closer to the requested 10:00 than 14:00.
    assert avail.chosen_slot.time == "09:00"
    assert avail.chosen_slot.date == REQ_DATE
    assert [s.time for s in avail.alternatives] == ["09:00", "14:00"]


def test_falls_back_to_next_day_when_same_day_empty():
    next_day = "2026-06-21"
    staff = [Staff("s1", "Alex")]
    provider = FakeAvailabilityProvider(
        available_slots=set(),
        staff_by_day={next_day: staff},  # no same-day staff
        slots_by_day={
            next_day: [Slot(date=next_day, time="10:00", staff_id="s1", staff_name="Alex")]
        },
    )
    avail, _ = _run(provider)

    assert avail.chosen_slot.date == next_day
    assert avail.escalate is False


def test_escalates_when_nothing_available_within_limits():
    provider = FakeAvailabilityProvider(available_slots=set())  # nothing, ever
    sink = InMemoryEventSink()
    avail, sink = _run(provider, sink)

    assert avail.chosen_slot is None
    assert avail.escalate is True
    # Bounded by the limits.
    assert avail.attempts <= C.AV_MAX_ATTEMPTS
    assert avail.searched_days <= C.AV_MAX_SEARCH_DAYS
    # Exactly 3 search attempts were made (decision ran 3 times).
    assert sink.statuses(C.AV_DECISION).count("success") == C.AV_MAX_ATTEMPTS
    assert sink.statuses(C.AV_SEARCH_STAFF).count("running") == C.AV_MAX_ATTEMPTS


def test_loop_never_exceeds_three_attempts():
    provider = FakeAvailabilityProvider(available_slots=set())
    avail, sink = _run(provider)
    assert avail.attempts == C.AV_MAX_ATTEMPTS
    # The staff search node must not have run a 4th time.
    assert sink.statuses(C.AV_SEARCH_STAFF).count("running") == 3


def test_every_step_emits_running_and_success():
    staff = [Staff("s1", "Alex")]
    provider = FakeAvailabilityProvider(
        available_slots=set(),
        staff_by_day={REQ_DATE: staff},
        slots_by_day={REQ_DATE: [Slot(date=REQ_DATE, time="11:00", staff_id="s1")]},
    )
    avail, sink = _run(provider)

    for node in (
        C.AV_CHECK_REQUESTED,
        C.AV_SEARCH_STAFF,
        C.AV_SEARCH_SAME_DAY,
        C.AV_SEARCH_NEXT_DAY,
        C.AV_RANK,
        C.AV_DECISION,
    ):
        assert sink.statuses(node) == ["running", "success"], node
    # Events carry duration.
    assert all(e.duration_ms is not None for e in sink.events if e.status == "success")


def test_generative_provider_returns_no_slots_without_staff():
    from app.graph.availability_provider import GenerativeFakeProvider

    assert GenerativeFakeProvider().slots_for_day("2026-06-20", []) == []


def test_default_generative_provider_finds_alternative():
    # Module-level subgraph (default provider) should make progress.
    graph = build_availability_subgraph()
    final = graph.invoke({"run_id": "r", "requested_slot": _requested()})
    avail = final["availability"]
    assert avail.escalate is False
    assert avail.chosen_slot is not None
