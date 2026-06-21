import { useMutation, useQueryClient } from "@tanstack/react-query";

import { approveRun, rejectRun } from "../lib/api";
import type { RunResponse } from "../lib/types";

/**
 * Approve / reject mutations for a paused run. Both write the returned
 * RunResponse back into the query cache so the UI reflects the new state.
 */
export function useApproval(runId: string | null) {
  const queryClient = useQueryClient();

  const onSettled = (run: RunResponse | undefined) => {
    if (!run) return;
    // Merge, don't replace: approve/reject return a stripped RunResponse (empty
    // node_statuses), so keep the locally-known statuses until the SSE replay
    // repopulates them — otherwise the canvas flashes blank between click and replay.
    queryClient.setQueryData<RunResponse>(["run", run.run_id], (prev) =>
      prev
        ? { ...prev, ...run, node_statuses: { ...prev.node_statuses, ...run.node_statuses } }
        : run,
    );
  };

  const approve = useMutation({
    mutationFn: () => approveRun(runId as string),
    onSuccess: onSettled,
  });

  const reject = useMutation({
    mutationFn: (reason?: string) => rejectRun(runId as string, reason),
    onSuccess: onSettled,
  });

  return { approve, reject };
}
