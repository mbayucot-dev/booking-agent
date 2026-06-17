import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApprovalDrawer } from "./ApprovalDrawer";
import type { ApprovalCard } from "../lib/types";

const card: ApprovalCard = {
  customer: "Jane Doe",
  service: "Plumbing",
  date: "2026-06-20",
  time: "09:00",
  staff: "Bob",
  email: "jane@example.com",
  prepared_actions: [
    { action: "create_job", payload: { jobId: "J1" } },
    { action: "send_email", payload: { to: "jane@example.com" } },
  ],
};

describe("ApprovalDrawer", () => {
  test("renders all approval card fields", () => {
    render(
      <ApprovalDrawer card={card} onApprove={() => {}} onReject={() => {}} />,
    );
    expect(screen.getByTestId("approval-customer")).toHaveTextContent("Jane Doe");
    expect(screen.getByTestId("approval-service")).toHaveTextContent("Plumbing");
    expect(screen.getByTestId("approval-date")).toHaveTextContent("2026-06-20");
    expect(screen.getByTestId("approval-time")).toHaveTextContent("09:00");
    expect(screen.getByTestId("approval-staff")).toHaveTextContent("Bob");
    expect(screen.getByTestId("approval-email")).toHaveTextContent(
      "jane@example.com",
    );
  });

  test("renders null fields as a dash", () => {
    render(
      <ApprovalDrawer
        card={{ ...card, staff: null }}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByTestId("approval-staff")).toHaveTextContent("—");
  });

  test("lists the prepared actions", () => {
    render(
      <ApprovalDrawer card={card} onApprove={() => {}} onReject={() => {}} />,
    );
    const items = screen.getByTestId("prepared-actions").querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(screen.getByText("create_job")).toBeInTheDocument();
    expect(screen.getByText("send_email")).toBeInTheDocument();
  });

  test("fires onApprove when Approve is clicked", async () => {
    const onApprove = vi.fn();
    render(
      <ApprovalDrawer card={card} onApprove={onApprove} onReject={() => {}} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  test("fires onReject with the typed reason", async () => {
    const onReject = vi.fn();
    render(
      <ApprovalDrawer card={card} onApprove={() => {}} onReject={onReject} />,
    );
    await userEvent.type(
      screen.getByLabelText("Rejection reason"),
      "slot taken",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onReject).toHaveBeenCalledWith("slot taken");
  });

  test("disables buttons while pending", () => {
    render(
      <ApprovalDrawer
        card={card}
        onApprove={() => {}}
        onReject={() => {}}
        pending
      />,
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });
});
