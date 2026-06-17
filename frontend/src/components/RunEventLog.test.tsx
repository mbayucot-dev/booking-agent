import { describe, test, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { RunEventLog } from "./RunEventLog";

describe("RunEventLog", () => {
  test("shows an empty state", () => {
    render(<RunEventLog events={[]} />);
    expect(screen.getByText("No events yet.")).toBeInTheDocument();
  });

  test("lists events with node, status label and duration", () => {
    render(
      <RunEventLog
        events={[
          { node: "chat_trigger", status: "success", duration_ms: 12 },
          { node: "extract_booking_request", status: "running", duration_ms: null },
        ]}
      />,
    );
    const items = screen.getAllByTestId("run-event");
    expect(items).toHaveLength(2);
    expect(screen.getByText("chat_trigger")).toBeInTheDocument();
    expect(screen.getByText("12ms")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
