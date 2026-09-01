import { test, expect, Page } from '@playwright/test';

/**
 * Inventory explorer (spec 004, S29, FR-010-FR-013). Mocked `GET /resources`
 * responses -- route interception, matching `sdas.spec.ts`'s established
 * pattern.
 */

interface Resource {
  id: string;
  accountId: string;
  arn: string;
  resourceType: string;
  service: string;
  region: string;
  sdaId: string | null;
  tagStatus: string;
  ownerStatus: string;
}

const RESOURCES: Resource[] = [
  {
    id: 'r-1',
    accountId: 'acct-1',
    arn: 'arn:aws:ec2:us-east-1:111:instance/i-1',
    resourceType: 'AWS::EC2::Instance',
    service: 'ec2',
    region: 'us-east-1',
    sdaId: null,
    tagStatus: 'compliant',
    ownerStatus: 'attributed',
  },
  {
    id: 'r-2',
    accountId: 'acct-1',
    arn: 'arn:aws:s3:::bucket-2',
    resourceType: 'AWS::S3::Bucket',
    service: 's3',
    region: 'us-west-2',
    sdaId: null,
    tagStatus: 'missing:owner',
    ownerStatus: 'unattributed',
  },
];

async function mockBackend(page: Page, resources: Resource[] = RESOURCES): Promise<void> {
  // A glob like `**/resources*` does not cross the `/` before a resource id
  // (found by running the detail-panel test, not by inspection) -- a regex,
  // matching sdas.spec.ts's own established pattern, covers both the list and
  // detail paths in one handler.
  await page.route(/\/resources(\/[^/?]+)?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    if (/\/resources\/[^/?]+$/.test(url.pathname)) {
      const id = url.pathname.split('/').pop();
      const resource = resources.find((r) => r.id === id);
      await route.fulfill({
        json: {
          id,
          arn: resource?.arn ?? 'unknown',
          resourceType: resource?.resourceType ?? 'unknown',
          service: resource?.service ?? '',
          region: resource?.region ?? '',
          tags: { owner: 'a@example.com' },
          detail: { state: 'running' },
          owner: resource?.ownerStatus === 'attributed' ? { ownerEmail: 'a@example.com', confidence: 'high' } : null,
          findings: [],
        },
      });
      return;
    }

    const service = url.searchParams.get('service');
    const filtered = service ? resources.filter((r) => r.service === service) : resources;
    await route.fulfill({
      json: { resources: filtered, page: 1, pageSize: 50, totalCount: filtered.length },
    });
  });
}

test.describe('inventory explorer', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
  });

  test('applying a filter narrows the visible table', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/inventory');

    await expect(page.getByRole('cell', { name: 'arn:aws:ec2:us-east-1:111:instance/i-1' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'arn:aws:s3:::bucket-2' })).toBeVisible();

    await page.getByLabel('Service').fill('ec2');
    await page.getByRole('button', { name: 'Apply filters' }).click();

    await expect(page.getByRole('cell', { name: 'arn:aws:ec2:us-east-1:111:instance/i-1' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'arn:aws:s3:::bucket-2' })).not.toBeVisible();
  });

  test('opening a resource shows its detail panel', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/inventory');

    await page.getByRole('button', { name: 'arn:aws:ec2:us-east-1:111:instance/i-1' }).click();

    await expect(page.getByRole('heading', { name: 'arn:aws:ec2:us-east-1:111:instance/i-1' })).toBeVisible();
    await expect(page.getByText('a@example.com (high confidence)')).toBeVisible();
    await expect(page.getByText('No findings.')).toBeVisible();
  });

  test('a zero-result filter shows the explicit empty state', async ({ page }) => {
    await mockBackend(page, []);
    await page.goto('/inventory');

    await expect(page.getByText('No matching resources.')).toBeVisible();
  });
});
