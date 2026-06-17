"""Memory seam for the graph layer.

Long-term memory stores ONLY durable customer facts — preferences,
communication preferences, VIP status, repeated constraints — never logs, tool
output, or transient slots. ``ALLOWED_MEMORY_TYPES`` is the whitelist; anything
else is dropped at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

ALLOWED_MEMORY_TYPES = frozenset({"preference", "communication", "vip", "constraint"})


@dataclass
class Memory:
    customer_key: str
    memory_type: str
    content: dict


def is_savable(memory: Memory) -> bool:
    return memory.memory_type in ALLOWED_MEMORY_TYPES


class MemoryStore(Protocol):
    def save(self, memory: Memory) -> bool: ...

    def load(self, customer_key: str) -> list[Memory]: ...


@dataclass
class InMemoryMemoryStore:
    """Dict-backed store for tests. Enforces the whitelist + upsert-by-type."""

    saved: dict[str, dict[str, Memory]] = field(default_factory=dict)

    def save(self, memory: Memory) -> bool:
        if not is_savable(memory):
            return False
        self.saved.setdefault(memory.customer_key, {})[memory.memory_type] = memory
        return True

    def load(self, customer_key: str) -> list[Memory]:
        return list(self.saved.get(customer_key, {}).values())
