import { useMutation, useQueryClient } from "@tanstack/react-query";

import { startRun } from "../lib/api";
import type { RunResponse } from "../lib/types";

/**
 * Submits a booking message to POST /runs. On success the caller receives the
 * RunResponse (containing the run_id) so it can set the active run.
 */
export function useStartRun(onStarted?: (run: RunResponse) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => startRun(message),
    onSuccess: (run) => {
      queryClient.setQueryData(["run", run.run_id], run);
      onStarted?.(run);
    },
  });
}
