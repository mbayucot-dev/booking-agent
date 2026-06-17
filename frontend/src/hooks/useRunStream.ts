import { useEffect, useRef, useState } from "react";

import { runEventsUrl } from "../lib/api";
import { isNodeStatus, type NodeStatus } from "../flow/nodeStatus";

export interface RunEvent {
  node: string;
  status: NodeStatus;
  duration_ms: number | null;
}

export type StatusMap = Record<string, NodeStatus>;

/** Parse a single SSE `data:` payload into a RunEvent, or null if invalid. */
export function parseRunEvent(raw: string): RunEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const obj = parsed as Record<string, unknown>;
  if (typeof obj.node !== "string" || !isNodeStatus(obj.status)) return null;
  const duration =
    typeof obj.duration_ms === "number" ? obj.duration_ms : null;
  return { node: obj.node, status: obj.status, duration_ms: duration };
}

/** Fold an event into a status map (pure; used by the hook and tests). */
export function reduceEvent(map: StatusMap, event: RunEvent): StatusMap {
  return { ...map, [event.node]: event.status };
}

export interface UseRunStreamResult {
  statuses: StatusMap;
  events: RunEvent[];
  /** True if the stream errored (connection/server failure) before it ended. */
  error: boolean;
}

/**
 * Opens an EventSource to the run's SSE endpoint, reducing each event into a
 * node->status map and an ordered log. Calls `onEnd` on completion.
 *
 * The stream closes at each run boundary; bumping `epoch` reopens it (after
 * approve/reject/retry) so the post-boundary execution streams live — the SSE
 * endpoint replays the persisted timeline on reconnect.
 */
export function useRunStream(
  runId: string | null,
  onEnd?: () => void,
  epoch: number = 0,
): UseRunStreamResult {
  const [statuses, setStatuses] = useState<StatusMap>({});
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState(false);
  const onEndRef = useRef(onEnd);
  onEndRef.current = onEnd;

  useEffect(() => {
    if (!runId) {
      setStatuses({});
      setEvents([]);
      setError(false);
      return;
    }

    // Reset accumulated state; the reconnect replays the full persisted timeline.
    setStatuses({});
    setEvents([]);
    setError(false);

    const source = new EventSource(runEventsUrl(runId));

    const handleMessage = (e: MessageEvent) => {
      const event = parseRunEvent(e.data);
      if (!event) return;
      setStatuses((prev) => reduceEvent(prev, event));
      setEvents((prev) => [...prev, event]);
    };

    const handleEnd = () => {
      source.close();
      onEndRef.current?.();
    };

    // Connection/server failure before the run reached a boundary: stop (don't
    // silently auto-reconnect forever) and surface it; refetch the snapshot so
    // the UI reflects the run's authoritative status.
    const handleError = () => {
      source.close();
      setError(true);
      onEndRef.current?.();
    };

    source.addEventListener("message", handleMessage as EventListener);
    source.addEventListener("end", handleEnd as EventListener);
    source.addEventListener("error", handleError as EventListener);

    return () => {
      source.removeEventListener("message", handleMessage as EventListener);
      source.removeEventListener("end", handleEnd as EventListener);
      source.removeEventListener("error", handleError as EventListener);
      source.close();
    };
  }, [runId, epoch]);

  return { statuses, events, error };
}
