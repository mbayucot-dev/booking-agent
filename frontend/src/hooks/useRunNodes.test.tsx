import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useRunNodes } from "./useRunNodes";
import * as api from "../lib/api";
import type { NodeDetail } from "../lib/types";

const NODES: NodeDetail[] = [
  {
    node: "extract_booking_request",
    status: "success",
    duration_ms: 5,
    tokens: null,
    cost_usd: null,
    output: { booking_request: { customer_name: "John Doe" } },
  },
];

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

afterEach(() => vi.restoreAllMocks());

describe("useRunNodes", () => {
  test("fetches per-node detail when enabled with a runId", async () => {
    const spy = vi.spyOn(api, "getRunNodes").mockResolvedValue(NODES);
    const { result } = renderHook(() => useRunNodes("run_1", true), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("run_1");
    expect(result.current.data).toEqual(NODES);
  });

  test("is disabled without a runId or when not enabled", () => {
    const spy = vi.spyOn(api, "getRunNodes").mockResolvedValue(NODES);
    renderHook(() => useRunNodes(null, true), { wrapper: wrapper() });
    renderHook(() => useRunNodes("run_1", false), { wrapper: wrapper() });
    expect(spy).not.toHaveBeenCalled();
  });
});
