import { Injectable, computed, signal } from '@angular/core';

/**
 * Session state.
 *
 * The role is read from `/me` on every session start and is **never** persisted or
 * cached beyond the session (FR-031a: the directory is the sole authority). There is
 * deliberately no `setRole` — nothing in this application may assign one.
 */
export interface CurrentUser {
  readonly userId: string;
  readonly email: string;
  readonly displayName?: string;
  readonly role: 'admin' | 'operator' | 'viewer';
  readonly tenantId: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly currentUser = signal<CurrentUser | null>(null);

  readonly user = this.currentUser.asReadonly();
  readonly isAuthenticated = computed(() => this.currentUser() !== null);
  readonly role = computed(() => this.currentUser()?.role ?? null);

  /**
   * Record the caller returned by `GET /me`.
   *
   * A user with no resolvable role never reaches here — the API returns 403 first
   * (FR-032a), so the frontend has no "signed in but roleless" state to handle beyond
   * showing the sign-in page.
   */
  setUser(user: CurrentUser | null): void {
    this.currentUser.set(user);
  }

  /**
   * FR-037: signing out must render the session unusable for all later requests.
   *
   * Clearing local state is not sufficient on its own — the Cognito logout endpoint
   * revokes the refresh token server-side (`enable_token_revocation`). Clearing without
   * revoking would leave a usable token behind.
   */
  signOut(hostedUiDomain: string, clientId: string, returnTo: string): void {
    this.currentUser.set(null);
    window.location.href =
      `https://${hostedUiDomain}/logout` +
      `?client_id=${encodeURIComponent(clientId)}` +
      `&logout_uri=${encodeURIComponent(returnTo)}`;
  }
}
