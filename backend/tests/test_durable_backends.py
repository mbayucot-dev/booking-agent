"""Durable backends: config-selected Postgres checkpointer, Redis event bus,
Redis rate limiter.

Selection logic is tested with monkeypatch (third-party saver/redis internals
aren't our coverage); Redis behaviour runs end-to-end against fakeredis.
"""

from __future__ import annotations

import fakeredis
import fakeredis.aioredis as fakeaio

from app.core.config import Settings
from app.core.events import (
    EVENT_TYPE,
    EventBus,
    RedisEventBus,
    build_event_bus,
)
from app.core.events import bus as default_bus
from app.core.ratelimit import (
    FixedWindowLimiter,
    RedisFixedWindowLimiter,
    _build_limiter,
)
from app.graph import checkpointing
from app.graph.checkpointing import build_checkpointer, default_checkpointer

# --- config selection properties ------------------------------------------


def test_is_postgres_detects_postgres_urls():
    assert Settings(database_url="postgresql://u:p@h/db").is_postgres is True
    assert Settings(database_url="postgres://u:p@h/db").is_postgres is True
    assert Settings(database_url="sqlite:///./booking.db").is_postgres is False


def test_redis_enabled_follows_redis_url():
    assert Settings(redis_url="redis://localhost:6379/0").redis_enabled is True
    assert Settings().redis_enabled is False


# --- checkpointer factory selection ----------------------------------------


def test_build_checkpointer_sqlite_is_in_process():
    saver = build_checkpointer(Settings(database_url="sqlite:///./booking.db"))
    # Same in-process saver type as the unchanged default.
    assert type(saver) is type(default_checkpointer())


def test_build_checkpointer_postgres_takes_durable_path(monkeypatch):
    # Postgres URL → the durable builder is chosen and wired with the DB url.
    captured = {}

    def fake_pg(url):
        captured["url"] = url
        return "PG_SAVER"

    monkeypatch.setattr(checkpointing, "build_postgres_checkpointer", fake_pg)
    saver = build_checkpointer(Settings(database_url="postgresql://u:p@h/db"))
    assert saver == "PG_SAVER"
    assert captured["url"] == "postgresql://u:p@h/db"


def test_build_postgres_checkpointer_wires_pool_and_setup(monkeypatch):
    # The third-party saver/pool are stubbed; we assert OUR wiring: a pool built
    # from the URL, the saver built on it with our serde, and setup() called.
    events = {}

    class FakePool:
        def __init__(self, url, *, max_size, kwargs):
            events["pool_url"] = url
            events["max_size"] = max_size
            events["kwargs"] = kwargs

    class FakeSaver:
        def __init__(self, *, conn, serde):
            events["conn"] = conn
            events["serde"] = serde

        def setup(self):
            events["setup"] = True

    import langgraph.checkpoint.postgres as pg
    import psycopg_pool

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", FakePool)
    monkeypatch.setattr(pg, "PostgresSaver", FakeSaver)

    saver = checkpointing.build_postgres_checkpointer("postgresql://u:p@h/db")
    assert isinstance(saver, FakeSaver)
    assert events["pool_url"] == "postgresql://u:p@h/db"
    assert events["kwargs"]["autocommit"] is True
    assert isinstance(events["conn"], FakePool)
    assert events["serde"] is checkpointing.CHECKPOINT_SERDE
    assert events["setup"] is True


# --- Redis event bus (fakeredis) -------------------------------------------


def _redis_bus() -> RedisEventBus:
    return RedisEventBus(fakeaio.FakeRedis())


def test_redis_bus_publish_reaches_subscriber():
    bus = _redis_bus()
    q = bus.subscribe("r1")
    bus.publish("r1", {"type": EVENT_TYPE, "node": "extract", "status": "running"})
    assert q.get(timeout=2)["node"] == "extract"
    bus.unsubscribe("r1", q)


