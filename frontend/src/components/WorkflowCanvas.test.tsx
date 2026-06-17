import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import type { StatusFlowNode } from "../flow/workflowDefinition";

// React Flow needs real layout measurement which jsdom lacks, so mock it
// shallowly: capture the nodes prop, render the registered node components, and
// wire onNodeClick / onPaneClick so we can assert the canvas's click handling.
vi.mock("@xyflow/react", () => {
  const Handle = () => null;
  return {
    __esModule: true,
    ReactFlow: ({
      nodes,
      nodeTypes,
      nodesDraggable,
      nodesConnectable,
      onNodeClick,
      onPaneClick,
    }: {
      nodes: StatusFlowNode[];
      nodeTypes: Record<string, (p: { data: unknown }) => ReactNode>;
      nodesDraggable: boolean;
      nodesConnectable: boolean;
      onNodeClick?: (e: unknown, n: StatusFlowNode) => void;
      onPaneClick?: () => void;
    }) => (
      <div
        data-testid="rf-mock"
        data-draggable={String(nodesDraggable)}
        data-connectable={String(nodesConnectable)}
      >
        <button type="button" data-testid="rf-pane" onClick={() => onPaneClick?.()}>
          pane
        </button>
        {nodes.map((n) => {
          const Comp = nodeTypes[n.type as string];
          return (
            <div key={n.id} onClick={() => onNodeClick?.({}, n)}>
              <Comp data={n.data} />
            </div>
          );
        })}
      </div>
    ),
    Background: () => null,
    Controls: () => null,
    Handle,
    Position: { Top: "top", Bottom: "bottom" },
  };
});

import { WorkflowCanvas } from "./WorkflowCanvas";

describe("WorkflowCanvas", () => {
  test("renders all canonical nodes without crashing", () => {
    render(<WorkflowCanvas />);
    expect(screen.getByTestId("workflow-canvas")).toBeInTheDocument();
    expect(screen.getByTestId("node-chat_trigger")).toBeInTheDocument();
    expect(screen.getByTestId("node-final_response")).toBeInTheDocument();
  });

  test("applies the live status map to the matching node", () => {
    render(
      <WorkflowCanvas
        statuses={{ extract_booking_request: "running", validation_agent: "success" }}
      />,
    );
    expect(screen.getByTestId("node-extract_booking_request")).toHaveAttribute(
      "data-status",
      "running",
    );
    expect(screen.getByTestId("node-validation_agent")).toHaveAttribute("data-status", "success");
    expect(screen.getByTestId("node-chat_trigger")).toHaveAttribute("data-status", "idle");
  });

  test("is read-only (no drag / connect)", () => {
    render(<WorkflowCanvas />);
    const rf = screen.getByTestId("rf-mock");
    expect(rf).toHaveAttribute("data-draggable", "false");
    expect(rf).toHaveAttribute("data-connectable", "false");
  });

  test("clicking a node selects it", async () => {
    const onNodeSelect = vi.fn();
    render(<WorkflowCanvas onNodeSelect={onNodeSelect} />);
    await userEvent.click(screen.getByTestId("node-extract_booking_request"));
    expect(onNodeSelect).toHaveBeenCalledWith("extract_booking_request");
  });

  test("clicking the pane clears the selection", async () => {
    const onClear = vi.fn();
    render(<WorkflowCanvas onClear={onClear} />);
    await userEvent.click(screen.getByTestId("rf-pane"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  test("highlights only the selected node", () => {
    render(<WorkflowCanvas selectedNode="extract_booking_request" />);
    // The selection ring is "ring-2 ring-primary ..." (the always-present focus
    // ring is "focus-visible:ring-2 ...", so match the contiguous selection token).
    expect(screen.getByTestId("node-extract_booking_request").className).toContain(
      "ring-2 ring-primary",
    );
    expect(screen.getByTestId("node-chat_trigger").className).not.toContain("ring-2 ring-primary");
  });
});
