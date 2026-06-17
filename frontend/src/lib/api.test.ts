import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";

import {
  ApiError,
  approveRun,
  getRun,
  getRunNodes,
  rejectRun,
  retryRun,
  runEventsUrl,
  startRun,
  API_BASE,
} from "./api";
import type { NodeDetail, RunResponse } from "./types";

const run: RunResponse = {
  run_id: "run_123",
  status: "running",
  node_statuses: { chat_trigger: "success" },
  approval_card: null,
  final_response: null,
};

function okResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

function errorResponse(status: number, body: unknown): Response {
  return {
    ok: false,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("api client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("startRun POSTs the message and returns the run", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(run));

    const result = await startRun("book a plumber");

    expect(result).toEqual(run);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ message: "book a plumber" });
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  test("getRun fetches by id", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(run));

    const result = await getRun("run_123");

    expect(result).toEqual(run);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs/run_123`);
    expect(init.method).toBe("GET");
  });

  test("approveRun POSTs with by", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(run));

    await approveRun("run_123", "alice");

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs/run_123/approve`);
    expect(JSON.parse(init.body)).toEqual({ by: "alice" });
  });

  test("rejectRun POSTs with reason", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(run));

    await rejectRun("run_123", "not available");

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs/run_123/reject`);
    expect(JSON.parse(init.body)).toEqual({ reason: "not available" });
  });

  test("throws ApiError parsing the error envelope on !ok", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResponse(422, {
        error: {
          code: "validation_error",
          message: "message is required",
          request_id: "req_1",
        },
      }),
    );

    await expect(startRun("")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      code: "validation_error",
      message: "message is required",
      requestId: "req_1",
    });
  });

  test("falls back to a generic ApiError when body is not an envelope", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      errorResponse(500, "boom"),
    );

    const err = await startRun("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.code).toBe("unknown");
  });

  test("retryRun POSTs to the retry endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(run));
    await retryRun("run_123");
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs/run_123/retry`);
    expect(init.method).toBe("POST");
  });

  test("getRunNodes GETs the per-node detail list", async () => {
    const nodes: NodeDetail[] = [
      {
        node: "extract_booking_request",
        status: "success",
        duration_ms: 5,
        tokens: null,
        cost_usd: null,
        output: { booking_request: { customer_name: "John Doe" } },
      },
    ];
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okResponse(nodes));
    const result = await getRunNodes("run_123");
    expect(result).toEqual(nodes);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`${API_BASE}/api/v1/runs/run_123/nodes`);
    expect(init.method).toBe("GET");
  });

  test("runEventsUrl builds the SSE url", () => {
    expect(runEventsUrl("run_123")).toBe(
      `${API_BASE}/api/v1/runs/run_123/events`,
    );
  });
});
