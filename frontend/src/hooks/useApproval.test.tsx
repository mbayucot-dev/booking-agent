import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useApproval } from "./useApproval";
import * as api from "../lib/api";
import type { RunResponse } from "../lib/types";

const RUN_RUNNING: RunResponse = {
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

describe("useApproval", () => {
  test("approve: writes result to cache when no prior data", async () => {
    vi.spyOn(api, "approveRun").mockResolvedValue(RUN_RUNNING);
    const qc = makeClient();
    const { result } = renderHook(() => useApproval("run_1"), { wrapper: wrap(qc) });

    act(() => result.current.approve.mutate());
    await waitFor(() => expect(result.current.approve.isSuccess).toBe(true));

    expect(qc.getQueryData(["run", "run_1"])).toEqual(RUN_RUNNING);
  });

  test("approve: merges result preserving prior node_statuses", async () => {
    // The approve endpoint returns a stripped RunResponse (empty node_statuses).
    // The prior canvas state must be kept so the UI doesn't flash blank.
    const approveResponse: RunResponse = { ...RUN_RUNNING, node_statuses: {} };
    vi.spyOn(api, "approveRun").mockResolvedValue(approveResponse);
    const qc = makeClient();
    const prior: RunResponse = {
      ...RUN_RUNNING,
      status: "paused",
      node_statuses: { chat_trigger: "success", human_approval: "waiting_approval" },
    };
    qc.setQueryData(["run", "run_1"], prior);

    const { result } = renderHook(() => useApproval("run_1"), { wrapper: wrap(qc) });
    act(() => result.current.approve.mutate());
    await waitFor(() => expect(result.current.approve.isSuccess).toBe(true));

    const cached = qc.getQueryData<RunResponse>(["run", "run_1"]);
    expect(cached?.node_statuses).toEqual({
      chat_trigger: "success",
      human_approval: "waiting_approval",
    });
    expect(cached?.status).toBe("running"); // new status from server
  });

  test("reject: POSTs the reason and writes to cache", async () => {
    vi.spyOn(api, "rejectRun").mockResolvedValue(RUN_RUNNING);
    const qc = makeClient();
    const { result } = renderHook(() => useApproval("run_1"), { wrapper: wrap(qc) });

    act(() => result.current.reject.mutate("slot taken"));
    await waitFor(() => expect(result.current.reject.isSuccess).toBe(true));

    expect(api.rejectRun).toHaveBeenCalledWith("run_1", "slot taken");
    expect(qc.getQueryData(["run", "run_1"])).toEqual(RUN_RUNNING);
  });

  test("does nothing when onSettled receives undefined", async () => {
    // useMutation calls onSuccess only on success; if the response is undefined
    // (edge-case type error) the cache must not be cleared.
    vi.spyOn(api, "approveRun").mockResolvedValue(undefined as unknown as RunResponse);
    const qc = makeClient();
    const prior: RunResponse = { ...RUN_RUNNING, status: "paused" };
    qc.setQueryData(["run", "run_1"], prior);

    const { result } = renderHook(() => useApproval("run_1"), { wrapper: wrap(qc) });
    act(() => result.current.approve.mutate());
    await waitFor(() => expect(result.current.approve.isSuccess).toBe(true));

    // Cache should be untouched because onSettled early-returns on undefined.
    expect(qc.getQueryData(["run", "run_1"])).toEqual(prior);
  });
});
