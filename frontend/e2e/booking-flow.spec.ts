/**
 * E2E booking flow: start → canvas streams → approval gate → approve → completion.
 *
 * All backend API calls are mocked at the network layer (page.route) so the
 * test suite runs standalone without a live backend. This catches real browser
 * issues that component tests cannot: SSE EventSource behaviour, React Query
 * cache-update-driven re-renders, layout/visibility, and keyboard interaction.
 *
 * Run:  npx playwright test
 * CI:   see .github/workflows/ci.yml e2e job
 */

import { test, expect, type Page } from "@playwright/test";

// --- fixture data -----------------------------------------------------------

const RUN_ID = "test-run-abc";

const RUNNING_RUN = {
  run_id: RUN_ID,
  status: "running",
  node_statuses: {},
  approval_card: null,
  final_response: null,
};

const PAUSED_RUN = {
  run_id: RUN_ID,
  status: "paused",
  node_statuses: {
    chat_trigger: "success",
    extract_booking_request: "success",
    validation_agent: "success",
    availability_subgraph: "success",
    staff_selection: "success",
    prepare_payloads: "success",
    human_approval: "waiting_approval",
  },
  approval_card: {
    customer: "Jane Doe",
    service: "House cleaning",
    date: "2026-07-01",
    time: "09:00",
    staff: "Alice",
    email: "jane@example.com",
    prepared_actions: [
      { action: "create_job", payload: { service: "House cleaning" } },
      { action: "send_email", payload: { to: "jane@example.com" } },
    ],
  },
  final_response: null,
};

const COMPLETED_RUN = {
  run_id: RUN_ID,
  status: "completed",
  node_statuses: {
    ...PAUSED_RUN.node_statuses,
    human_approval: "approved",
    execution: "success",
    email_agent: "success",
    audit_log: "success",
  },
  approval_card: null,
  final_response: "Booking confirmed for Jane Doe on 2026-07-01 at 09:00.",
};

const NODE_DETAILS = [
  {
    node: "extract_booking_request",
    status: "success",
    duration_ms: 120,
    tokens: 42,
    cost_usd: 0.0001,
    output: { customer_name: "Jane Doe", service: "House cleaning" },
  },
];

// --- helpers ----------------------------------------------------------------

type RunFixture = typeof RUNNING_RUN | typeof PAUSED_RUN | typeof COMPLETED_RUN;

