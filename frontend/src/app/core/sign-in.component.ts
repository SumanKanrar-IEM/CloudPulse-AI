import { Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { resolveCognitoConfig } from './api-config';
import {
  generateCodeChallenge,
  generateCodeVerifier,
  generateState,
  storePkceRoundTrip,
} from './pkce';

/**
 * FR-001, research.md R-402. Redirects to Cognito Hosted UI's `/oauth2/authorize`
 * with a generated PKCE challenge and `state`. `returnTo` (set by `authGuard` when
 * it redirects an unauthenticated request here) is carried through as Cognito's own
 * `state` parameter is already spoken for by CSRF protection -- stashed in
 * `sessionStorage` alongside the PKCE verifier instead, and read back by
 * `auth.callback.component.ts`.
 */
@Component({
  selector: 'cp-sign-in',
  standalone: true,
  template: `
    <p role="status">Redirecting to sign in…</p>
  `,
})
export class SignInComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);

  async ngOnInit(): Promise<void> {
    const config = resolveCognitoConfig();
    if (!config) {
      // Local dev / e2e without a real deployment: nothing to redirect to.
      return;
    }

    const returnTo = this.route.snapshot.queryParamMap.get('returnTo') ?? '/';
    sessionStorage.setItem('cp_pkce_return_to', returnTo);

    const verifier = generateCodeVerifier();
    const challenge = await generateCodeChallenge(verifier);
    const state = generateState();
    storePkceRoundTrip(verifier, state);

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      scope: 'openid email profile',
      code_challenge: challenge,
      code_challenge_method: 'S256',
      state,
    });
    window.location.href = `https://${config.domain}/oauth2/authorize?${params.toString()}`;
  }
}
