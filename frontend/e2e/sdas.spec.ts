import { test, expect, Page } from '@playwright/test';

/**
 * SDA admin screen, functional (spec 003, T034, S18b, FR-007-FR-010b).
 *
 * There is no way to reach an authenticated route in this repo yet -- no
 * `/sign-in` route exists (spec 001/002 never implemented one) and there is
 * no mock-auth mechanism until this task added one. `window.__CLOUDPULSE_
 * CONFIG__.e2eMockRole` (api-config.ts) seeds a fake session at app boot,
 * test-only, so this suite can exercise the guarded `/sdas` route at all.
 *
 * The backend is not running in this suite (`playwright.config.ts`'s
 * `webServer` starts only the Angular dev server) -- every request is
 * intercepted and served from an in-memory fixture store below, matching the
 * generated client's actual request/response shapes exactly (the OpenAPI
 * contract, not a live database). This proves the screen calls the right
 * endpoints with the right payloads and renders what they return -- the
 * contract-level half of "confirm effect matches the API." Proving the real
 * backend/database effect end-to-end is T032's live-verification concern,
 * deferred by explicit user decision (2026-08-29), not re-litigated here.
 */

interface Sda {
  id: string;
  name: string;
  ownerEmail: string;
  team?: string | null;
  tagValues: Record<string, string>;
}

async function mockBackend(page: Page): Promise<{ sdas: Sda[] }> {
  const state = {
    sdas: [
      { id: 'sda-1', name: 'Platform', ownerEmail: 'platform@example.com', tagValues: { team: 'platform' } },
    ] as Sda[],
  };

  // `/sdas` is both the Angular route's own URL and the API path -- same
  // origin, same pathname, in this dev setup. One handler, dispatched by
  // pathname/method, so there is no glob-overlap ambiguity between multiple
  // `page.route()` registrations to get wrong -- and the top-level page
  // navigation to /sdas (a "document" request, not xhr/fetch) always falls
  // through untouched, or the Angular app itself never loads.
  await page.route(/\/sdas(\/.*)?$/, async (route) => {
    const request = route.request();
    if (request.resourceType() === 'document') {
      await route.continue();
      return;
    }

    const path = new URL(request.url()).pathname;
    const method = request.method();

    if (path.endsWith('/unmatched-resources')) {
      await route.fulfill({ json: { resources: [] } });
      return;
    }

    if (path === '/sdas' || path.endsWith('/api/sdas')) {
      if (method === 'GET') {
        await route.fulfill({ json: { sdas: state.sdas } });
        return;
      }
      if (method === 'POST') {
        const body = request.postDataJSON();
        const created: Sda = { id: `sda-${state.sdas.length + 1}`, ...body };
        state.sdas.push(created);
        await route.fulfill({ status: 201, json: created });
        return;
      }
    }

    const sdaId = path.split('/').pop();
    if (method === 'PATCH') {
      const body = request.postDataJSON();
      const sda = state.sdas.find((s) => s.id === sdaId);
      if (sda) Object.assign(sda, body);
      await route.fulfill({ json: sda });
      return;
    }
    if (method === 'DELETE') {
      state.sdas = state.sdas.filter((s) => s.id !== sdaId);
      await route.fulfill({ status: 204, body: '' });
      return;
    }

    await route.continue();
  });

  return state;
}

test.describe('SDA admin screen', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
  });

  test('lists registered SDAs', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/sdas');

    await expect(page.getByRole('heading', { name: 'Service delivery areas' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Platform', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'platform@example.com' })).toBeVisible();
  });

  test('registering an SDA sends the correct request and shows it in the list', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/sdas');

    await page.getByRole('button', { name: 'Register an SDA' }).click();
    await page.getByLabel('Name').fill('Data Platform');
    await page.getByLabel('Owner email').fill('data@example.com');
    await page.getByLabel('Tag-value mapping').fill('team=data');

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().endsWith('/sdas') && req.method() === 'POST'),
      page.getByRole('button', { name: 'Register' }).click(),
    ]);
    expect(request.postDataJSON()).toEqual({
      name: 'Data Platform',
      ownerEmail: 'data@example.com',
      tagValues: { team: 'data' },
    });

    await expect(page.getByRole('cell', { name: 'Data Platform' })).toBeVisible();
  });

  test('editing an SDA sends a PATCH with the changed owner email', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/sdas');

    await page.getByRole('button', { name: 'Edit' }).click();
    await page.getByLabel('Owner email').fill('new-owner@example.com');

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/sdas/sda-1') && req.method() === 'PATCH'),
      page.getByRole('button', { name: 'Save changes' }).click(),
    ]);
    expect(request.postDataJSON().ownerEmail).toBe('new-owner@example.com');

    await expect(page.getByRole('cell', { name: 'new-owner@example.com' })).toBeVisible();
  });

  test('removing an SDA sends a DELETE and it disappears from the list', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/sdas');

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/sdas/sda-1') && req.method() === 'DELETE'),
      page.getByRole('button', { name: 'Remove' }).click(),
    ]);
    expect(request.method()).toBe('DELETE');

    await expect(page.getByRole('cell', { name: 'Platform', exact: true })).not.toBeVisible();
    await expect(page.getByText('No SDAs registered yet.')).toBeVisible();
  });

  test('a non-admin cannot register, edit, or remove an SDA', async ({ page }) => {
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'viewer' };
    });
    await mockBackend(page);
    await page.goto('/sdas');

    await expect(page.getByRole('button', { name: 'Register an SDA', disabled: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit', disabled: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Remove', disabled: true })).toBeVisible();
  });

  test('the "No SDA" bucket shows unmatched resources', async ({ page }) => {
    await mockBackend(page);
    await page.route('**/sdas/unmatched-resources', async (route) => {
      await route.fulfill({
        json: {
          resources: [
            {
              id: 'r-1',
              arn: 'arn:aws:ec2:us-east-1:123456789012:instance/i-unmatched',
              resourceType: 'AWS::EC2::Instance',
              region: 'us-east-1',
              accountId: '123456789012',
            },
          ],
        },
      });
    });
    await page.goto('/sdas');

    await expect(page.getByRole('heading', { name: '"No SDA" bucket' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'AWS::EC2::Instance' })).toBeVisible();
  });
});
