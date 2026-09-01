import { test, expect, Page } from '@playwright/test';

/**
 * Findings workbench (spec 004, S30, FR-014-FR-020a). Mocked findings API --
 * route interception, matching `inventory-explorer.spec.ts`'s established
 * pattern.
 */

interface Finding {
  id: string;
  resource: { id: string; arn: string; resourceType: string; region: string; accountId: string };
  ruleKey: string;
  ruleVersion: number;
  severity: string;
  status: string;
  openedAt: string;
  resolvedAt: string | null;
  acknowledgedAt: string | null;
  acknowledgedBy: string | null;
}

const FINDING: Finding = {
  id: 'f-1',
  resource: {
    id: 'r-1',
    arn: 'arn:aws:s3:::bucket-1',
    resourceType: 'AWS::S3::Bucket',
    region: 'us-east-1',
    accountId: 'acct-1',
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

async function mockBackend(
  page: Page,
  options: { findings?: Finding[]; suggestion?: Record<string, unknown> | null } = {},
): Promise<void> {
  const findings = options.findings ?? [FINDING];
  let acknowledged = false;

  await page.route(/\/findings(\/[^/?]+\/(acknowledge|suggestion))?(\?.*)?$/, async (route) => {
    if (route.request().resourceType() === 'document') {
      await route.continue();
      return;
    }
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname.endsWith('/acknowledge') && method === 'POST') {
      acknowledged = true;
      await route.fulfill({
        json: {
          findingId: FINDING.id,
          acknowledgedAt: '2026-01-02T00:00:00Z',
          acknowledgedBy: 'e2e-test-user',
        },
      });
      return;
    }

    if (url.pathname.endsWith('/suggestion') && method === 'GET') {
      await route.fulfill({
        json: options.suggestion === undefined
          ? { findingId: FINDING.id }
          : { findingId: FINDING.id, ...options.suggestion },
      });
      return;
    }

    if (url.pathname.endsWith('/suggestion') && method === 'PUT') {
      const body = route.request().postDataJSON();
      await route.fulfill({
        json: {
          findingId: FINDING.id,
          suggestionText: body.suggestionText,
          blastRadiusNote: body.blastRadiusNote,
          source: 'admin_seeded',
        },
      });
      return;
    }

    await route.fulfill({
      json: {
        findings: findings.map((f) => (acknowledged ? { ...f, acknowledgedAt: '2026-01-02T00:00:00Z' } : f)),
      },
    });
  });
}

test.describe('findings workbench', () => {
  test('an operator can acknowledge an open finding and it updates immediately', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'operator' };
    });
    await mockBackend(page);
    await page.goto('/findings');

    await expect(page.getByText('arn:aws:s3:::bucket-1')).toBeVisible();
    await page.getByRole('button', { name: 'Acknowledge' }).click();

    await expect(page.getByTestId('acknowledged-badge')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Acknowledge' })).not.toBeVisible();
  });

  test('a viewer sees findings but has no acknowledge control', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page);
    await page.goto('/findings');

    await expect(page.getByText('arn:aws:s3:::bucket-1')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Acknowledge' })).not.toBeVisible();
  });

  test('a finding with no suggestion shows the no-suggestion-available state', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page, { suggestion: null });
    await page.goto('/findings');

    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('No suggestion available.')).toBeVisible();
  });

  test('a finding with a suggestion shows it and its blast-radius note inline', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page, {
      suggestion: { suggestionText: 'Add the owner tag.', blastRadiusNote: 'Low risk.', source: 'ai_generated' },
    });
    await page.goto('/findings');

    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('Add the owner tag.')).toBeVisible();
    await expect(page.getByText('Low risk.')).toBeVisible();
  });

  test('an admin can attach a demo suggestion and it displays like a real one', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
    await mockBackend(page, { suggestion: null });
    await page.goto('/findings');

    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByText('No suggestion available.')).toBeVisible();

    await page.getByLabel('Suggestion text').fill('Test suggestion.');
    await page.getByLabel('Blast radius note').fill('Test note.');
    await page.getByRole('button', { name: 'Attach demo suggestion' }).click();

    await expect(page.getByText('Suggestion (test data):')).toBeVisible();
    await expect(page.getByText('Test suggestion.')).toBeVisible();
  });

  test('an operator has no control to attach a suggestion', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'operator' };
    });
    await mockBackend(page, { suggestion: null });
    await page.goto('/findings');

    await page.getByRole('button', { name: 'Show suggestion' }).click();
    await expect(page.getByRole('form', { name: 'Attach demo suggestion' })).not.toBeVisible();
  });

  test('a suggestion fetch failure shows a distinct error state, not a stuck spinner', async ({
    page,
  }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page);
    await page.route(/\/findings\/[^/?]+\/suggestion(\?.*)?$/, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ status: 500, json: { error: { code: 'INTERNAL_ERROR' } } });
        return;
      }
      await route.continue();
    });
    await page.goto('/findings');

    await page.getByRole('button', { name: 'Show suggestion' }).click();

    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByText('Loading suggestion…')).not.toBeVisible();
  });
});
