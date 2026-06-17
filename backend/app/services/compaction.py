"""Context compaction.

Keeps the LLM context bounded: system prompt + a rolling summary of older turns
+ the last N messages + relevant long-term memories. Older messages are folded
into the summary rather than re-sent, so we never ship the full history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KEEP_LAST = 10
MAX_MEMORIES = 20  # cap long-term facts injected into context (bounds prompt size)


@dataclass
class CompactedContext:
    system: str
    summary: str
    messages: list[dict]
    memories: list[dict] = field(default_factory=list)

    def to_messages(self) -> list[dict]:
        """Flatten into a provider-ready message list (system → summary → tail)."""
        out: list[dict] = [{"role": "system", "content": self.system}]
        if self.summary:
            out.append({"role": "system", "content": f"Summary so far: {self.summary}"})
        if self.memories:
            facts = "; ".join(f"{m.get('type')}={m.get('content')}" for m in self.memories)
            out.append({"role": "system", "content": f"Known customer facts: {facts}"})
        out.extend(self.messages)
        return out


def needs_compaction(messages: list[dict], keep_last: int = KEEP_LAST) -> bool:
    return len(messages) > keep_last


def summarize(messages: list[dict]) -> str:
    """Cheap deterministic summary of older messages."""
    if not messages:
        return ""
    return f"{len(messages)} earlier message(s) exchanged."


def compact(
    *,
    system: str,
    messages: list[dict],
    summary: str = "",
    memories: list[dict] | None = None,
    keep_last: int = KEEP_LAST,
    max_memories: int = MAX_MEMORIES,
) -> CompactedContext:
    """Return a bounded context: older-than-last-N messages are summarised into
    ``summary`` and dropped from the tail; memories are capped at ``max_memories``."""
    memories = (memories or [])[:max_memories]
    if len(messages) <= keep_last:
        return CompactedContext(system, summary, list(messages), memories)

    older = messages[:-keep_last]
    tail = messages[-keep_last:]
    new_summary = summarize(older)
    merged = f"{summary} {new_summary}".strip() if summary else new_summary
    return CompactedContext(system, merged, tail, memories)