/** Wire up all API mocks before navigation. */
async function mockApi(page: Page) {
  let runState: RunFixture = RUNNING_RUN;

  // POST /api/v1/runs → start a run
  await page.route("**/api/v1/runs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(RUNNING_RUN),
      });
    } else {
      await route.continue();
    }
  });

  // GET /api/v1/runs/:id → current run state (starts running, transitions to paused)
  await page.route(`**/api/v1/runs/${RUN_ID}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(runState),
    });
  });

  // GET /api/v1/runs/:id/nodes → per-node detail
  await page.route(`**/api/v1/runs/${RUN_ID}/nodes`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(NODE_DETAILS),
    });
  });

  // POST /api/v1/runs/:id/approve → approve the run
  await page.route(`**/api/v1/runs/${RUN_ID}/approve`, async (route) => {
    runState = COMPLETED_RUN;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify(COMPLETED_RUN),
    });
  });

  // GET /api/v1/runs/:id/events → SSE stream (simulated with paused→completed events).
  // Transition runState to PAUSED here so that when the stream ends and useRun
  // refetches GET /runs/:id, it gets the paused snapshot (with approval_card).
  await page.route(`**/api/v1/runs/${RUN_ID}/events`, async (route) => {
    runState = PAUSED_RUN;
    const events = [
      'data: {"node":"chat_trigger","status":"success","duration_ms":10}\n\n',
      'data: {"node":"extract_booking_request","status":"success","duration_ms":120}\n\n',
      'data: {"node":"validation_agent","status":"success","duration_ms":5}\n\n',
      'data: {"node":"availability_subgraph","status":"success","duration_ms":200}\n\n',
      'data: {"node":"staff_selection","status":"success","duration_ms":80}\n\n',
      'data: {"node":"prepare_payloads","status":"success","duration_ms":30}\n\n',
      'data: {"node":"human_approval","status":"waiting_approval","duration_ms":null}\n\n',
      "event: end\ndata: {}\n\n",
    ].join("");
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "cache-control": "no-cache", "x-accel-buffering": "no" },
      body: events,
    });
  });

  return { setRunState: (s: RunFixture) => { runState = s; } };
}

// --- tests ------------------------------------------------------------------

test.describe("Booking flow", () => {
  test("submit → canvas streams → approval drawer → approve → completion", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    // 1. Chat input is visible and the canvas shows the workflow graph.
    const chatInput = page.getByLabel("Booking message");
    await expect(chatInput).toBeVisible();

    // 2. fill() uses insertText (not keyboard events) so React's field.onChange fires
    //    and RHF gets the value before handleSubmit validates.
    const submitBtn = page.getByRole("button", { name: "Submit" });
    await chatInput.fill("Book a house cleaning for Jane Doe on July 1st at 9am");
    await expect(chatInput).toHaveValue("Book a house cleaning for Jane Doe on July 1st at 9am");
    await submitBtn.click();

    // 3. Canvas should appear (dynamic import; give extra time) and node statuses
    //    should update as SSE events arrive.
    const canvas = page.locator('[data-testid="workflow-canvas"]');
    await expect(canvas).toBeVisible({ timeout: 15_000 });

    // 4. The approval drawer should appear after the SSE stream signals waiting_approval.
    const drawer = page.locator('[data-testid="approval-drawer"]');
    await expect(drawer).toBeVisible({ timeout: 10_000 });

    // 5. Approval card fields are populated from the paused run.
    await expect(page.locator('[data-testid="approval-customer"]')).toHaveText("Jane Doe");
    await expect(page.locator('[data-testid="approval-service"]')).toHaveText("House cleaning");

    // 6. Approve the run.
    await page.getByRole("button", { name: "Approve" }).click();

    // 7. After approval the drawer should disappear and the final response should show.
    await expect(drawer).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/booking confirmed/i)).toBeVisible({ timeout: 10_000 });
  });

  test("node detail panel opens on click and shows output", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    const chatInput = page.getByLabel("Booking message");
    const submitBtn2 = page.getByRole("button", { name: "Submit" });
    await chatInput.fill("Book a plumber");
    await expect(chatInput).toHaveValue("Book a plumber");
    await submitBtn2.click();

    // Wait for a completed node to be clickable on the canvas.
    const canvas = page.locator('[data-testid="workflow-canvas"]');
    await expect(canvas).toBeVisible({ timeout: 15_000 });

    // Click the extract node (rendered by React Flow as an element with the node label).
    await page.locator('[data-id="extract_booking_request"]').click({ timeout: 10_000 });

    // The detail panel should open and show output from the mocked /nodes response.
    const panel = page.locator('[data-testid="node-detail-panel"]');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("Jane Doe");

    // Close with Escape.
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
  });

  test("start over: resets UI to initial state after a completed run", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    // Drive through the full happy path to reach a completed state.
    await page.getByLabel("Booking message").fill("Book a house cleaning for Jane Doe on July 1st at 9am");
    await page.getByRole("button", { name: "Submit" }).click();
    await expect(page.locator('[data-testid="approval-drawer"]')).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText(/booking confirmed/i)).toBeVisible({ timeout: 10_000 });

    // "Start over" button appears in terminal state.
    const startOverBtn = page.getByRole("button", { name: "Start over" });
    await expect(startOverBtn).toBeVisible();
    await startOverBtn.click();

    // UI resets: textarea is empty, run details are gone.
    await expect(page.getByLabel("Booking message")).toHaveValue("");
    await expect(page.getByText(/booking confirmed/i)).not.toBeVisible();
    await expect(startOverBtn).not.toBeVisible();
  });

  test("error state: shows retry button on a failed run", async ({ page }) => {
    await page.route("**/api/v1/runs", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ ...RUNNING_RUN }),
        });
      }
    });

    await page.route(`**/api/v1/runs/${RUN_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...RUNNING_RUN, status: "failed" }),
      });
    });

    await page.route(`**/api/v1/runs/${RUN_ID}/events`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"node":"chat_trigger","status":"failed","duration_ms":null}\n\nevent: end\ndata: {}\n\n',
      });
    });

    await page.goto("/");
    const errorInput = page.getByLabel("Booking message");
    const submitBtn3 = page.getByRole("button", { name: "Submit" });
    await errorInput.fill("trigger a failure");
    await expect(errorInput).toHaveValue("trigger a failure");
    await submitBtn3.click();

    // Retry button should appear somewhere in the UI for a failed run.
    await expect(page.getByRole("button", { name: /retry run/i })).toBeVisible({ timeout: 10_000 });
  });
});
