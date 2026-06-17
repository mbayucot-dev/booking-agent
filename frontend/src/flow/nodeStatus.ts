// The 8 node statuses, kept in lockstep with the backend `NodeStatus` enum
// (backend/app/models.py). run_events stream these values and the canvas maps
// them onto nodes.

export type NodeStatus =
  | "idle"
  | "running"
  | "success"
  | "failed"
  | "waiting_approval"
  | "approved"
  | "rejected"
  | "skipped";

export interface StatusStyle {
  label: string;
  /** Foreground / accent colour. */
  color: string;
  /** Node background. */
  bg: string;
  /** Border colour. */
  border: string;
  /** Whether the node should animate while in this status. */
  pulse?: boolean;
}

export const STATUS_STYLES: Record<NodeStatus, StatusStyle> = {
  idle: { label: "Idle", color: "#64748b", bg: "#f8fafc", border: "#cbd5e1" },
  running: {
    label: "Running",
    color: "#1d4ed8",
    bg: "#eff6ff",
    border: "#3b82f6",
    pulse: true,
  },
  success: { label: "Success", color: "#15803d", bg: "#f0fdf4", border: "#22c55e" },
  failed: { label: "Failed", color: "#b91c1c", bg: "#fef2f2", border: "#ef4444" },
  waiting_approval: {
    label: "Waiting for approval",
    color: "#b45309",
    bg: "#fffbeb",
    border: "#f59e0b",
    pulse: true,
  },
  approved: { label: "Approved", color: "#15803d", bg: "#ffffff", border: "#22c55e" },
  rejected: { label: "Rejected", color: "#b91c1c", bg: "#ffffff", border: "#ef4444" },
  skipped: { label: "Skipped", color: "#94a3b8", bg: "#f8fafc", border: "#e2e8f0" },
};

export const isNodeStatus = (value: unknown): value is NodeStatus =>
  typeof value === "string" && value in STATUS_STYLES;
