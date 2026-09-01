/**
 * Resolves the API's base URL and Cognito Hosted UI parameters at runtime (spec 002,
 * extended spec 004 -- research.md R-401).
 *
 * There is deliberately no build-time environment file here. The frontend
 * (CloudFront/S3) and the API (API Gateway) are separate origins with no proxy
 * between them (infra/modules/frontend has no API behavior), and the deploy
 * pipeline builds the frontend *before* `terraform apply` runs -- the API Gateway
 * URL and the Cognito app client's own id/domain are not yet known at `npm run
 * build` time. A build-time Angular environment file cannot be correctly populated
 * under that ordering without reordering the pipeline.
 *
 * This reads a small runtime config object instead: `window.__CLOUDPULSE_CONFIG__`,
 * injected into `index.html` by `deploy-dev.yml`/`deploy-prod.yml` after the real
 * values are known (spec 004, T003). Resolves to `''`/`undefined` outside a real
 * deployment -- correct for local development against a dev-server proxy.
 */

declare global {
  interface Window {
    __CLOUDPULSE_CONFIG__?: {
      apiBaseUrl?: string;
      /** Cognito Hosted UI domain the sign-in flow redirects to (research.md R-402). */
      cognitoDomain?: string;
      /** The SPA's Cognito app client id (public, no secret -- PKCE covers this). */
      cognitoClientId?: string;
      /** Must exactly match the app client's configured `callback_urls` entry. */
      cognitoRedirectUri?: string;
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

export function resolveCognitoConfig(): {
  domain: string;
  clientId: string;
  redirectUri: string;
} | null {
  const config = typeof window !== 'undefined' ? window.__CLOUDPULSE_CONFIG__ : undefined;
  if (!config?.cognitoDomain || !config.cognitoClientId || !config.cognitoRedirectUri) {
    return null;
  }
  return {
    domain: config.cognitoDomain,
    clientId: config.cognitoClientId,
    redirectUri: config.cognitoRedirectUri,
  };
}

export function resolveE2eMockRole(): 'admin' | 'operator' | 'viewer' | undefined {
  return typeof window !== 'undefined' ? window.__CLOUDPULSE_CONFIG__?.e2eMockRole : undefined;
}
