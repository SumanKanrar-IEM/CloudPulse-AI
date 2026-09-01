import { APP_INITIALIZER, ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, Routes } from '@angular/router';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';
import { provideApi } from './api/provide-api';
import { correlationInterceptor } from './core/correlation.interceptor';
import { authInterceptor } from './core/auth.interceptor';
import { resolveApiBaseUrl, resolveE2eMockRole } from './core/api-config';
import { authGuard, roleGuard } from './core/auth.guard';
import { AuthService } from './core/auth.service';

// Feature routes: accounts (spec 002), sdas (spec 003), overview/inventory/findings/
// scans (spec 004). sign-in/auth/callback (spec 004) are the two unauthenticated
// routes everything else depends on reaching.
export const routes: Routes = [
  // FR-006 default landing route after sign-in.
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  {
    path: 'overview',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/overview/compliance-overview.component').then(
        (m) => m.ComplianceOverviewComponent,
      ),
  },
  {
    path: 'sign-in',
    loadComponent: () => import('./core/sign-in.component').then((m) => m.SignInComponent),
  },
  {
    path: 'auth/callback',
    loadComponent: () =>
      import('./core/auth.callback.component').then((m) => m.AuthCallbackComponent),
  },
  {
    path: 'inventory',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/inventory/inventory-explorer.component').then(
        (m) => m.InventoryExplorerComponent,
      ),
  },
  {
    path: 'findings',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/findings/findings-workbench.component').then(
        (m) => m.FindingsWorkbenchComponent,
      ),
  },
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
    provideHttpClient(withInterceptors([authInterceptor, correlationInterceptor])),
    provideApi(resolveApiBaseUrl()),
    provideCharts(withDefaultRegisterables()),
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
