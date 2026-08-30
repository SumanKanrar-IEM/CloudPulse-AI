import { APP_INITIALIZER, ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, Routes } from '@angular/router';
import { provideApi } from './api/provide-api';
import { correlationInterceptor } from './core/correlation.interceptor';
import { resolveApiBaseUrl, resolveE2eMockRole } from './core/api-config';
import { authGuard, roleGuard } from './core/auth.guard';
import { AuthService } from './core/auth.service';

// Feature routes: accounts (spec 002), sdas (spec 003). Later specs (004-005) add
// their own below.
export const routes: Routes = [
  {
    path: 'accounts',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/accounts/accounts-list.component').then((m) => m.AccountsListComponent),
  },
  {
    path: 'sdas',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/sdas/sdas-list.component').then((m) => m.SdasListComponent),
  },
];

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([correlationInterceptor])),
    provideApi(resolveApiBaseUrl()),
    {
      // Test-only (spec 003, T034): seeds a fake session before routing
      // starts, when a Playwright test has set `window.__CLOUDPULSE_CONFIG__
      // .e2eMockRole` -- see api-config.ts for why this exists and why it
      // cannot grant real access. A no-op in every other context.
      provide: APP_INITIALIZER,
      multi: true,
      useFactory: (auth: AuthService) => () => {
        const role = resolveE2eMockRole();
        if (role) {
          auth.setUser({
            userId: 'e2e-test-user',
            email: 'e2e-test@example.com',
            role,
            tenantId: 'e2e-test-tenant',
          });
        }
      },
      deps: [AuthService],
    },
  ],
};
