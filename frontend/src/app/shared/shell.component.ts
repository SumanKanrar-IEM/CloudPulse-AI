import { Component, inject } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { resolveCognitoConfig } from '../core/api-config';

/**
 * Application shell.
 *
 * Meets the FR-047a accessibility baseline, which every screen added by specs 002-005
 * inherits:
 *
 *  - semantic markup with correct roles and labels (`header`/`nav`/`main`, one `h1`);
 *  - every interactive control reachable and operable by keyboard alone;
 *  - a visible focus indicator on the focused control (set once in styles.scss, so a
 *    component library that suppresses the default outline cannot silently remove it).
 *
 * FR-047b is explicit that automated lint proves only part of this. The skip link and
 * keyboard order below are the half a reviewer has to check by hand.
 *
 * Navigation (FR-003, spec 004): every screen in this platform is all-role read
 * (Accounts FR-010a, SDAs FR-030, and every spec 004 screen's own FR-027) — there is
 * no case today where an entire page must be hidden from a permitted role, only
 * individual write controls, already gated *within* each screen (disabled-not-hidden,
 * tag compliance and ownership's precedent). So the nav list itself is uniform for any
 * role and rendered unconditionally, signed in or not (every link routes through
 * `authGuard`, which redirects an unauthenticated click on its own, FR-002); the only
 * auth-conditional piece is the sign-in/sign-out control itself.
 */
@Component({
  selector: 'cp-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <!-- First focusable element: lets a keyboard user bypass the nav entirely.
         Visually hidden until focused, which is why it must never be display:none. -->
    <a class="skip-link" href="#main-content">Skip to main content</a>

    <header class="shell-header">
      <h1 class="shell-title">CloudPulse AI</h1>
      <!-- Always rendered, authenticated or not: every link here routes through
           authGuard, which redirects an unauthenticated click to sign-in on its
           own (FR-002) -- the nav itself is chrome, not governance data, so there
           is no reason to hide it before a route is even attempted. Kept
           unconditional so the shell's a11y landmarks (shell.spec.ts) hold on
           every visit, signed in or not. -->
      <nav aria-label="Primary">
        <ul class="shell-nav">
          <li><a routerLink="/overview" routerLinkActive="active-link">Overview</a></li>
          <li><a routerLink="/inventory" routerLinkActive="active-link">Inventory</a></li>
          <li><a routerLink="/findings" routerLinkActive="active-link">Findings</a></li>
          <li><a routerLink="/scans" routerLinkActive="active-link">Scan operations</a></li>
          <li><a routerLink="/accounts" routerLinkActive="active-link">Accounts</a></li>
          <li><a routerLink="/sdas" routerLinkActive="active-link">SDAs</a></li>
        </ul>
      </nav>
      @if (auth.isAuthenticated()) {
        <button type="button" class="sign-out" (click)="signOut()">Sign out</button>
      } @else {
        <a routerLink="/sign-in" class="sign-in">Sign in</a>
      }
    </header>

    <main id="main-content" tabindex="-1">
      <router-outlet />
    </main>

    <!-- aria-live so an async error is announced to a screen reader rather than only
         appearing visually. polite, not assertive: it should not interrupt. -->
    <div class="shell-status" role="status" aria-live="polite"></div>
  `,
  styles: [
    `
      .skip-link {
        position: absolute;
        left: -9999px;
        top: 0;
        padding: 0.75rem 1rem;
        background: #fff;
        z-index: 100;
      }
      .skip-link:focus {
        left: 0;
      }
      .shell-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.75rem 2rem;
        padding: 1rem 1.5rem;
        border-bottom: 1px solid #d0d0d0;
      }
      .shell-title {
        font-size: 1.25rem;
        margin: 0;
      }
      .shell-nav {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem 1rem;
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .active-link {
        font-weight: bold;
        text-decoration: underline;
      }
      .sign-out,
      .sign-in {
        margin-left: auto;
      }
      main {
        padding: 1.5rem;
      }
      /* Removing the outline on a programmatically focused main would defeat the
         skip link, so only the ring is suppressed -- never focus visibility itself. */
      main:focus {
        outline: none;
      }
    `,
  ],
})
export class ShellComponent {
  protected readonly auth = inject(AuthService);

  protected signOut(): void {
    const config = resolveCognitoConfig();
    if (!config) {
      return;
    }
    this.auth.signOut(config.domain, config.clientId, window.location.origin);
  }
}
