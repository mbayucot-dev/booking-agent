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
    const button = screen.getByRole("button", { name: "Submit" });
    expect(button).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("shows pending label and disables the button", () => {
    render(<ChatBox onSubmit={() => {}} pending />);
    expect(
      screen.getByRole("button", { name: "Starting…" }),
    ).toBeDisabled();
  });
});
