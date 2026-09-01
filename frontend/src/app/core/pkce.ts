/**
 * Authorization Code + PKCE helpers (research.md R-402).
 *
 * PKCE is not a style choice here -- Cognito's app client is configured
 * `allowed_oauth_flows = ["code"]` with `generate_secret = false` (a public SPA
 * client), and Cognito requires a code challenge for that combination. Uses the
 * Web Crypto API already available in every browser this app targets -- no new
 * dependency for something the platform already provides.
 */

const SESSION_STORAGE_VERIFIER_KEY = 'cp_pkce_verifier';
const SESSION_STORAGE_STATE_KEY = 'cp_pkce_state';

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length));
}

/** RFC 7636 code_verifier: 43-128 characters from the unreserved character set. */
export function generateCodeVerifier(): string {
  return base64UrlEncode(randomBytes(32));
}

/** RFC 7636 S256 code_challenge derived from a verifier. */
export async function generateCodeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return base64UrlEncode(new Uint8Array(digest));
}

export function generateState(): string {
  return base64UrlEncode(randomBytes(16));
}

/** Held only for the redirect round-trip; cleared as soon as the callback reads it. */
export function storePkceRoundTrip(verifier: string, state: string): void {
  sessionStorage.setItem(SESSION_STORAGE_VERIFIER_KEY, verifier);
  sessionStorage.setItem(SESSION_STORAGE_STATE_KEY, state);
}

export function consumePkceRoundTrip(): { verifier: string; state: string } | null {
  const verifier = sessionStorage.getItem(SESSION_STORAGE_VERIFIER_KEY);
  const state = sessionStorage.getItem(SESSION_STORAGE_STATE_KEY);
  sessionStorage.removeItem(SESSION_STORAGE_VERIFIER_KEY);
  sessionStorage.removeItem(SESSION_STORAGE_STATE_KEY);
  if (!verifier || !state) {
    return null;
  }
  return { verifier, state };
}
