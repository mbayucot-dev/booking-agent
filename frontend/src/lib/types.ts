// Shared API types mirroring the FastAPI backend contract.

import type { NodeStatus } from "../flow/nodeStatus";

export type { NodeStatus };

export type RunStatus =
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "escalated";

export interface PreparedAction {
  action: string;
  payload: Record<string, unknown>;
}

export interface ApprovalCard {
  customer: string | null;
  service: string | null;
  date: string | null;
  time: string | null;
  staff: string | null;
  email: string | null;
  prepared_actions: PreparedAction[];
}

export interface RunResponse {
  run_id: string;
  status: RunStatus;
  node_statuses: Record<string, NodeStatus>;
  approval_card: ApprovalCard | null;
  final_response: string | null;
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}

/** Per-node execution detail for the clickable node-preview panel. */
export interface NodeDetail {
  node: string;
  status: NodeStatus;
  duration_ms: number | null;
  tokens: number | null;
  cost_usd: number | null;
  output: Record<string, unknown> | null;
}
