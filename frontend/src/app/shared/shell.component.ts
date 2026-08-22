import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';

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
 */
@Component({
  selector: 'cp-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink],
  template: `
    <!-- First focusable element: lets a keyboard user bypass the nav entirely.
         Visually hidden until focused, which is why it must never be display:none. -->
    <a class="skip-link" href="#main-content">Skip to main content</a>

    <header class="shell-header">
      <h1 class="shell-title">CloudPulse AI</h1>
      <nav aria-label="Primary">
        <ul class="shell-nav">
          <!-- Feature routes are added here by specs 002-005. -->
          <li><a routerLink="/" aria-current="page">Overview</a></li>
        </ul>
      </nav>
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
        align-items: center;
        gap: 2rem;
        padding: 1rem 1.5rem;
        border-bottom: 1px solid #d0d0d0;
      }
      .shell-title {
        font-size: 1.25rem;
        margin: 0;
      }
      .shell-nav {
        display: flex;
        gap: 1rem;
        list-style: none;
        margin: 0;
        padding: 0;
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
export class ShellComponent {}
