import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { NodeProps } from "@xyflow/react";

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom" },
}));

import { StatusNode } from "./StatusNode";
import type { StatusFlowNode } from "../flow/workflowDefinition";

function renderNode(onSelect: () => void) {
  const data = {
    name: "extract_booking_request" as const,
    label: "Extract Booking Request",
    status: "success" as const,
    implemented: true,
    selected: false,
    onSelect,
  };
  render(<StatusNode {...({ data } as unknown as NodeProps<StatusFlowNode>)} />);
  return screen.getByTestId("node-extract_booking_request");
}

describe("StatusNode accessibility", () => {
  test("is an operable button with a label", () => {
    const node = renderNode(() => {});
    expect(node).toHaveAttribute("role", "button");
    expect(node).toHaveAttribute("tabindex", "0");
    expect(node.getAttribute("aria-label")).toMatch(/Extract Booking Request/);
  });

  test("Enter and Space activate selection", () => {
    const onSelect = vi.fn();
    const node = renderNode(onSelect);
    fireEvent.keyDown(node, { key: "Enter" });
    fireEvent.keyDown(node, { key: " " });
    expect(onSelect).toHaveBeenCalledTimes(2);
  });
});
