import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import ErrorBoundary from "./error";

describe("error boundary", () => {
  test("shows a recovery message and calls reset", () => {
    const reset = vi.fn();
    render(<ErrorBoundary error={new Error("boom")} reset={reset} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
  });
});
