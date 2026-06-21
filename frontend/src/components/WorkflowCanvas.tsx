"use client";

import { useMemo } from "react";
import { Background, Controls, type Node, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { nodeTypes } from "./StatusNode";
import {
  applyEdgeStatuses,
  applyStatuses,
  initialEdges,
  initialNodes,
} from "@/flow/workflowDefinition";
import type { NodeName } from "@/flow/nodeNames";
import type { NodeStatus } from "@/flow/nodeStatus";

export interface WorkflowCanvasProps {
  /** Live node -> status map (from the run stream / run response). */
  statuses?: Record<string, NodeStatus>;
  /** Node currently open in the preview panel (highlighted). */
  selectedNode?: string | null;
  /** Called when a node is clicked — opens its preview panel. */
  onNodeSelect?: (name: NodeName) => void;
  /** Called when the empty canvas is clicked — closes the preview panel. */
  onClear?: () => void;
}

export function WorkflowCanvas({
  statuses = {},
  selectedNode = null,
  onNodeSelect,
  onClear,
}: WorkflowCanvasProps) {
  const typed = statuses as Partial<Record<NodeName, NodeStatus>>;
  const nodes = useMemo(
    () =>
      applyStatuses(initialNodes, typed).map((n) => ({
        ...n,
        data: {
          ...n.data,
          selected: n.id === selectedNode,
          onSelect: () => onNodeSelect?.(n.id as NodeName),
        },
      })),
    [typed, selectedNode, onNodeSelect],
  );
  const edges = useMemo(() => applyEdgeStatuses(initialEdges, typed), [typed]);

  return (
    <div className="h-full w-full" data-testid="workflow-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        edgesFocusable={false}
        onNodeClick={(_, node: Node) => onNodeSelect?.(node.id as NodeName)}
        onPaneClick={() => onClear?.()}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} className="opacity-60" />
        <Controls showInteractive={false} className="!shadow-sm" />
      </ReactFlow>
    </div>
  );
}
