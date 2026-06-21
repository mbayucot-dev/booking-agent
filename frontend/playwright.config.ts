import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // Run all tests in parallel — each test uses a fresh browser context.
  fullyParallel: true,
  // Fail the build on CI if tests are accidentally left in .only/.skip.
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Single worker on CI (limited cores); parallel locally.
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    // Base URL — the Next.js dev server (or `npm run build && npm start`).
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    // Capture traces on first retry so failures are diagnosable in CI.
    trace: "on-first-retry",
    // The BFF proxy guard: if FRONTEND_ACCESS_KEY is set, every request must
    // carry this header. The extraHTTPHeaders key passes it transparently.
    extraHTTPHeaders: process.env.FRONTEND_ACCESS_KEY
      ? { "x-access-key": process.env.FRONTEND_ACCESS_KEY }
      : {},
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  // Start (and teardown) the Next.js server automatically during `playwright test`.
  // Skipped if `PLAYWRIGHT_BASE_URL` is provided (pointing at an already-running server).
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "npm run build && node .next/standalone/server.js",
        url: "http://localhost:3000",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
