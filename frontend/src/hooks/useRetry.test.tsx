import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useRetry } from "./useRetry";
import * as api from "../lib/api";
import type { RunResponse } from "../lib/types";

const RUN: RunResponse = {
  run_id: "run_1",
  status: "running",
  node_statuses: {},
  approval_card: null,
  final_response: null,
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function wrap(qc: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => vi.restoreAllMocks());

describe("useRetry", () => {
  test("on success caches the run and invalidates its node detail", async () => {
    vi.spyOn(api, "retryRun").mockResolvedValue(RUN);
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    const { result } = renderHook(() => useRetry("run_1"), { wrapper: wrap(qc) });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Merged into cache (no prior entry → equals RUN).
    expect(qc.getQueryData(["run", "run_1"])).toEqual(RUN);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["run", "run_1", "nodes"] });
  });

  test("merges retry result with cached run when prior data exists", async () => {
    // The retry endpoint returns a stripped response (empty node_statuses).
    // The prior node statuses must be preserved so the canvas doesn't flash blank.
    const retryResponse: RunResponse = { ...RUN, node_statuses: {} };
    vi.spyOn(api, "retryRun").mockResolvedValue(retryResponse);
    const qc = makeClient();
    const prior: RunResponse = { ...RUN, node_statuses: { chat_trigger: "success" }, status: "failed" };
    qc.setQueryData(["run", "run_1"], prior);

    const { result } = renderHook(() => useRetry("run_1"), { wrapper: wrap(qc) });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = qc.getQueryData<RunResponse>(["run", "run_1"]);
    expect(cached?.node_statuses).toEqual({ chat_trigger: "success" }); // prior statuses preserved
    expect(cached?.status).toBe("running"); // retry response status wins
  });

  test("does not POST when there is no active run", async () => {
    const spy = vi.spyOn(api, "retryRun").mockResolvedValue(RUN);
    const qc = makeClient();
    const { result } = renderHook(() => useRetry(null), { wrapper: wrap(qc) });
    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(spy).not.toHaveBeenCalled();
  });
});
