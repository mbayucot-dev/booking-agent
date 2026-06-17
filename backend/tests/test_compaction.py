"""Context compaction: keep system + summary + last N + memories; never the
full history."""

from app.services.compaction import (
    KEEP_LAST,
    MAX_MEMORIES,
    CompactedContext,
    compact,
    needs_compaction,
    summarize,
)


def _msgs(n: int) -> list[dict]:
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


def test_short_history_unchanged():
    msgs = _msgs(3)
    ctx = compact(system="sys", messages=msgs)
    assert ctx.messages == msgs
    assert ctx.summary == ""


def test_long_history_is_compacted():
    msgs = _msgs(25)
    ctx = compact(system="sys", messages=msgs)
    assert len(ctx.messages) == KEEP_LAST  # only the tail kept
    assert ctx.messages[-1]["content"] == "m24"
    assert ctx.summary  # older folded into summary
    # The dropped messages are NOT in the tail (never sent in full).
    assert {m["content"] for m in ctx.messages}.isdisjoint({"m0", "m1", "m14"})


def test_merges_prior_summary():
    ctx = compact(system="sys", messages=_msgs(15), summary="earlier stuff")
    assert ctx.summary.startswith("earlier stuff")


def test_memories_are_capped():
    many = [{"type": "preference", "content": i} for i in range(MAX_MEMORIES + 30)]
    ctx = compact(system="sys", messages=[], memories=many)
    assert len(ctx.memories) == MAX_MEMORIES  # prompt stays bounded
    ctx2 = compact(system="sys", messages=_msgs(20), memories=many, max_memories=5)
    assert len(ctx2.memories) == 5  # explicit cap honored on the compacted path too


def test_needs_compaction():
    assert needs_compaction(_msgs(KEEP_LAST + 1)) is True
    assert needs_compaction(_msgs(KEEP_LAST)) is False


def test_summarize_empty():
    assert summarize([]) == ""


def test_to_messages_includes_system_summary_memories_and_tail():
    ctx = CompactedContext(
        system="sys",
        summary="prior",
        messages=[{"role": "user", "content": "hi"}],
        memories=[{"type": "vip", "content": {"tier": "gold"}}],
    )
    out = ctx.to_messages()
    roles = [m["role"] for m in out]
    assert roles[0] == "system"
    assert any("Summary so far" in m["content"] for m in out)
    assert any("Known customer facts" in m["content"] for m in out)
    assert out[-1]["content"] == "hi"
