import { defineConfig, devices } from '@playwright/test';

// spec 004 T041: E2E_BASE_URL points this suite at a real deployed environment
// (deploy-dev.yml, after each successful deploy) instead of a local server --
// no local `webServer` in that case, since there is nothing to boot and
// nothing local to reuse.
const baseURL = process.env['E2E_BASE_URL'] ?? 'http://localhost:4200';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  // Serves the built app locally so the a11y suite runs in CI without a deployed
  // environment. SC-015's keyboard half is still a manual check (FR-047b).
  ...(process.env['E2E_BASE_URL']
    ? {}
    : {
        webServer: {
          command: 'npm run start -- --port=4200',
          url: 'http://localhost:4200',
          reuseExistingServer: !process.env['CI'],
          timeout: 120_000,
        },
      }),
});
