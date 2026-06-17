import { useMutation, useQueryClient } from "@tanstack/react-query";

import { retryRun } from "../lib/api";
import type { RunResponse } from "../lib/types";

/**
 * Retry a failed run — resumes it from the backend checkpoint. The result is
 * written back into the query cache so the UI reflects the new (running) state.
 */
export function useRetry(runId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      runId ? retryRun(runId) : Promise.reject(new Error("No active run")),
    onSuccess: (run) => {
      // Merge, don't replace: retry returns a stripped RunResponse (empty
      // node_statuses); keep the failed attempt's statuses until the SSE replay
      // repopulates them so the canvas doesn't flash blank.
      queryClient.setQueryData<RunResponse>(["run", run.run_id], (prev) =>
        prev
          ? { ...prev, ...run, node_statuses: { ...prev.node_statuses, ...run.node_statuses } }
          : run,
      );
      // Drop the previous attempt's per-node output so an open panel refreshes.
      queryClient.invalidateQueries({ queryKey: ["run", run.run_id, "nodes"] });
    },
  });
}
