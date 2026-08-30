import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end browser tests for the AURA-X dashboard.
 *
 * These run against a live Vite dev server (http://localhost:5173) and a live
 * backend (http://localhost:8000). Start both before running:
 *
 *   backend:  uvicorn app.main:app --port 8000        (needs a DB; SQLite is fine)
 *   frontend: npm run dev
 *
 * then:  npm run e2e            (chromium only, fast)
 *        npm run e2e:all        (chromium + firefox + webkit)
 *
 * Specs that perform a real GitHub ingestion are tagged @network and skip
 * automatically when api.github.com is unreachable. Everything else uses
 * Playwright request interception and needs no outbound network.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'e2e/.report' }]],
  outputDir: 'e2e/.artifacts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
})
