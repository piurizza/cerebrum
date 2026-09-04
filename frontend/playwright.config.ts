import { defineConfig, devices } from "@playwright/test";

// Local-only mobile E2E. This is NOT part of the CI gate (see ci.yml, which
// runs biome + tsc + vitest only) -- it drives a real Chromium against the
// running Docker stack so the mobile-responsive work (drawer, tap targets,
// full-screen modals, dvh layout) can be verified at a phone viewport with
// touch emulation and screenshots, which jsdom cannot do.
//
// Prerequisites:
//   * the Docker stack is up and serving the frontend on http://localhost:8080
//     (`docker compose up -d`)
//   * the test account exists (piurizza / provaprova123) -- e2e/fixtures.ts
//     logs in through the real form once per test
//   * a system Google Chrome is installed; `channel: "chrome"` uses it so
//     Playwright needs no downloaded browser (CI never installs one)
//
// Run: `npm run test:e2e` (from frontend/, with the Node 22 the rest of the
// frontend toolchain pins).

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? "line" : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: BASE_URL,
    channel: "chrome",
    // Deterministic layout runs: a service worker left registered by a
    // previous session (the app calls registerSW() on load) must not serve
    // stale shell HTML into these tests. The ReloadPrompt / offline specs
    // that arrive with U8 re-enable it per-project.
    serviceWorkers: "block",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "mobile-chrome",
      use: {
        // Pixel 7: Chromium engine, 412x915 CSS px, devicePixelRatio 2.625,
        // isMobile + hasTouch. `channel: "chrome"` from the top-level `use`
        // still applies (the preset only sets viewport/UA/touch flags).
        ...devices["Pixel 7"],
        channel: "chrome",
      },
    },
  ],
});
