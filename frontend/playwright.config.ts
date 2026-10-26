import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3100";
const authSecret = "playwright-test-secret-at-least-32-characters";
process.env.AUDIT_RUN ??= new Date().toISOString().replace(/[:.]/g, "-");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: process.env.CI ? 1 : undefined,
  expect: { timeout: 10_000 },
  outputDir: "test-results",
  reporter: [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: `"${process.execPath}" node_modules/next/dist/bin/next ${process.env.PLAYWRIGHT_PRODUCTION ? "start" : "dev --webpack"} -p 3100`,
        url: baseURL,
        reuseExistingServer: false,
        timeout: 120_000,
        env: {
          PATH: `${path.dirname(process.execPath)}${path.delimiter}${process.env.PATH ?? ""}`,
          AUTH_SECRET: authSecret,
          AUTH_URL: baseURL,
          AUTHENTIK_ISSUER: "https://auth.test/application/o/tdl-console",
          AUTHENTIK_CLIENT_ID: "test-client",
          AUTHENTIK_CLIENT_SECRET: "test-secret",
          AUTHENTIK_TOKEN_URL: "https://auth.test/application/o/token/",
          API_INTERNAL_URL: "http://127.0.0.1:8000",
        },
      },
});
