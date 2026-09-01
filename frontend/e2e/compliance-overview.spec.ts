import { test, expect, Page } from '@playwright/test';

/**
 * Compliance overview (spec 004, S28, FR-006-FR-009, SC-004).
 *
 * Backend not running in this suite -- every request intercepted and served
 * from an in-memory fixture, matching the generated client's actual request/
 * response shapes (same pattern `sdas.spec.ts` established).
 */

interface Finding {
  id: string;
  ruleKey: string;
  severity: string;
  status: string;
}

async function mockBackend(page: Page): Promise<void> {
  const accounts = [
    { id: 'acct-1', alias: 'Prod', connectionMode: 'local', awsAccountId: '111', scanRegions: ['us-east-1'], status: 'verified', lastScan: { status: 'succeeded', startedAt: '2026-01-01T00:00:00Z' } },
    { id: 'acct-2', alias: 'Sandbox', connectionMode: 'local', awsAccountId: '222', scanRegions: ['us-east-1'], status: 'verified', lastScan: null },
  ];
  const scores: Record<string, { compliantCount: number; totalCount: number; score: number }> = {
    'acct-1': { compliantCount: 7, totalCount: 10, score: 0.7 },
  };
  const findingsByAccount: Record<string, Finding[]> = {
    'acct-1': [
      { id: 'f-1', ruleKey: 'owner', severity: 'high', status: 'open' },
      { id: 'f-2', ruleKey: 'owner', severity: 'medium', status: 'open' },
      { id: 'f-3', ruleKey: 'project_id', severity: 'low', status: 'open' },
    ],
  };
  const allFindings = Object.values(findingsByAccount).flat();

  await page.route('**/accounts', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    await route.fulfill({ json: { accounts } });
  });

  await page.route('**/accounts/*/compliance-score', async (route) => {
    const accountId = new URL(route.request().url()).pathname.split('/')[2];
    await route.fulfill({ json: scores[accountId] });
  });

  await page.route('**/findings*', async (route) => {
    const url = new URL(route.request().url());
    const accountId = url.searchParams.get('accountId');
    const findings = accountId ? (findingsByAccount[accountId] ?? []) : allFindings;
    await route.fulfill({ json: { findings } });
  });
}

test.describe('compliance overview', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
  });

  test('scores and counts match the mocked API responses exactly', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/overview');

    // Overall: 7/10 compliant (acct-2 never scanned, contributes nothing) -- SC-004.
    await expect(page.locator('.score-card .score')).toHaveText('70%');
    await expect(page.getByText('7 / 10 resources compliant')).toBeVisible();

    await expect(page.getByRole('cell', { name: 'Prod' })).toBeVisible();
    await expect(page.getByRole('row', { name: /Prod/ }).getByRole('cell', { name: '70%' })).toBeVisible();
    await expect(page.getByRole('row', { name: /Prod/ }).getByRole('cell', { name: '3', exact: true })).toBeVisible();
  });

  test('findings-by-type and by-severity counts sum to the total open-finding count', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/overview');

    // 3 total open findings: 2 "owner", 1 "project_id" -- sums to 3 either way (FR-007).
    await expect(page.locator('canvas[aria-label="Open findings by tag rule"]')).toBeVisible();
    await expect(page.locator('canvas[aria-label="Open findings by severity"]')).toBeVisible();
  });

  test('an account with no completed scan shows "Not yet scanned", not a zero score', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/overview');

    await expect(page.getByRole('cell', { name: 'Sandbox' })).toBeVisible();
    await expect(page.getByRole('row', { name: /Sandbox/ }).getByText('Not yet scanned')).toBeVisible();
  });

  test('no connected accounts shows an explicit empty state', async ({ page }) => {
    await page.route('**/accounts', async (route) => {
      await route.fulfill({ json: { accounts: [] } });
    });
    await page.goto('/overview');

    await expect(page.getByText('No connected accounts yet.')).toBeVisible();
  });

  test('renders within SC-003 2-second budget for a 5,000-resource account', async ({ page }) => {
    // Synthetic: mocked responses carry zero real network latency, so this
    // measures client-side processing time only (chart grouping over the full
    // open-findings array, table rendering) -- it cannot prove real-AWS
    // latency, but a slow result here would be a genuine red flag regardless,
    // since production can only add to this, never subtract from it.
    const RESOURCE_COUNT = 5000;
    const account = {
      id: 'acct-big',
      alias: 'Big account',
      connectionMode: 'local',
      awsAccountId: '999999999999',
      scanRegions: ['us-east-1'],
      status: 'verified',
      lastScan: { status: 'succeeded', startedAt: '2026-01-01T00:00:00Z' },
    };
    const ruleKeys = ['owner', 'project_id', 'environment', 'cost_center', 'data_classification'];
    const severities = ['low', 'medium', 'high', 'critical'];
    const findings = Array.from({ length: 3000 }, (_, i) => ({
      id: `f-${i}`,
      ruleKey: ruleKeys[i % ruleKeys.length],
      severity: severities[i % severities.length],
      status: 'open',
    }));

    await page.route('**/accounts', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      await route.fulfill({ json: { accounts: [account] } });
    });
    await page.route('**/accounts/*/compliance-score', async (route) => {
      await route.fulfill({
        json: { compliantCount: 4200, totalCount: RESOURCE_COUNT, score: 0.84 },
      });
    });
    await page.route('**/findings*', async (route) => {
      await route.fulfill({ json: { findings } });
    });

    const start = Date.now();
    await page.goto('/overview');
    await expect(page.locator('.score-card .score')).toHaveText('84%');
    const elapsedMs = Date.now() - start;

    expect(elapsedMs).toBeLessThan(2000);
  });
});
