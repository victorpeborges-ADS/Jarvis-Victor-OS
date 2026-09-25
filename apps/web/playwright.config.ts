import { defineConfig, devices } from "@playwright/test";

const webOrigin = process.env.JARVIS_E2E_WEB_ORIGIN ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  timeout: 45_000,
  use: {
    baseURL: webOrigin,
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 }, channel: "chrome" }
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 }, channel: "chrome" }
    }
  ]
});
