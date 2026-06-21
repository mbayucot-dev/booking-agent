// Same-origin BFF proxy to the booking-agent backend.
//
// Forwards to the backend with the bearer token injected server-side, so the
// secret never ships to the client, the SPA needs no CORS, and EventSource
// (which can't set headers) still authenticates. The upstream body is streamed
// straight back, so SSE works transparently.
//
// Config (server-side env, NOT NEXT_PUBLIC):
//   BOOKING_AGENT_API_URL  backend base URL (default http://localhost:8000)
//   API_AUTH_TOKEN         bearer token; when set, added to every proxied call
//   FRONTEND_ACCESS_KEY    when set, ALL proxy calls must carry a matching
//                          x-access-key header — prevents unauthenticated
//                          visitors from reaching the backend through the proxy.
//                          Production deployments should set this and gate the
//                          header behind a real session (NextAuth, Clerk, etc.).

export const dynamic = "force-dynamic"; // never cache; required to stream SSE
export const runtime = "nodejs"; // node streaming semantics for long-lived SSE

// Connection-scoped headers must not be forwarded.
const HOP_BY_HOP = new Set(["host", "connection", "content-length", "transfer-encoding"]);

// Bound non-streaming requests so a hung backend can't hang the proxy forever.
const PROXY_TIMEOUT_MS = 30_000;

function checkAccessKey(request: Request): Response | null {
  const requiredKey = process.env.FRONTEND_ACCESS_KEY;
  if (!requiredKey) return null; // guard disabled (dev/local)
  const provided = request.headers.get("x-access-key") ?? "";
  // Constant-time comparison prevents timing attacks on the key.
  if (provided.length !== requiredKey.length) return new Response(null, { status: 401 });
  let diff = 0;
  for (let i = 0; i < requiredKey.length; i++) {
    diff |= provided.charCodeAt(i) ^ requiredKey.charCodeAt(i);
  }
  return diff !== 0 ? new Response(null, { status: 401 }) : null;
}

async function proxy(request: Request, path: string[]): Promise<Response> {
  const denied = checkAccessKey(request);
  if (denied) return denied;
  const backend = (process.env.BOOKING_AGENT_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
  const token = process.env.API_AUTH_TOKEN;
  const search = new URL(request.url).search;
  const target = `${backend}/api/v1/${path.join("/")}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  if (token) headers.set("authorization", `Bearer ${token}`);

  const init: RequestInit = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.text();
  }

  // SSE is long-lived → no timeout; everything else gets a bounded one.
  const isStream = (request.headers.get("accept") ?? "").includes("text/event-stream");
  const controller = new AbortController();
  const timer = isStream ? undefined : setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);

  let upstream: Response;
  try {
    upstream = await fetch(target, { ...init, signal: controller.signal });
  } catch (err) {
    // 504 if we timed out waiting on the backend; 502 if it was unreachable.
    const aborted = err instanceof Error && err.name === "AbortError";
    return new Response(null, { status: aborted ? 504 : 502 });
  } finally {
    if (timer) clearTimeout(timer);
  }

  const respHeaders = new Headers();
  // x-accel-buffering is forwarded so a proxy in front of THIS app also leaves
  // the SSE stream unbuffered.
  for (const h of ["content-type", "cache-control", "x-accel-buffering"]) {
    const v = upstream.headers.get(h);
    if (v) respHeaders.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: respHeaders });
}

// Next 16: route `params` is async and must be awaited.
type Ctx = { params: Promise<{ path: string[] }> };
export const GET = async (req: Request, { params }: Ctx) => proxy(req, (await params).path);
export const POST = async (req: Request, { params }: Ctx) => proxy(req, (await params).path);
