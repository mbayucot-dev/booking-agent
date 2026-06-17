// Typed fetch client for the booking-workflow backend.

import type { ApiErrorEnvelope, NodeDetail, RunResponse } from "./types";

// Same-origin: requests go to the Next.js BFF proxy (src/app/api/v1/[...path]),
// which injects the bearer token server-side — so the token stays off the client
// and EventSource (which can't set headers) still authenticates.
export const API_BASE = "";

/** Error thrown when the backend returns a non-2xx response. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: unknown,
    requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }
  const envelope = body as ApiErrorEnvelope | undefined;
  const err = envelope?.error;
  if (err && typeof err.message === "string") {
    return new ApiError(
      res.status,
      err.code ?? "unknown",
      err.message,
      err.details,
      err.request_id,
    );
  }
  return new ApiError(
    res.status,
    "unknown",
    `Request failed with status ${res.status}`,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw await parseError(res);
  }
  return (await res.json()) as T;
}

export function startRun(message: string): Promise<RunResponse> {
  return request<RunResponse>("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function getRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/v1/runs/${runId}`, { method: "GET" });
}

export function approveRun(runId: string, by?: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/v1/runs/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({ by }),
  });
}

export function rejectRun(
  runId: string,
  reason?: string,
): Promise<RunResponse> {
  return request<RunResponse>(`/api/v1/runs/${runId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function retryRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/v1/runs/${runId}/retry`, { method: "POST" });
}

export function getRunNodes(runId: string): Promise<NodeDetail[]> {
  return request<NodeDetail[]>(`/api/v1/runs/${runId}/nodes`, { method: "GET" });
}

/** URL of the SSE events stream for a run. */
export function runEventsUrl(runId: string): string {
  return `${API_BASE}/api/v1/runs/${runId}/events`;
}
