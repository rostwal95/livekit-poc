import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Inherit the pinned Playwright-managed Chromium default and explicit executable override.
// Separate discovery preserves the six-case scripted transport regression. P2/P3 media
// suites own their configs and private fixtures, so only the P1 real suite is matched.
export default defineConfig(base, {
  testMatch: '**/local-real.media.ts',
  timeout: 180_000,
  globalTimeout: 300_000,
  expect: { timeout: 45_000 },
  workers: 1,
  retries: 0,
  fullyParallel: false,
});
