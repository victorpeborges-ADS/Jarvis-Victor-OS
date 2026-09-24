import { defineConfig, devices } from "@playwright/test";

const browserServerEnv = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => ![
    "JARVIS_LOCAL_PASSPHRASE", "JARVIS_DATABASE_PATH", "JARVIS_E2E_DATABASE_PATH",
    "JARVIS_E2E_PASSPHRASE", "JARVIS_E2E_API_ORIGIN", "JARVIS_E2E_WEB_ORIGIN",
    "JARVIS_BIND_HOST", "JARVIS_BIND_PORT"
  ].includes(key))
) as Record<string, string>;
const webOrigin = process.env.JARVIS_E2E_WEB_ORIGIN ?? "http://127.0.0.1:3000";
const apiOrigin = process.env.JARVIS_E2E_API_ORIGIN ?? "http://127.0.0.1:8000";
browserServerEnv.NEXT_PUBLIC_JARVIS_API_URL = apiOrigin;

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
  ],
  webServer: {
    command: "npm run build && npx next start --hostname 127.0.0.1 --port 3000",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: false,
    timeout: 180 * 1000,
    env: browserServerEnv
  }
});
