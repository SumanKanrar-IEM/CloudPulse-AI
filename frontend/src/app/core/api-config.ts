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
    __CLOUDPULSE_CONFIG__?: { apiBaseUrl?: string };
  }
}

export function resolveApiBaseUrl(): string {
  return (typeof window !== 'undefined' && window.__CLOUDPULSE_CONFIG__?.apiBaseUrl) || '';
}
