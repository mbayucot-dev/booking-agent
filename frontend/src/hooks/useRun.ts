import { useQuery } from "@tanstack/react-query";

import { getRun } from "../lib/api";
import type { RunResponse } from "../lib/types";

/** Polls / fetches the current state of a run. Disabled until a runId exists. */
export function useRun(runId: string | null) {
  return useQuery<RunResponse>({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId as string),
    enabled: !!runId,
  });
}
