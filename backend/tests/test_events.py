"""In-process event bus + BusEventSink."""

import threading

from app.core.events import BusEventSink, EventBus
from app.graph.instrumentation import RunEventRecord


def test_subscribe_receives_published_events():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.publish("r1", {"type": "event", "node": "extract", "status": "running"})
    assert q.get_nowait()["node"] == "extract"


def test_publish_isolated_per_run():
    bus = EventBus()
    q1 = bus.subscribe("r1")
    bus.subscribe("r2")
    bus.publish("r2", {"type": "event", "node": "x", "status": "running"})
    assert q1.empty()


def test_close_publishes_terminal():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.close("r1", "completed")
    end = q.get_nowait()
    assert end == {"type": "end", "status": "completed"}


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    q = bus.subscribe("r1")
    bus.unsubscribe("r1", q)
    bus.publish("r1", {"type": "event", "node": "x", "status": "running"})
    assert q.empty()


def test_multiple_subscribers_each_receive():
    bus = EventBus()
    q1, q2 = bus.subscribe("r1"), bus.subscribe("r1")
    bus.publish("r1", {"type": "event", "node": "x", "status": "success"})
    assert q1.get_nowait()["node"] == "x"
    assert q2.get_nowait()["node"] == "x"


def test_cross_thread_publish_received():
    bus = EventBus()
    q = bus.subscribe("r1")
    threading.Thread(
        target=lambda: bus.publish("r1", {"type": "event", "node": "t", "status": "running"})
    ).start()
    assert q.get(timeout=2)["node"] == "t"


def test_bus_event_sink_republishes_records():
    bus = EventBus()
    q = bus.subscribe("r1")
    BusEventSink(bus).emit(
        RunEventRecord(run_id="r1", node="email_agent", status="success", duration_ms=5)
    )
    event = q.get_nowait()
    assert event == {
        "type": "event",
        "node": "email_agent",
        "status": "success",
        "duration_ms": 5,
    }
