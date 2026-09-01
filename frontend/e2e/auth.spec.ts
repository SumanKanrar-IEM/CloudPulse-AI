import { test, expect, Page } from '@playwright/test';

/**
 * Sign-in / sign-out / navigation (spec 004, S27, FR-001-FR-005, research.md R-402).
 *
 * The Cognito Hosted UI redirect and token exchange are intercepted via
 * `page.route()` rather than exercised against a real Cognito dependency -- the
 * same tradeoff `e2eMockRole` already made for other screens (spec 003, T034): a
 * real external IdP in CI is slow, flaky, and needs a real test user's credentials
 * to live somewhere CI can reach. This proves the flow's own logic (PKCE params,
 * state validation, token exchange, the /me call, the redirect to returnTo), not
 * Cognito's own behavior.
 *
 * Role-differentiated behavior is scoped to what was actually implemented, not the
 * spec's most literal reading: every screen in this platform is all-role read
 * (confirmed directly -- accounts FR-010a, sdas FR-030, every spec 004 screen's own
 * FR-027), so there is no case today where an entire nav item is hidden per role;
 * the shell's nav is uniform and unconditional (see shell.component.ts's own
 * docstring). What differs per role is control-level gating *within* each screen,
 * already proven by sdas.spec.ts's own "a non-admin cannot register, edit, or
 * remove" test -- not re-tested here.
 */

const COGNITO_DOMAIN = 'fake-cognito.example.com';
const CLIENT_ID = 'test-client-id';

async function seedCognitoConfig(page: Page): Promise<void> {
  await page.addInitScript(
    ({ domain, clientId }) => {
      window.__CLOUDPULSE_CONFIG__ = {
        cognitoDomain: domain,
        cognitoClientId: clientId,
        cognitoRedirectUri: `${window.location.origin}/auth/callback`,
      };
    },
    { domain: COGNITO_DOMAIN, clientId: CLIENT_ID },
  );
}

/** Intercepts the two external Cognito calls the flow makes, echoing back a fake session. */
async function mockCognito(page: Page): Promise<void> {
  await page.route(`https://${COGNITO_DOMAIN}/oauth2/authorize*`, async (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('client_id')).toBe(CLIENT_ID);
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
    expect(url.searchParams.get('code_challenge')).toBeTruthy();
    const state = url.searchParams.get('state');
    expect(state).toBeTruthy();

    const redirectUri = url.searchParams.get('redirect_uri')!;
    await route.fulfill({
      status: 302,
      headers: { location: `${redirectUri}?code=fake-auth-code&state=${state}` },
    });
  });

  await page.route(`https://${COGNITO_DOMAIN}/oauth2/token`, async (route) => {
    const body = new URLSearchParams(route.request().postData() ?? '');
    expect(body.get('grant_type')).toBe('authorization_code');
    expect(body.get('code')).toBe('fake-auth-code');
    expect(body.get('code_verifier')).toBeTruthy();
    await route.fulfill({
      json: { access_token: 'fake-access-token', token_type: 'Bearer', expires_in: 3600 },
    });
  });
}

async function mockMe(page: Page, role: 'admin' | 'operator' | 'viewer'): Promise<void> {
  await page.route('**/me', async (route) => {
    await route.fulfill({
      json: { userId: 'u-1', email: `${role}@example.com`, role, tenantId: 't-1' },
    });
  });
}

test.describe('sign-in / sign-out', () => {
  test('redirects to the Hosted UI with a PKCE challenge and state, completes the callback, and lands on returnTo', async ({
    page,
  }) => {
    await seedCognitoConfig(page);
    await mockCognito(page);
    await mockMe(page, 'admin');

    await page.goto('/sign-in?returnTo=%2Faccounts');
    await expect(page).toHaveURL(/\/accounts$/);
    await expect(page.getByRole('heading', { name: 'Connected accounts' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  });

  test('an unauthenticated direct request to a guarded route redirects to sign-in', async ({ page }) => {
    await page.goto('/accounts');
    await expect(page).toHaveURL(/\/sign-in\?returnTo=/);
  });

  test('signing out clears the session and the next load requires signing in again', async ({ page }) => {
    await seedCognitoConfig(page);
    await mockCognito(page);
    await mockMe(page, 'admin');
    await page.goto('/sign-in?returnTo=%2Faccounts');
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();

    // Cognito's own logout page is external; intercept it too rather than let the
    // browser try to actually navigate there.
    await page.route(`https://${COGNITO_DOMAIN}/logout*`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'text/html', body: '<p>Signed out</p>' });
    });
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByText('Signed out')).toBeVisible();

    // Clearing the Cognito config (not unroute/abort -- either still lets
    // SignInComponent's own `window.location.href =` fire and commit to leaving
    // the document, landing on chrome-error:// once the target is gone) makes
    // SignInComponent no-op on mount, same as the unauthenticated-redirect test
    // above -- isolates this assertion to what it actually checks: authGuard's own
    // redirect, not the sign-in page's downstream behavior once there.
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = {};
    });

    // A later, fresh visit to a guarded route has no session left.
    await page.goto('/accounts');
    await expect(page).toHaveURL(/\/sign-in\?returnTo=/);
  });

  test('the shell remains usable at phone width without horizontal scrolling', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.addInitScript(() => {
      window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: 'admin' };
    });
    await page.goto('/accounts');

    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
});

test.describe('navigation is uniform for every authenticated role', () => {
  for (const role of ['admin', 'operator', 'viewer'] as const) {
    test(`${role} sees the full nav and a sign-out control`, async ({ page }) => {
      await page.addInitScript(
        (r) => {
          window.__CLOUDPULSE_CONFIG__ = { e2eMockRole: r };
        },
        role,
      );
      await page.goto('/accounts');

      const nav = page.getByRole('navigation', { name: 'Primary' });
      for (const label of ['Overview', 'Inventory', 'Findings', 'Scan operations', 'Accounts', 'SDAs']) {
        await expect(nav.getByRole('link', { name: label })).toBeVisible();
      }
      await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
    });
  }

  test('an unauthenticated visitor sees the nav and a sign-in link, not sign-out', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign out' })).not.toBeVisible();
  });
});
