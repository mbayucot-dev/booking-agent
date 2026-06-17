// Static, read-only React Flow topology for the booking workflow — the single
// source of truth for what the canvas renders. Node status starts "idle"; the
// live run stream patches each node's `data.status` from run_events.

import type { Edge, Node } from "@xyflow/react";

import { NODE, PHASE_1_IMPLEMENTED, type NodeName } from "./nodeNames";
import type { NodeStatus } from "./nodeStatus";

export interface StatusNodeData {
  /** Node name — matches backend node id. */
  name: NodeName;
  /** Human-readable label shown on the node. */
  label: string;
  /** Current execution status, driven by run_events. */
  status: NodeStatus;
  /** False for unimplemented nodes (rendered muted). */
  implemented: boolean;
  /** True when this node is open in the preview panel (highlighted ring). */
  selected?: boolean;
  /** Opens this node's preview panel (keyboard activation). */
  onSelect?: () => void;
  [key: string]: unknown;
}

export type StatusFlowNode = Node<StatusNodeData, "status">;

// Vertical layout: one column, evenly spaced. Kept simple and deterministic so
// the read-only canvas is stable across renders.
const X = 240;
const GAP = 90;

const ORDER: ReadonlyArray<[NodeName, string]> = [
  [NODE.CHAT_TRIGGER, "Chat Trigger"],
  [NODE.SUPERVISOR, "Supervisor Agent"],
  [NODE.EXTRACT, "Extract Booking Request"],
  [NODE.VALIDATION, "Validation Agent"],
  [NODE.CUSTOMER, "Customer Agent"],
  [NODE.AVAILABILITY, "Availability"],
  [NODE.JOB_PLANNING, "Job Planning Agent"],
  [NODE.COMMUNICATION, "Communication Agent"],
  [NODE.RISK_REVIEW, "Risk Review Agent"],
  [NODE.HUMAN_APPROVAL, "Human Approval"],
  [NODE.EXECUTION, "Execution"],
  [NODE.HUBSPOT, "HubSpot Sync"],
  [NODE.EMAIL, "Email Agent"],
  [NODE.AUDIT_LOG, "Audit Log"],
  [NODE.MEMORY, "Memory Agent"],
  [NODE.FINAL_RESPONSE, "Final Response"],
];

/** node name → human-readable label (used by the node-preview panel). */
export const NODE_LABELS: Record<NodeName, string> = Object.fromEntries(ORDER) as Record<
  NodeName,
  string
>;

export const initialNodes: StatusFlowNode[] = ORDER.map(([name, label], i) => ({
  id: name,
  type: "status",
  position: { x: X, y: 40 + i * GAP },
  data: {
    name,
    label,
    status: "idle",
    implemented: PHASE_1_IMPLEMENTED.has(name),
  },
  draggable: false,
  connectable: false,
}));

// Linear backbone edges. The supervisor↔specialist routing is conceptual; for
// the read-only overview we draw the canonical top-to-bottom flow.
export const initialEdges: Edge[] = ORDER.slice(1).map(([name], i) => ({
  id: `e-${ORDER[i][0]}-${name}`,
  source: ORDER[i][0],
  target: name,
  animated: false,
}));

const DONE: ReadonlyArray<NodeStatus> = ["success", "approved"];
const ACTIVE: ReadonlyArray<NodeStatus> = ["running", "waiting_approval"];

/**
 * Animate/colour edges from the live status map: the edge into the active node
 * animates (primary); an edge between two finished nodes is solid (success);
 * everything else stays muted.
 */
export function applyEdgeStatuses(
  edges: Edge[],
  statuses: Partial<Record<NodeName, NodeStatus>>,
): Edge[] {
  return edges.map((e) => {
    const source = statuses[e.source as NodeName];
    const target = statuses[e.target as NodeName];
    const active = !!target && ACTIVE.includes(target);
    const done = !!source && !!target && DONE.includes(source) && DONE.includes(target);
    const stroke = active
      ? "hsl(var(--primary))"
      : done
        ? "hsl(var(--success))"
        : "hsl(var(--border))";
    return {
      ...e,
      animated: active,
      style: { stroke, strokeWidth: active ? 2.5 : 1.5 },
    };
  });
}

/** Apply a run_events status map onto the static nodes (used by the canvas). */
export function applyStatuses(
  nodes: StatusFlowNode[],
  statuses: Partial<Record<NodeName, NodeStatus>>,
): StatusFlowNode[] {
  return nodes.map((n) => {
    const next = statuses[n.id as NodeName];
    return next ? { ...n, data: { ...n.data, status: next } } : n;
  });
}
