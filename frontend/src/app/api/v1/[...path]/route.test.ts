import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { GET, POST } from "./route";

describe("BFF proxy", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.API_AUTH_TOKEN;
    delete process.env.BOOKING_AGENT_API_URL;
  });

  test("forwards to the backend and injects the bearer when API_AUTH_TOKEN is set", async () => {
    process.env.BOOKING_AGENT_API_URL = "http://backend:8000";
    process.env.API_AUTH_TOKEN = "s3cret";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("{}", { status: 200, headers: { "content-type": "application/json" } }),
    );

    const res = await GET(new Request("http://localhost:3000/api/v1/runs/abc?x=1"), {
      params: Promise.resolve({ path: ["runs", "abc"] }),
    });

    expect(res.status).toBe(200);
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/runs/abc?x=1"); // path + query preserved
    expect((init.headers as Headers).get("authorization")).toBe("Bearer s3cret");
  });

  test("omits the Authorization header when no token is configured", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response("{}", { status: 200 }));

    await POST(
      new Request("http://localhost:3000/api/v1/runs", { method: "POST", body: '{"message":"x"}' }),
      { params: Promise.resolve({ path: ["runs"] }) },
    );

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/runs"); // default backend
    expect((init.headers as Headers).get("authorization")).toBeNull();
    expect(init.body).toBe('{"message":"x"}'); // POST body forwarded
  });

  test("propagates the upstream status on error", async () => {
    process.env.API_AUTH_TOKEN = "s3cret";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response("nope", { status: 401 }));
    const res = await GET(new Request("http://localhost:3000/api/v1/runs/x"), {
      params: Promise.resolve({ path: ["runs", "x"] }),
    });
    expect(res.status).toBe(401);
  });

  test("maps an upstream timeout (abort) to 504", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(
      Object.assign(new Error("The operation was aborted"), { name: "AbortError" }),
    );
    const res = await GET(new Request("http://localhost:3000/api/v1/runs/x"), {
      params: Promise.resolve({ path: ["runs", "x"] }),
    });
    expect(res.status).toBe(504);
  });

  test("maps an unreachable backend to 502", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await GET(new Request("http://localhost:3000/api/v1/runs/x"), {
      params: Promise.resolve({ path: ["runs", "x"] }),
    });
    expect(res.status).toBe(502);
  });

  test("streams SSE through without a timeout abort", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((_url, opts) => {
      expect((opts.signal as AbortSignal).aborted).toBe(false); // not aborted at call time
      return Promise.resolve(
        new Response("data: {}\n\n", {
          status: 200,
          headers: { "content-type": "text/event-stream", "x-accel-buffering": "no" },
        }),
      );
    });
    const res = await GET(
      new Request("http://localhost:3000/api/v1/runs/x/events", {
        headers: { accept: "text/event-stream" },
      }),
      { params: Promise.resolve({ path: ["runs", "x", "events"] }) },
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/event-stream");
    expect(res.headers.get("x-accel-buffering")).toBe("no"); // anti-buffering forwarded
  });
});
