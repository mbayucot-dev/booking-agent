"""Long-term memory: whitelist enforcement, store/repo, node, and load-on-run."""

from app.graph.memory import (
    ALLOWED_MEMORY_TYPES,
    InMemoryMemoryStore,
    Memory,
    is_savable,
)
from app.graph.nodes.customer_agent import make_customer_agent
from app.graph.nodes.memory_agent import _derive, make_memory_agent
from app.graph.state import BookingRequest
from app.models import CustomerMemory
from app.persistence import DbMemoryStore
from app.repositories.memory import MemoryRepository

REQ = BookingRequest(
    customer_name="John Doe",
    service="contact work",
    email="john@example.com",
    phone="0400000000",
)


# --- whitelist ------------------------------------------------------------


def test_only_whitelisted_types_savable():
    assert ALLOWED_MEMORY_TYPES == {"preference", "communication", "vip", "constraint"}
    assert is_savable(Memory("john@x", "preference", {}))
    assert not is_savable(Memory("john@x", "log", {}))  # logs never saved
    assert not is_savable(Memory("john@x", "tool_output", {}))


def test_in_memory_store_rejects_disallowed():
    store = InMemoryMemoryStore()
    assert store.save(Memory("k", "communication", {"channel": "email"})) is True
    assert store.save(Memory("k", "debug_dump", {"big": "data"})) is False
    assert [m.memory_type for m in store.load("k")] == ["communication"]


# --- DB store + repository ------------------------------------------------


def test_db_memory_store_roundtrip(Session):
    store = DbMemoryStore(Session)
    assert store.save(Memory("john@example.com", "vip", {"tier": "gold"})) is True
    assert store.save(Memory("john@example.com", "secrets", {"x": 1})) is False

    loaded = store.load("john@example.com")
    assert len(loaded) == 1
    assert loaded[0].memory_type == "vip"
    with Session() as s:
        assert s.query(CustomerMemory).count() == 1


def test_repository_upsert_updates_existing(Session):
    with Session() as s:
        repo = MemoryRepository(s)
        repo.upsert("k", "preference", {"last_service": "a"})
        repo.upsert("k", "preference", {"last_service": "b"})  # same key+type
        rows = repo.list_for("k")
    assert len(rows) == 1
    assert rows[0].content["last_service"] == "b"


# --- node + load ----------------------------------------------------------


def test_memory_agent_derives_and_saves():
    store = InMemoryMemoryStore()
    node = make_memory_agent(store)
    out = node({"run_id": "r1", "booking_request": REQ})
    assert out["memory"]["saved"] == 2  # communication + preference
    types = {m.memory_type for m in store.load("john@example.com")}
    assert types == {"communication", "preference"}


def test_memory_agent_no_email_saves_nothing():
    store = InMemoryMemoryStore()
    node = make_memory_agent(store)
    out = node({"run_id": "r1", "booking_request": BookingRequest(customer_name="X")})
    assert out["memory"]["saved"] == 0


def test_derive_empty_without_request():
    assert _derive({}) == []


def test_customer_agent_loads_prior_memories():
    store = InMemoryMemoryStore()
    store.save(Memory("john@example.com", "vip", {"tier": "gold"}))
    agent = make_customer_agent(store)
    out = agent({"booking_request": REQ})
    assert out["customer"]["matched"] is True
    assert {m["type"] for m in out["customer_memories"]} == {"vip"}


def test_customer_agent_no_memories_for_new_customer():
    agent = make_customer_agent(InMemoryMemoryStore())
    out = agent({"booking_request": REQ})
    assert out["customer"]["matched"] is False
    assert out["customer_memories"] == []


# --- preference capture + backfill ----------------------------------------


def test_memory_agent_saves_preference_note():
    store = InMemoryMemoryStore()
    req = REQ.model_copy(update={"preferences": "calm with anxious dogs"})
    make_memory_agent(store)({"run_id": "r1", "booking_request": req})
    pref = next(m for m in store.load("john@example.com") if m.memory_type == "preference")
    assert pref.content["note"] == "calm with anxious dogs"
    assert pref.content["last_service"] == "contact work"


def test_customer_agent_backfills_preference_from_memory():
    store = InMemoryMemoryStore()
    store.save(Memory("john@example.com", "preference", {"note": "fragrance-free"}))
    # Returning customer who didn't restate the note this time.
    out = make_customer_agent(store)(
        {"booking_request": REQ.model_copy(update={"preferences": None})}
    )
    assert out["booking_request"].preferences == "fragrance-free"


def test_customer_agent_keeps_explicit_preference_over_memory():
    store = InMemoryMemoryStore()
    store.save(Memory("john@example.com", "preference", {"note": "old note"}))
    req = REQ.model_copy(update={"preferences": "fresh note this time"})
    out = make_customer_agent(store)({"booking_request": req})
    assert "booking_request" not in out  # explicit preference kept; no backfill
