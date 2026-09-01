import { test, expect, Page } from '@playwright/test';

/**
 * End-to-end smoke suite covering each P1 user story's primary journey in one
 * pass, per role (spec 004, S33, FR-024): sign in; view compliance overview;
 * filter and drill into inventory; filter, view a suggestion on, and
 * acknowledge a finding. Mocked backend -- route interception, matching the
 * pattern every other e2e spec in this suite already established.
 */

const ACCOUNT = {
  id: 'acct-1',
  alias: 'Prod',
  connectionMode: 'local',
  awsAccountId: '111111111111',
  scanRegions: ['us-east-1'],
  status: 'verified',
  lastScan: { status: 'succeeded', startedAt: '2026-01-01T00:00:00Z' },
};

const RESOURCE = {
  id: 'r-1',
  accountId: ACCOUNT.id,
  arn: 'arn:aws:s3:::bucket-1',
  resourceType: 'AWS::S3::Bucket',
  service: 's3',
  region: 'us-east-1',
  sdaId: null,
  tagStatus: 'missing:owner',
  ownerStatus: 'unattributed',
};

const FINDING = {
  id: 'f-1',
  resource: {
    id: RESOURCE.id,
    arn: RESOURCE.arn,
    resourceType: RESOURCE.resourceType,
    region: RESOURCE.region,
    accountId: ACCOUNT.id,
  },
  ruleKey: 'owner',
  ruleVersion: 1,
  severity: 'high',
  status: 'open',
  openedAt: '2026-01-01T00:00:00Z',
  resolvedAt: null,
  acknowledgedAt: null,
  acknowledgedBy: null,
};

async function mockBackend(page: Page): Promise<void> {
  await page.route(/\/accounts(\/[^/?]+\/compliance-score)?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/compliance-score')) {
      await route.fulfill({ json: { compliantCount: 7, totalCount: 10, score: 0.7 } });
      return;
    }
    await route.fulfill({ json: { accounts: [ACCOUNT] } });
  });

  await page.route(/\/resources(\/[^/?]+)?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (/\/resources\/[^/?]+$/.test(url.pathname)) {
      await route.fulfill({
        json: {
          id: RESOURCE.id,
          arn: RESOURCE.arn,
          resourceType: RESOURCE.resourceType,
          service: RESOURCE.service,
          region: RESOURCE.region,
          tags: {},
          detail: {},
          owner: null,
          findings: [FINDING],
        },
      });
      return;
    }
    const service = url.searchParams.get('service');
    const resources = service && service !== RESOURCE.service ? [] : [RESOURCE];
    await route.fulfill({ json: { resources, page: 1, pageSize: 50, totalCount: resources.length } });
  });

  await page.route(/\/findings(\/[^/?]+\/(acknowledge|suggestion))?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname.endsWith('/acknowledge') && method === 'POST') {
      await route.fulfill({
        json: { findingId: FINDING.id, acknowledgedAt: '2026-01-02T00:00:00Z', acknowledgedBy: 'e2e-test-user' },
      });
      return;
    }
    if (url.pathname.endsWith('/suggestion') && method === 'GET') {
      await route.fulfill({
        json: {
          findingId: FINDING.id,
          suggestionText: 'Add the owner tag.',
          blastRadiusNote: 'Low risk: tag-only change.',
          source: 'ai_generated',
        },
      });
      return;
    }
    await route.fulfill({ json: { findings: [FINDING] } });
  });
}

test.describe('dashboard smoke: each P1 journey, per role', () => {
  test('admin: overview, inventory drill-down, findings + suggestion + acknowledge', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
    await mockBackend(page);

    await page.goto('/overview');
    await expect(page.locator('.score-card .score')).toHaveText('70%');

    await page.goto('/inventory');
    await page.getByLabel('Service').fill('s3');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await page.getByRole('button', { name: RESOURCE.arn }).click();
    await expect(page.getByRole('heading', { name: RESOURCE.arn })).toBeVisible();

    await page.goto('/findings');
    await expect(page.getByText(RESOURCE.arn)).toBeVisible();
    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('Add the owner tag.')).toBeVisible();
    await page.getByRole('button', { name: 'Acknowledge' }).click();
    await expect(page.getByTestId('acknowledged-badge')).toBeVisible();
  });

  test('operator: same journey, can also acknowledge', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'operator' };
    });
    await mockBackend(page);

    await page.goto('/overview');
    await expect(page.locator('.score-card .score')).toHaveText('70%');

    await page.goto('/inventory');
    await page.getByLabel('Service').fill('s3');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await page.getByRole('button', { name: RESOURCE.arn }).click();
    await expect(page.getByRole('heading', { name: RESOURCE.arn })).toBeVisible();

    await page.goto('/findings');
    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('Add the owner tag.')).toBeVisible();
    await page.getByRole('button', { name: 'Acknowledge' }).click();
    await expect(page.getByTestId('acknowledged-badge')).toBeVisible();
  });

  test('viewer: same journey, no acknowledge control', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page);

    await page.goto('/overview');
    await expect(page.locator('.score-card .score')).toHaveText('70%');

    await page.goto('/inventory');
    await page.getByLabel('Service').fill('s3');
    await page.getByRole('button', { name: 'Apply filters' }).click();
    await page.getByRole('button', { name: RESOURCE.arn }).click();
    await expect(page.getByRole('heading', { name: RESOURCE.arn })).toBeVisible();

    await page.goto('/findings');
    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('Add the owner tag.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Acknowledge' })).not.toBeVisible();
  });
});
