import { test, expect, Page } from '@playwright/test';

/**
 * Scan operations (spec 004, S31, FR-021-FR-023). Mocked accounts/scan-history/
 * trigger-scan responses -- route interception, matching
 * `findings-workbench.spec.ts`'s established pattern.
 */

interface Account {
  id: string;
  alias: string;
  connectionMode: string;
  awsAccountId: string;
  scanRegions: string[];
  status: string;
  createdAt: string;
}

const ACCOUNT: Account = {
  id: 'acct-1',
  alias: 'prod',
  connectionMode: 'local',
  awsAccountId: '111111111111',
  scanRegions: ['us-east-1'],
  status: 'verified',
  createdAt: '2026-01-01T00:00:00Z',
};

const FINISHED_SCAN = {
  id: 'scan-1',
  accountId: ACCOUNT.id,
  trigger: 'manual',
  status: 'succeeded',
  startedAt: '2026-01-01T00:00:00Z',
  finishedAt: '2026-01-01T00:03:00Z',
  resourceCount: 12,
  added: 3,
  removed: 1,
  changed: 2,
};

async function mockBackend(
  page: Page,
  options: { triggerFinishesAfterPolls?: number } = {},
): Promise<void> {
  let pollCount = 0;
  let triggered = false;
  const finishAfter = options.triggerFinishesAfterPolls ?? 0;

  await page.route(/\/accounts(\/[^/?]+\/scans)?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname.endsWith('/scans') && method === 'POST') {
      triggered = true;
      await route.fulfill({
        json: {
          id: 'scan-new',
          accountId: ACCOUNT.id,
          trigger: 'manual',
          status: 'running',
          startedAt: '2026-01-02T00:00:00Z',
        },
      });
      return;
    }

    if (url.pathname.endsWith('/scans') && method === 'GET') {
      pollCount += 1;
      const scans: Record<string, unknown>[] = [FINISHED_SCAN];
      if (triggered) {
        const runningStillGoing = pollCount <= finishAfter;
        scans.unshift(
          runningStillGoing
            ? {
                id: 'scan-new',
                accountId: ACCOUNT.id,
                trigger: 'manual',
                status: 'running',
                startedAt: '2026-01-02T00:00:00Z',
              }
            : {
                id: 'scan-new',
                accountId: ACCOUNT.id,
                trigger: 'manual',
                status: 'succeeded',
                startedAt: '2026-01-02T00:00:00Z',
                finishedAt: '2026-01-02T00:01:00Z',
                added: 1,
                removed: 0,
                changed: 0,
              },
        );
      }
      await route.fulfill({ json: { scans } });
      return;
    }

    await route.fulfill({ json: { accounts: [ACCOUNT] } });
  });
}

test.describe('scan operations', () => {
  test('scan history shows start time, duration, and deltas', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
    await mockBackend(page);
    await page.goto('/scans');

    await page.getByRole('button', { name: 'Show history' }).click();

    await expect(page.getByRole('cell', { name: 'succeeded' })).toBeVisible();
    await expect(page.getByRole('cell', { name: '3', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: '180s' })).toBeVisible();
  });

  test('triggering a scan shows status updating to a final state without a manual reload', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'operator' };
    });
    await mockBackend(page, { triggerFinishesAfterPolls: 1 });
    await page.goto('/scans');

    await page.getByRole('button', { name: 'Scan now' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Scanning' })).toBeVisible();

    await expect(page.getByRole('status').filter({ hasText: 'Scanning' })).not.toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByRole('button', { name: 'Scan now' })).toBeVisible();
  });

  test('a viewer sees history but has no trigger control', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page);
    await page.goto('/scans');

    await expect(page.getByText('prod')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Scan now' })).not.toBeVisible();
    await page.getByRole('button', { name: 'Show history' }).click();
    await expect(page.getByRole('cell', { name: 'succeeded' })).toBeVisible();
  });
});
