import { Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { IdentityService } from '../api';
import { resolveCognitoConfig } from './api-config';
import { AuthService } from './auth.service';
import { consumePkceRoundTrip } from './pkce';

/**
 * Served at `/auth/callback` -- the exact path `infra/envs/dev/main.tf`'s Cognito
 * app client `callback_urls` already points at (confirmed, not assumed). Validates
 * `state`, exchanges the authorization code + PKCE verifier for tokens at Cognito's
 * `/oauth2/token`, calls `GET /me`, populates `AuthService`, and navigates to
 * `returnTo` (research.md R-402).
 */
@Component({
  selector: 'cp-auth-callback',
  standalone: true,
  template: `
    @if (error()) {
      <p role="alert">{{ error() }}</p>
    } @else {
      <p role="status">Finishing sign-in…</p>
    }
  `,
})
export class AuthCallbackComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly identity = inject(IdentityService);

  protected readonly error = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    const config = resolveCognitoConfig();
    if (!config) {
      this.error.set('Sign-in is not configured for this environment.');
      return;
    }

    const params = this.route.snapshot.queryParamMap;
    const code = params.get('code');
    const returnedState = params.get('state');
    const roundTrip = consumePkceRoundTrip();

    if (!code || !returnedState || !roundTrip || returnedState !== roundTrip.state) {
      this.error.set('Sign-in could not be verified. Please try again.');
      return;
    }

    try {
      const tokenResponse = await fetch(`https://${config.domain}/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          grant_type: 'authorization_code',
          client_id: config.clientId,
          code,
          redirect_uri: config.redirectUri,
          code_verifier: roundTrip.verifier,
        }),
      });
      if (!tokenResponse.ok) {
        this.error.set('Sign-in failed. Please try again.');
        return;
      }
      const tokens = (await tokenResponse.json()) as { access_token: string };
      this.auth.setAccessToken(tokens.access_token);

      const me = await firstValueFrom(this.identity.getCurrentUser());
      this.auth.setUser({
        userId: me.userId,
        email: me.email,
        displayName: me.displayName ?? undefined,
        role: me.role as 'admin' | 'operator' | 'viewer',
        tenantId: me.tenantId,
      });

      const returnTo = sessionStorage.getItem('cp_pkce_return_to') ?? '/';
      sessionStorage.removeItem('cp_pkce_return_to');
      await this.router.navigateByUrl(returnTo);
    } catch {
      this.auth.setAccessToken(null);
      this.error.set('Sign-in failed. Please try again.');
    }
  }
}
