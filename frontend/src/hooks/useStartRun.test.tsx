import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useStartRun } from "./useStartRun";
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
  return new QueryClient({ defaultOptions: { mutations: { retry: false } } });
}

function wrap(qc: QueryClient) {
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => vi.restoreAllMocks());

describe("useStartRun", () => {
  test("POSTs the message and seeds the cache, then calls onStarted", async () => {
    vi.spyOn(api, "startRun").mockResolvedValue(RUN);
    const qc = makeClient();
    const onStarted = vi.fn();

    const { result } = renderHook(() => useStartRun(onStarted), { wrapper: wrap(qc) });
    act(() => result.current.mutate("book a cleaner"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(api.startRun).toHaveBeenCalledWith("book a cleaner");
    expect(qc.getQueryData(["run", "run_1"])).toEqual(RUN);
    expect(onStarted).toHaveBeenCalledWith(RUN);
  });

  test("works without an onStarted callback", async () => {
    vi.spyOn(api, "startRun").mockResolvedValue(RUN);
    const qc = makeClient();

    const { result } = renderHook(() => useStartRun(), { wrapper: wrap(qc) });
    act(() => result.current.mutate("book a plumber"));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(qc.getQueryData(["run", "run_1"])).toEqual(RUN);
  });
});
