"""Audit-writer abstraction for the graph layer.

Like :class:`EventSink`, this is a seam so graph nodes can record an audit
trail without depending on the database. ``DbAuditWriter`` (in app.persistence)
satisfies this structural protocol; tests use :class:`InMemoryAuditWriter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class AuditWriter(Protocol):
    def write(self, entry: dict) -> None: ...


class NullAuditWriter:
    def write(self, entry: dict) -> None:  # noqa: D401
        return None


@dataclass
class InMemoryAuditWriter:
    entries: list[dict] = field(default_factory=list)

    def write(self, entry: dict) -> None:
        self.entries.append(entry)
