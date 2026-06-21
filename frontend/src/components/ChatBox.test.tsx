import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatBox } from "./ChatBox";

describe("ChatBox", () => {
  test("submits the trimmed message", async () => {
    const onSubmit = vi.fn();
    render(<ChatBox onSubmit={onSubmit} />);
    await userEvent.type(
      screen.getByLabelText("Booking message"),
      "  book a plumber  ",
    );
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledWith("book a plumber");
  });

  test("does not submit an empty / whitespace message", async () => {
    const onSubmit = vi.fn();
    render(<ChatBox onSubmit={onSubmit} />);
    // Button is always enabled; zod validation blocks onSubmit for empty input.
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).not.toHaveBeenCalled();
    await screen.findByText("Enter a booking request to continue.");
  });

  test("shows pending label and disables the button", () => {
    render(<ChatBox onSubmit={() => {}} pending />);
    expect(
      screen.getByRole("button", { name: "Starting…" }),
    ).toBeDisabled();
  });
});
