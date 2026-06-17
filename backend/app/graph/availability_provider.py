"""Availability data source for the subgraph.

Deterministic synthetic providers behind a Protocol, so the subgraph has no real
I/O and tests can inject precise scenarios. The app uses the DB-backed
DbAvailabilityProvider (services/availability.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

from .state import Slot


@dataclass(frozen=True)
class Staff:
    id: str
    name: str
    skills: tuple[str, ...] = ()
    latitude: float | None = None
    longitude: float | None = None


def add_days(date_iso: str, days: int) -> str:
    return (date.fromisoformat(date_iso) + timedelta(days=days)).isoformat()


class AvailabilityProvider(Protocol):
    def is_available(self, slot: Slot) -> bool: ...

    def staff_for_day(self, date_iso: str) -> list[Staff]: ...

    def slots_for_day(self, date_iso: str, staff: list[Staff]) -> list[Slot]: ...


@dataclass
class FakeAvailabilityProvider:
    """Config-driven fake for precise tests.

    Anything not explicitly listed is unavailable. ``slots_for_day`` only
    returns a slot if its ``staff_id`` is among the staff available that day
    (so "search same-day staff" meaningfully gates "search same-day slots").
    """

    available_slots: set[tuple[str, str]] = field(default_factory=set)
    staff_by_day: dict[str, list[Staff]] = field(default_factory=dict)
    slots_by_day: dict[str, list[Slot]] = field(default_factory=dict)

    def is_available(self, slot: Slot) -> bool:
        return (slot.date, slot.time) in self.available_slots

    def staff_for_day(self, date_iso: str) -> list[Staff]:
        return list(self.staff_by_day.get(date_iso, []))

    def slots_for_day(self, date_iso: str, staff: list[Staff]) -> list[Slot]:
        staff_ids = {s.id for s in staff}
        return [
            s
            for s in self.slots_by_day.get(date_iso, [])
            if s.staff_id is None or s.staff_id in staff_ids
        ]


@dataclass
class GenerativeFakeProvider:
    """Default/demo provider: requested slot is busy, but every queried day has
    one staff member offering a couple of alternative slots."""

    times: tuple[str, ...] = ("09:00", "13:00")
    staff: tuple[Staff, ...] = (Staff("s1", "Alex Taylor"),)

    def is_available(self, slot: Slot) -> bool:
        return False

    def staff_for_day(self, date_iso: str) -> list[Staff]:
        return list(self.staff)

    def slots_for_day(self, date_iso: str, staff: list[Staff]) -> list[Slot]:
        if not staff:
            return []
        s = staff[0]
        return [Slot(date=date_iso, time=t, staff_id=s.id, staff_name=s.name) for t in self.times]
