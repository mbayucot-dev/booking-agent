// Custom read-only React Flow node that renders a workflow step and its live
// status. Registered as nodeType "status".

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

import { STATUS_STYLES } from "@/flow/nodeStatus";
import { STATUS_PRESENTATION } from "@/flow/statusPresentation";
import type { StatusFlowNode } from "@/flow/workflowDefinition";
import { cn } from "@/lib/utils";

function StatusNodeImpl({ data }: NodeProps<StatusFlowNode>) {
  const label = STATUS_STYLES[data.status].label;
  const { Icon, node, spin, pulse } = STATUS_PRESENTATION[data.status];
  const muted = !data.implemented;

  return (
    <div
      className={cn(
        "min-w-[200px] cursor-pointer rounded-lg border-2 px-3 py-2 text-[13px] font-semibold shadow-sm transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        node,
        muted && "opacity-55",
        pulse && "animate-status-pulse",
        data.selected && "ring-2 ring-primary ring-offset-2 ring-offset-background",
      )}
      role="button"
      tabIndex={0}
      aria-label={`${data.label} — ${label}. Open details.`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          data.onSelect?.();
        }
      }}
      data-testid={`node-${data.name}`}
      data-status={data.status}
    >
      {/* input handle (target) — muted dot at the top */}
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2.5 !w-2.5 !border-2 !border-background !bg-muted-foreground"
      />
      <div className="flex items-center gap-2">
        <Icon className={cn("h-4 w-4 shrink-0", spin && "animate-spin")} aria-hidden="true" />
        <span className="text-foreground/90">{data.label}</span>
      </div>
      <div className="mt-1 pl-6 text-[11px] font-medium opacity-80">
        {label}
        {muted ? " · planned" : ""}
      </div>
      {/* output handle (source) — primary dot at the bottom, feeds the next input */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2.5 !w-2.5 !border-2 !border-background !bg-primary"
      />
    </div>
  );
}

// Memoized: during streaming only the nodes whose data changed re-render.
export const StatusNode = memo(StatusNodeImpl);

// Map passed to <ReactFlow nodeTypes=...>.
export const nodeTypes = { status: StatusNode };