def test_redis_bus_fans_out_to_multiple_subscribers():
    bus = _redis_bus()
    q1, q2 = bus.subscribe("r1"), bus.subscribe("r1")
    bus.publish("r1", {"type": EVENT_TYPE, "node": "x", "status": "success"})
    assert q1.get(timeout=2)["node"] == "x"
    assert q2.get(timeout=2)["node"] == "x"
    bus.unsubscribe("r1", q1)
    bus.unsubscribe("r1", q2)


def test_redis_bus_close_publishes_terminal():
    bus = _redis_bus()
    q = bus.subscribe("r1")
    bus.close("r1", "completed")
    assert q.get(timeout=2) == {"type": "end", "status": "completed"}
    bus.unsubscribe("r1", q)


def test_redis_bus_unsubscribe_one_keeps_the_other():
    bus = _redis_bus()
    q1, q2 = bus.subscribe("r1"), bus.subscribe("r1")
    bus.unsubscribe("r1", q1)  # not the last subscriber: reader stays up
    bus.publish("r1", {"type": EVENT_TYPE, "node": "y", "status": "running"})
    assert q2.get(timeout=2)["node"] == "y"
    bus.unsubscribe("r1", q2)  # last subscriber: reader is cancelled


# --- event bus factory selection -------------------------------------------


def test_build_event_bus_defaults_to_in_process_singleton():
    bus = build_event_bus(Settings())
    assert bus is default_bus
    assert isinstance(bus, EventBus)


def test_build_event_bus_uses_redis_when_configured(monkeypatch):
    captured = {}

    def fake_from_url(url):
        captured["url"] = url
        return fakeaio.FakeRedis()

    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", fake_from_url)
    bus = build_event_bus(Settings(redis_url="redis://localhost:6379/0"))
    assert isinstance(bus, RedisEventBus)
    assert captured["url"] == "redis://localhost:6379/0"


# --- Redis rate limiter (fakeredis) ----------------------------------------


def test_redis_limiter_enforces_limit_and_sets_window():
    r = fakeredis.FakeStrictRedis()
    lim = RedisFixedWindowLimiter(limit=2, window_s=10, redis_client=r)
    assert lim.allow("k") is True
    assert lim.allow("k") is True
    assert lim.allow("k") is False  # third hit blocked within the window
    assert r.ttl("ratelimit:k") == 10  # the first hit set the TTL


def test_redis_limiter_count_is_shared_across_replicas():
    # Two limiter instances (two "replicas") share one Redis: the count is global.
    server = fakeredis.FakeServer()
    r1 = fakeredis.FakeStrictRedis(server=server)
    r2 = fakeredis.FakeStrictRedis(server=server)
    lim1 = RedisFixedWindowLimiter(limit=1, window_s=10, redis_client=r1)
    lim2 = RedisFixedWindowLimiter(limit=1, window_s=10, redis_client=r2)
    assert lim1.allow("k") is True
    assert lim2.allow("k") is False  # other replica already used the budget


def test_redis_limiter_window_resets_after_expiry():
    r = fakeredis.FakeStrictRedis()
    lim = RedisFixedWindowLimiter(limit=1, window_s=10, redis_client=r)
    assert lim.allow("k") is True
    assert lim.allow("k") is False
    r.delete("ratelimit:k")  # simulate the window key expiring
    assert lim.allow("k") is True  # fresh window


# --- rate limiter factory selection ----------------------------------------


def test_build_limiter_defaults_to_in_process():
    assert isinstance(_build_limiter(Settings()), FixedWindowLimiter)


def test_build_limiter_uses_redis_when_configured(monkeypatch):
    captured = {}

    def fake_from_url(url):
        captured["url"] = url
        return fakeredis.FakeStrictRedis()

    import redis

    monkeypatch.setattr(redis, "from_url", fake_from_url)
    lim = _build_limiter(Settings(redis_url="redis://localhost:6379/0", rate_limit_runs=5))
    assert isinstance(lim, RedisFixedWindowLimiter)
    assert captured["url"] == "redis://localhost:6379/0"
