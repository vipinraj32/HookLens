import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests drive the real stack: Anvil with the HookLens fixtures deployed
 * (scripts/dev-chain.sh), the FastAPI backend, and this Next.js app. Nothing is mocked.
 *
 * Servers already running on the expected ports are reused; otherwise they are started.
 * Anvil itself must already be running with fixtures deployed.
 */
const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3000);

export default defineConfig({
  testDir: "./e2e",
  timeout: 10 * 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./e2e-results",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } }, testIgnore: /mobile.spec.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/v1/health`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: `npm run start -- -p ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      reuseExistingServer: true,
      timeout: 120_000,
      env: { HOOKLENS_API_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
