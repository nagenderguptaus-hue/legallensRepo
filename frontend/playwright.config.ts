import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // Mock API only; integration.spec.ts runs against the real backend (playwright.backend.config.ts).
  testMatch: 'demo.spec.ts',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4173',
    // Local default: the installed Microsoft Edge (no download). CI sets PW_CHANNEL=chromium.
    channel: process.env.PW_CHANNEL ?? 'msedge',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run build && npm run preview',
    url: 'http://localhost:4173',
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
