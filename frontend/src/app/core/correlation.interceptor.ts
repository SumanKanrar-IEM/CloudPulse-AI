import { HttpInterceptorFn } from '@angular/common/http';

/**
 * Surfaces the correlation id the API returns (FR-044, SC-010).
 *
 * The client deliberately does **not** generate or send one. The server validates any
 * inbound `X-Correlation-Id` against a strict UUID pattern and discards anything else,
 * so sending a browser-generated value would at best be ignored. Reading the response
 * header is what actually helps: it gives the user something to quote when reporting a
 * problem, and it is the same id in the structured logs.
 */
export const correlationInterceptor: HttpInterceptorFn = (req, next) => {
  return next(req);
};

/** Extract the id from a response, for display alongside an error message. */
export function correlationIdOf(headers: { get(name: string): string | null }): string | null {
  return headers.get('X-Correlation-Id');
}
