import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig } from '@playwright/test';

/**
 * End-to-end tests against the REAL FastAPI backend (stand-in adapters, no AI).
 *   npm run test:e2e:api
 * Starts its own backend on port 8010 with a fresh data folder, so it never touches your dev data
 * and can run next to `npm run dev:stack`.
 */
const API_PORT = 8010;
// Set once in the main process; workers inherit it, so every process agrees on the folder.
process.env.LL_E2E_DATA_DIR ??= join(tmpdir(), `legallens-e2e-${Date.now()}`);

export default defineConfig({
  testDir: './e2e',
  testMatch: 'integration.spec.ts',
  globalSetup: './e2e/global-setup.backend.ts',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4174',
    // Local default: the installed Microsoft Edge (no download). CI sets PW_CHANNEL=chromium.
    channel: process.env.PW_CHANNEL ?? 'msedge',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'uv run --directory ../backend legallens-api',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: {
        LL_PORT: String(API_PORT),
        LL_DATA_DIR: process.env.LL_E2E_DATA_DIR,
        // Slow enough to press Stop mid-answer, fast enough to keep the run short.
        LL_STANDIN_TOKEN_DELAY_MS: '40',
        LL_LOG_JSON: 'false',
      },
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      // Plain vite (no typecheck): CI typechecks separately, and this keeps startup fast.
      command: 'npx vite build --mode backend && npx vite preview --mode backend',
      url: 'http://localhost:4174',
      env: { VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
