import { useQuery } from "@tanstack/react-query";

import { getRunNodes } from "../lib/api";
import type { NodeDetail } from "../lib/types";

/**
 * Fetches per-node execution detail (status + produced output) for the
 * clickable node-preview panel. Enabled only while the panel is open so we
 * don't fetch payloads no one is looking at.
 */
export function useRunNodes(runId: string | null, enabled: boolean) {
  return useQuery<NodeDetail[]>({
    queryKey: ["run", runId, "nodes"],
    queryFn: () => getRunNodes(runId as string),
    enabled: !!runId && enabled,
    // One retry: a transient blip shouldn't surface as a permanent empty panel.
    retry: 1,
    retryDelay: 1000,
  });
}
