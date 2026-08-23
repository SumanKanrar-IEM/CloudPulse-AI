import { ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter, Routes } from '@angular/router';
import { provideApi } from './api/provide-api';
import { correlationInterceptor } from './core/correlation.interceptor';
import { resolveApiBaseUrl } from './core/api-config';
import { authGuard, roleGuard } from './core/auth.guard';

// Feature routes: accounts (spec 002). Later specs (003-005) add their own below.
export const routes: Routes = [
  {
    path: 'accounts',
    canActivate: [authGuard, roleGuard('admin', 'operator', 'viewer')],
    loadComponent: () =>
      import('./features/accounts/accounts-list.component').then((m) => m.AccountsListComponent),
  },
];

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([correlationInterceptor])),
    provideApi(resolveApiBaseUrl()),
  ],
};
