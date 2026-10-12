import { test, expect, Page } from '@playwright/test';

/**
 * spec 005, T058: the Cost and Utilization screens each list a "No SDA" project row,
 * whose sdaId is null. Both tracked that list by `row.sdaId ?? 'none'`, which Angular
 * 18's template compiler turns into an undefined temporary: the render threw
 * `ReferenceError: tmp_.. is not defined` and every table after it stayed empty.
 * Mocked backend, the pattern every other e2e spec here follows.
 */

const UTILIZATION = {
  overall: { used: 3, provisioned: 4, percent: 75 },
  byAccount: [{ accountId: 'a1', alias: 'Prod', utilization: { used: 3, provisioned: 4, percent: 75 } }],
  byProject: [
    { sdaId: 's1', sdaName: 'Platform', utilization: { used: 2, provisioned: 2, percent: 100 } },
    { sdaId: null, sdaName: null, utilization: { used: 1, provisioned: 2, percent: 50 } },
  ],
};

const SPEND = {
  totalUsd: '30.00',
  byProject: [
    { sdaId: 's1', sdaName: 'Platform', totalUsd: '20.00' },
    { sdaId: null, sdaName: null, totalUsd: '10.00' },
  ],
  trend: [{ date: '2026-10-01', totalUsd: '30.00' }],
};

async function mockBackend(page: Page, errors: string[]): Promise<void> {
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
  });
  await page.route(/\/(utilization|spend\/summary|budgets)(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/utilization')) {
      await route.fulfill({ json: UTILIZATION });
    } else if (path.endsWith('/spend/summary')) {
      await route.fulfill({ json: SPEND });
    } else {
      await route.fulfill({ json: { budgets: [] } });
    }
  });
}

test('utilization lists the No SDA project row without a render error', async ({ page }) => {
  const errors: string[] = [];
  await mockBackend(page, errors);
  await page.goto('/utilization');

  await expect(page.getByRole('cell', { name: 'Prod' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Platform' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'No SDA' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('cost lists the No SDA project row without a render error', async ({ page }) => {
  const errors: string[] = [];
  await mockBackend(page, errors);
  await page.goto('/cost');

  await expect(page.getByRole('cell', { name: 'Platform' })).toBeVisible();
  await expect(page.getByRole('row', { name: /No SDA/ })).toBeVisible();
  expect(errors).toEqual([]);
});
