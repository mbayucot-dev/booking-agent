import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useRun } from "./useRun";
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
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(qc: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => vi.restoreAllMocks());

describe("useRun", () => {
  test("fetches and returns the run when a runId is provided", async () => {
    vi.spyOn(api, "getRun").mockResolvedValue(RUN);
    const qc = makeClient();
    const { result } = renderHook(() => useRun("run_1"), { wrapper: wrap(qc) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(RUN);
    expect(api.getRun).toHaveBeenCalledWith("run_1");
  });

  test("does not fetch when runId is null", () => {
    const spy = vi.spyOn(api, "getRun").mockResolvedValue(RUN);
    const qc = makeClient();
    const { result } = renderHook(() => useRun(null), { wrapper: wrap(qc) });
    expect(result.current.fetchStatus).toBe("idle");
    expect(spy).not.toHaveBeenCalled();
  });
});
