import { test, expect } from "vitest";

import { NODE } from "./nodeNames";
import {
  applyEdgeStatuses,
  applyStatuses,
  initialEdges,
  initialNodes,
} from "./workflowDefinition";

test("defines all 16 workflow nodes", () => {
  expect(initialNodes.length).toBe(16);
  expect(initialEdges.length).toBe(initialNodes.length - 1);
});

test("all nodes start idle", () => {
  expect(initialNodes.every((n) => n.data.status === "idle")).toBe(true);
});

test("phase 1 nodes are marked implemented, later ones are not", () => {
  const byId = Object.fromEntries(initialNodes.map((n) => [n.id, n]));
  expect(byId[NODE.EXTRACT].data.implemented).toBe(true);
  expect(byId[NODE.SUPERVISOR].data.implemented).toBe(true);
  expect(byId[NODE.MEMORY].data.implemented).toBe(false);
});

test("applyStatuses patches only the named nodes", () => {
  const next = applyStatuses(initialNodes, {
    [NODE.EXTRACT]: "running",
    [NODE.VALIDATION]: "success",
  });
  const byId = Object.fromEntries(next.map((n) => [n.id, n]));
  expect(byId[NODE.EXTRACT].data.status).toBe("running");
  expect(byId[NODE.VALIDATION].data.status).toBe("success");
  expect(byId[NODE.CHAT_TRIGGER].data.status).toBe("idle");
});

test("nodes are not editable (read-only canvas)", () => {
  expect(initialNodes.every((n) => n.draggable === false)).toBe(true);
  expect(initialNodes.every((n) => n.connectable === false)).toBe(true);
});

test("applyEdgeStatuses animates the edge into the active node", () => {
  const edges = applyEdgeStatuses(initialEdges, {
    [NODE.CHAT_TRIGGER]: "success",
    [NODE.SUPERVISOR]: "running",
  });
  const byId = Object.fromEntries(edges.map((e) => [e.id, e]));
  // chat_trigger (done) → supervisor (running): animated.
  const active = byId[`e-${NODE.CHAT_TRIGGER}-${NODE.SUPERVISOR}`];
  expect(active.animated).toBe(true);
  // An untouched downstream edge stays idle (not animated).
  const idle = byId[`e-${NODE.EXTRACT}-${NODE.VALIDATION}`];
  expect(idle.animated).toBe(false);
});

test("applyEdgeStatuses marks an edge between two finished nodes as done", () => {
  const edges = applyEdgeStatuses(initialEdges, {
    [NODE.CHAT_TRIGGER]: "success",
    [NODE.SUPERVISOR]: "approved",
  });
  const done = edges.find(
    (e) => e.id === `e-${NODE.CHAT_TRIGGER}-${NODE.SUPERVISOR}`,
  );
  expect(done?.animated).toBe(false); // solid, not animated
  expect(done?.style?.stroke).toContain("success");
});
