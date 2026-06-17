// Canonical node names — must match backend/app/graph/constants.py exactly so
// run_events (keyed by node name) map onto the right React Flow node.

export const NODE = {
  CHAT_TRIGGER: "chat_trigger",
  SUPERVISOR: "supervisor_agent",
  EXTRACT: "extract_booking_request",
  VALIDATION: "validation_agent",
  CUSTOMER: "customer_agent",
  AVAILABILITY: "availability_subgraph",
  JOB_PLANNING: "job_planning_agent",
  COMMUNICATION: "communication_agent",
  RISK_REVIEW: "risk_review_agent",
  HUMAN_APPROVAL: "human_approval",
  EXECUTION: "execution_agent",
  HUBSPOT: "hubspot_agent",
  EMAIL: "email_agent",
  AUDIT_LOG: "audit_log",
  MEMORY: "memory_agent",
  FINAL_RESPONSE: "final_response",
} as const;

export type NodeName = (typeof NODE)[keyof typeof NODE];

// Node names the backend actually executes; the rest render as idle placeholders.
export const PHASE_1_IMPLEMENTED: ReadonlySet<NodeName> = new Set([
  NODE.CHAT_TRIGGER,
  NODE.SUPERVISOR,
  NODE.EXTRACT,
  NODE.VALIDATION,
]);
