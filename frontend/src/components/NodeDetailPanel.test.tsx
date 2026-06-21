import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NodeDetailPanel } from "./NodeDetailPanel";
import type { NodeDetail } from "../lib/types";

const detail: NodeDetail = {
  node: "extract_booking_request",
  status: "success",
  duration_ms: 5,
  tokens: null,
  cost_usd: null,
  output: { booking_request: { customer_name: "John Doe" } },
};

describe("NodeDetailPanel", () => {
  test("renders the label, status, and output JSON", () => {
    render(
      <NodeDetailPanel label="Extract Booking Request" status="success" detail={detail} onClose={() => {}} />,
    );
    expect(screen.getByText("Extract Booking Request")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText(/John Doe/)).toBeInTheDocument();
    expect(screen.getByText("5ms")).toBeInTheDocument();
  });

  test("shows an empty state when the step has no output", () => {
    render(<NodeDetailPanel label="Memory Agent" status="idle" onClose={() => {}} />);
    expect(screen.getByText(/hasn't produced output yet/i)).toBeInTheDocument();
  });

  test("distinguishes running, error, and empty states", () => {
    const { rerender } = render(
      <NodeDetailPanel label="Execution" status="running" onClose={() => {}} />,
    );
    expect(screen.getByText(/Executing/i)).toBeInTheDocument();

    rerender(<NodeDetailPanel label="Execution" status="success" error onClose={() => {}} />);
    expect(screen.getByText(/Failed to load output/i)).toBeInTheDocument();

    rerender(<NodeDetailPanel label="Execution" status="success" loading onClose={() => {}} />);
    expect(screen.getByText(/Loading/i)).toBeInTheDocument();
  });

  test("closes on Escape", () => {
    const onClose = vi.fn();
    render(<NodeDetailPanel label="X" status="idle" onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("fires onClose from the close button", async () => {
    const onClose = vi.fn();
    render(<NodeDetailPanel label="X" status="idle" onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Close panel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("offers retry only when the run failed, and fires onRetry", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(
      <NodeDetailPanel label="Execution" status="failed" onClose={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();

    rerender(
      <NodeDetailPanel
        label="Execution"
        status="failed"
        showRetry
        onRetry={onRetry}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test("shows a spinner and disables the retry button while pending", () => {
    render(
      <NodeDetailPanel
        label="Execution"
        status="failed"
        showRetry
        retryPending
        onRetry={() => {}}
        onClose={() => {}}
      />,
    );
    const btn = screen.getByRole("button", { name: /retry/i });
    expect(btn).toBeDisabled();
    // Loader2 is rendered as an SVG aria-hidden; its sibling text is still present.
    expect(btn).toHaveTextContent(/retry from last checkpoint/i);
  });
});
