import {
  describe,
  test,
  expect,
  vi,
  beforeEach,
  afterEach,
} from "vitest";
import { act, renderHook } from "@testing-library/react";

import {
  parseRunEvent,
  reduceEvent,
  useRunStream,
  type StatusMap,
} from "./useRunStream";

// --- Mock EventSource ---------------------------------------------------

type Listener = (e: unknown) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  listeners: Record<string, Listener[]> = {};

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: Listener) {
    (this.listeners[type] ??= []).push(cb);
  }
  removeEventListener(type: string, cb: Listener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== cb);
  }
  close() {
    this.closed = true;
  }

  emitMessage(data: string) {
    for (const l of this.listeners["message"] ?? []) l({ data });
  }
  emitEnd() {
    for (const l of this.listeners["end"] ?? []) l({ data: "{}" });
  }
  emitError() {
    for (const l of this.listeners["error"] ?? []) l({});
  }

  static last() {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
  static reset() {
    MockEventSource.instances = [];
  }
}

describe("parseRunEvent / reduceEvent", () => {
  test("parses a valid event", () => {
    expect(
      parseRunEvent('{"node":"extract_booking_request","status":"running","duration_ms":12}'),
    ).toEqual({
      node: "extract_booking_request",
      status: "running",
      duration_ms: 12,
    });
  });

  test("coerces missing duration to null", () => {
    expect(
      parseRunEvent('{"node":"validation_agent","status":"success"}'),
    ).toEqual({ node: "validation_agent", status: "success", duration_ms: null });
  });

  test("rejects invalid status and malformed json", () => {
    expect(parseRunEvent('{"node":"x","status":"bogus"}')).toBeNull();
    expect(parseRunEvent("not json")).toBeNull();
    expect(parseRunEvent('{"status":"running"}')).toBeNull();
  });

  test("reduceEvent folds immutably", () => {
    const a: StatusMap = { foo: "idle" };
    const b = reduceEvent(a, { node: "bar", status: "running", duration_ms: null });
    expect(b).toEqual({ foo: "idle", bar: "running" });
    expect(a).toEqual({ foo: "idle" });
  });
});

describe("useRunStream", () => {
  beforeEach(() => {
    MockEventSource.reset();
    vi.stubGlobal("EventSource", MockEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("does nothing without a runId", () => {
    const { result } = renderHook(() => useRunStream(null));
    expect(result.current.statuses).toEqual({});
    expect(MockEventSource.instances).toHaveLength(0);
  });

  test("reduces incoming events into a status map and event log", () => {
    const { result } = renderHook(() => useRunStream("run_1"));
    const es = MockEventSource.last();

    act(() => {
      es.emitMessage('{"node":"chat_trigger","status":"success","duration_ms":5}');
      es.emitMessage('{"node":"extract_booking_request","status":"running","duration_ms":null}');
    });

    expect(result.current.statuses).toEqual({
      chat_trigger: "success",
      extract_booking_request: "running",
    });
    expect(result.current.events).toHaveLength(2);
  });

  test("ignores malformed events", () => {
    const { result } = renderHook(() => useRunStream("run_1"));
    const es = MockEventSource.last();
    act(() => {
      es.emitMessage("garbage");
      es.emitMessage('{"node":"x","status":"bogus"}');
    });
    expect(result.current.statuses).toEqual({});
    expect(result.current.events).toHaveLength(0);
  });

  test("calls onEnd and closes on end event", () => {
    const onEnd = vi.fn();
    renderHook(() => useRunStream("run_1", onEnd));
    const es = MockEventSource.last();
    act(() => {
      es.emitEnd();
    });
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(es.closed).toBe(true);
  });

  test("closes the EventSource on unmount", () => {
    const { unmount } = renderHook(() => useRunStream("run_1"));
    const es = MockEventSource.last();
    unmount();
    expect(es.closed).toBe(true);
  });

  test("opens a new EventSource and resets state when runId changes", () => {
    const { result, rerender } = renderHook(
      ({ id }) => useRunStream(id),
      { initialProps: { id: "run_1" } },
    );
    const first = MockEventSource.last();
    act(() => {
      first.emitMessage('{"node":"chat_trigger","status":"success"}');
    });
    expect(result.current.statuses.chat_trigger).toBe("success");

    rerender({ id: "run_2" });
    expect(first.closed).toBe(true);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(result.current.statuses).toEqual({});
  });

  test("surfaces an error and stops on a stream failure", () => {
    const onEnd = vi.fn();
    const { result } = renderHook(() => useRunStream("run_1", onEnd));
    const es = MockEventSource.last();
    act(() => {
      es.emitError();
    });
    expect(result.current.error).toBe(true);
    expect(es.closed).toBe(true);
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  test("reopens a fresh EventSource when the epoch is bumped", () => {
    const { result, rerender } = renderHook(
      ({ epoch }) => useRunStream("run_1", undefined, epoch),
      { initialProps: { epoch: 0 } },
    );
    const first = MockEventSource.last();
    act(() => {
      first.emitMessage('{"node":"chat_trigger","status":"success"}');
    });
    expect(result.current.statuses.chat_trigger).toBe("success");

    rerender({ epoch: 1 });
    expect(first.closed).toBe(true);
    expect(MockEventSource.instances).toHaveLength(2);
    expect(result.current.statuses).toEqual({}); // reset; reconnect replays from DB
  });
});
