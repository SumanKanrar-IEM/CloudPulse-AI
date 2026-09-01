import { inject } from '@angular/core';
import { HttpInterceptorFn } from '@angular/common/http';
import { AuthService } from './auth.service';

/**
 * Attaches `Authorization: Bearer <token>` to every platform API request (FR-001).
 *
 * Found missing while implementing sign-in (spec 004, T008): nothing in this
 * application attached a bearer token to outgoing requests before this — every
 * `GET /me` call this session verified was made directly with `curl`, never through
 * the running Angular app, which is why the gap went unnoticed. The generated
 * client's own `Configuration.addCredentialToHeaders` mechanism is a no-op unless
 * something supplies a credential; this interceptor is that something, read fresh
 * from `AuthService` on every request rather than baked into the `Configuration`
 * object once at bootstrap, since the token does not exist yet at that point and
 * changes across sign-in/sign-out without the app reloading.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.accessToken();
  if (!token) {
    return next(req);
  }
  return next(req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }));
};
