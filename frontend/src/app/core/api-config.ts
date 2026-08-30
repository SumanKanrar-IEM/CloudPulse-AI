/**
 * Resolves the API's base URL at runtime (spec 002).
 *
 * There is deliberately no build-time environment file here. The frontend
 * (CloudFront/S3) and the API (API Gateway) are separate origins with no proxy
 * between them (infra/modules/frontend has no API behavior), and the deploy
 * pipeline currently builds the frontend *before* `terraform apply` runs -- the API
 * Gateway URL is not yet known at `npm run build` time (see deploy-dev.yml/
 * deploy-prod.yml). A build-time Angular environment file cannot be correctly
 * populated under that ordering without reordering the pipeline.
 *
 * This reads a small runtime config object instead, so the seam a future deploy-time
 * fix plugs into already exists: `window.__CLOUDPULSE_CONFIG__`, populated by a
 * script tag a deploy step could inject into `index.html` (or upload as a sibling
 * JSON file) *after* the API URL is known. Until that deploy-side piece exists, this
 * resolves to `''` (relative/same-origin) -- correct for local development against a
 * dev-server proxy, not yet correct for a real CloudFront deployment. Flagged to the
 * user rather than guessed at, since it needs a CI/CD pipeline decision this session
 * did not make unilaterally.
 */

declare global {
  interface Window {
    __CLOUDPULSE_CONFIG__?: {
      apiBaseUrl?: string;
      /**
       * Test-only. Seeds `AuthService` with a fake session of this role,
       * bypassing the real `GET /me` call and the `authGuard` redirect to
       * `/sign-in` (spec 003, T034 -- that route doesn't exist yet, and there
       * is no way to reach an authenticated screen locally otherwise).
       *
       * Never set by any deploy step or production `index.html` -- only a
       * Playwright test's `page.addInitScript()` sets this, before the app
       * boots, same as `apiBaseUrl` above. `authGuard`'s own docstring is
       * explicit that it is "a usability control, not a security control":
       * this bypass changes what a test *sees rendered*, never what a real
       * backend call is authorized to do -- every HTTP request the seeded
       * session makes still needs a real (or Playwright-intercepted)
       * response, exactly as an unauthenticated one would.
       */
      e2eMockRole?: 'admin' | 'operator' | 'viewer';
    };
  }
}

export function resolveApiBaseUrl(): string {
  return (typeof window !== 'undefined' && window.__CLOUDPULSE_CONFIG__?.apiBaseUrl) || '';
}

export function resolveE2eMockRole(): 'admin' | 'operator' | 'viewer' | undefined {
  return typeof window !== 'undefined' ? window.__CLOUDPULSE_CONFIG__?.e2eMockRole : undefined;
}
