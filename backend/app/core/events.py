"""Pub/sub event bus for live run streaming.

Node transitions are published per ``run_id``; SSE connections subscribe to a
thread-safe queue. Event shapes:
  {"type": "event", "node": str, "status": str, "duration_ms": int|None}
  {"type": "end",   "status": str}   # terminal — run reached a boundary

``EventBus`` is in-process (single worker); ``RedisEventBus`` fans events out
across replicas so an SSE client sees events from whichever replica ran the node.
``build_event_bus`` picks one by config.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading

from ..graph.instrumentation import RunEventRecord

END_TYPE = "end"
EVENT_TYPE = "event"


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def subscribe(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(run_id)
            if subs and q in subs:
                subs.remove(q)
            if subs is not None and not subs:
                self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers.get(run_id, []))
        for q in subs:
            q.put(event)

    def close(self, run_id: str, status: str) -> None:
        self.publish(run_id, {"type": END_TYPE, "status": status})


# Process-wide bus singleton (single-worker deployments).
bus = EventBus()


_CHANNEL_PREFIX = "run-events:"


class RedisEventBus:
    """Cross-replica bus over Redis pub/sub, drop-in for ``EventBus``.

    Each ``run_id`` maps to a Redis channel; a per-run asyncio reader feeds a
    local ``queue.Queue`` so the synchronous SSE generator consumes it exactly
    as the in-process bus. A dedicated background loop owns all redis.asyncio
    I/O — the rest of the app stays synchronous."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._readers: dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()
        # Own event loop on a daemon thread: redis.asyncio lives here, sync callers
        # hand work over via run_coroutine_threadsafe.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"{_CHANNEL_PREFIX}{run_id}"

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def subscribe(self, run_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            subs = self._subscribers.setdefault(run_id, [])
            subs.append(q)
            first = len(subs) == 1
        if first:
            # One Redis subscription per run feeds all local subscriber queues.
            self._readers[run_id] = self._run(self._start_reader(run_id))
        return q

    async def _start_reader(self, run_id: str) -> asyncio.Task:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(run_id))
        return self._loop.create_task(self._reader(run_id, pubsub))

    async def _reader(self, run_id: str, pubsub) -> None:
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue  # subscribe/unsubscribe acks
                event = json.loads(message["data"])
                with self._lock:
                    subs = list(self._subscribers.get(run_id, []))
                for q in subs:
                    q.put(event)
        finally:
            # Runs on cancellation (last subscriber left): release the channel.
            await pubsub.unsubscribe(self._channel(run_id))
            await pubsub.aclose()

    def unsubscribe(self, run_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(run_id)
            if subs and q in subs:
                subs.remove(q)
            last = subs is not None and not subs
            if last:
                self._subscribers.pop(run_id, None)
                reader = self._readers.pop(run_id, None)
        if last and reader is not None:
            self._run(self._cancel_reader(reader))

    async def _cancel_reader(self, reader: asyncio.Task) -> None:
        # Await the cancellation so the reader's cleanup (channel unsubscribe)
        # finishes before we return — no dangling subscription.
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass

    def publish(self, run_id: str, event: dict) -> None:
        self._run(self._redis.publish(self._channel(run_id), json.dumps(event)))

    def close(self, run_id: str, status: str) -> None:
        self.publish(run_id, {"type": END_TYPE, "status": status})


def build_event_bus(settings):
    """In-process bus by default; a shared Redis bus when REDIS_URL is set so SSE
    clients see events regardless of which replica ran the node."""
    if not settings.redis_enabled:
        return bus
    import redis.asyncio as aioredis

    return RedisEventBus(aioredis.from_url(settings.redis_url))


class BusEventSink:
    """EventSink that republishes run events onto the bus for live SSE."""

    def __init__(self, event_bus: EventBus | RedisEventBus):
        self._bus = event_bus

    def emit(self, record: RunEventRecord) -> None:
        self._bus.publish(
            record.run_id,
            {
                "type": EVENT_TYPE,
                "node": record.node,
                "status": record.status,
                "duration_ms": record.duration_ms,
            },
        )
