import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Route guard (FR-034).
 *
 * This is a **usability** control, not a security control. The API enforces
 * authorisation on every request regardless of what the browser does — a guard runs in
 * code the user controls, so it can only decide what to render, never what is
 * permitted. Treating it as security would be the classic mistake.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isAuthenticated()) {
    return true;
  }
  return router.createUrlTree(['/sign-in'], {
    queryParams: { returnTo: state.url },
  });
};

/**
 * Restrict a route to specific roles.
 *
 * Mirrors the API's `require_role`. Again: presentation only. The server refuses
 * independently, and a caller mapping to zero or multiple directory groups never gets
 * a role at all (FR-032a).
 */
export const roleGuard =
  (...allowed: ReadonlyArray<'admin' | 'operator' | 'viewer'>): CanActivateFn =>
  () => {
    const role = inject(AuthService).role();
    return role !== null && allowed.includes(role);
  };
