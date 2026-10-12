import { Component, inject } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { MatRippleModule } from '@angular/material/core';
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
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatRippleModule],
  template: `
    <!-- First focusable element: lets a keyboard user bypass the nav entirely.
         Visually hidden until focused, which is why it must never be display:none. -->
    <a class="skip-link" href="#main-content">Skip to main content</a>

    <div class="layout">
      <header class="sidebar">
        <h1 class="brand">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path class="pulse" d="M2 12h4l2.5-6 4 12 3-9 2 3H22" />
            </svg>
          </span>
          <span>CloudPulse <span class="brand-ai">AI</span></span>
        </h1>

        <!-- Always rendered, authenticated or not: every link here routes through
             authGuard, which redirects an unauthenticated click to sign-in on its
             own (FR-002) -- the nav itself is chrome, not governance data, so there
             is no reason to hide it before a route is even attempted. Kept
             unconditional so the shell's a11y landmarks (shell.spec.ts) hold on
             every visit, signed in or not. -->
        <nav aria-label="Primary">
          @for (group of navGroups; track group.label) {
            <p class="nav-group" [id]="group.id">{{ group.label }}</p>
            <ul class="shell-nav" [attr.aria-labelledby]="group.id">
              @for (item of group.items; track item.path) {
                <li>
                  <a matRipple [routerLink]="item.path" routerLinkActive="active-link">
                    <span class="material-symbols-rounded" aria-hidden="true">{{ item.icon }}</span>
                    {{ item.label }}
                  </a>
                </li>
              }
            </ul>
          }
        </nav>

        <div class="sidebar-footer">
          @if (auth.user(); as user) {
            <div class="user-card">
              <span class="avatar" aria-hidden="true">{{ user.email.charAt(0).toUpperCase() }}</span>
              <span class="user-meta">
                <span class="user-email">{{ user.email }}</span>
                <span class="user-role">{{ user.role }}</span>
              </span>
            </div>
          }
          @if (auth.isAuthenticated()) {
            <button type="button" class="sign-out" (click)="signOut()">
              <span class="material-symbols-rounded" aria-hidden="true">logout</span>
              Sign out
            </button>
          } @else {
            <a routerLink="/sign-in" class="sign-in">
              <span class="material-symbols-rounded" aria-hidden="true">login</span>
              Sign in
            </a>
          }
        </div>
      </header>

      <main id="main-content" tabindex="-1">
        <router-outlet />
      </main>
    </div>

    <!-- aria-live so an async error is announced to a screen reader rather than only
         appearing visually. polite, not assertive: it should not interrupt. -->
    <div class="shell-status" role="status" aria-live="polite"></div>
  `,
  styles: [
    `
      .skip-link {
        position: absolute;
        left: -9999px;
        top: 0.5rem;
        padding: 0.75rem 1rem;
        background: #fff;
        color: #3730a3;
        font-weight: 600;
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(16, 24, 40, 0.18);
        z-index: 100;
      }
      .skip-link:focus {
        left: 0.5rem;
      }
      .layout {
        display: grid;
        grid-template-columns: 16.5rem 1fr;
        min-height: 100vh;
      }
      .sidebar {
        position: sticky;
        top: 0;
        height: 100vh;
        display: flex;
        flex-direction: column;
        gap: 1rem;
        padding: 1.25rem 0.85rem;
        color: #c7d0e0;
        background:
          radial-gradient(20rem 14rem at 0% 0%, rgba(124, 58, 237, 0.28), transparent 70%),
          radial-gradient(18rem 14rem at 100% 100%, rgba(14, 165, 233, 0.18), transparent 70%),
          #0b1020;
        overflow-y: auto;
      }
      .brand {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        margin: 0 0.5rem 0.5rem;
        font-size: 1.15rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        color: #ffffff;
      }
      .brand-ai {
        color: #c4b5fd;
      }
      .brand-mark {
        display: grid;
        place-items: center;
        width: 2.25rem;
        height: 2.25rem;
        border-radius: 11px;
        background: linear-gradient(135deg, #4f46e5, #7c3aed 55%, #0ea5e9);
        background-size: 200% 200%;
        box-shadow: 0 6px 18px rgba(124, 58, 237, 0.45);
        animation: brand-glow 6s ease-in-out infinite;
      }
      .pulse {
        fill: none;
        stroke: #ffffff;
        stroke-width: 2.2;
        stroke-linecap: round;
        stroke-linejoin: round;
        stroke-dasharray: 48;
        animation: pulse-draw 2.8s ease-in-out infinite;
      }
      .nav-group {
        margin: 0.75rem 0.75rem 0.35rem;
        font-size: 0.68rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #8b96ad;
      }
      .shell-nav {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 0.15rem;
      }
      .shell-nav a {
        position: relative;
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.55rem 0.75rem;
        border-radius: 10px;
        color: #c7d0e0;
        font-weight: 500;
        font-size: 0.9rem;
        text-decoration: none;
        overflow: hidden;
        transition:
          background-color 0.2s ease,
          color 0.2s ease,
          transform 0.2s ease;
      }
      .shell-nav a:hover {
        background: rgba(255, 255, 255, 0.06);
        color: #ffffff;
        transform: translateX(2px);
      }
      .shell-nav a.active-link {
        background: linear-gradient(90deg, rgba(124, 58, 237, 0.35), rgba(79, 70, 229, 0.12));
        color: #ffffff;
        font-weight: 600;
      }
      .shell-nav a.active-link::before {
        content: '';
        position: absolute;
        left: 0;
        top: 20%;
        bottom: 20%;
        width: 3px;
        border-radius: 3px;
        background: linear-gradient(#a78bfa, #38bdf8);
      }
      .shell-nav a.active-link .material-symbols-rounded {
        color: #c4b5fd;
      }
      .sidebar-footer {
        margin-top: auto;
        display: grid;
        gap: 0.6rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
      }
      .user-card {
        display: flex;
        align-items: center;
        gap: 0.65rem;
        padding: 0 0.5rem;
        min-width: 0;
      }
      .avatar {
        flex: none;
        display: grid;
        place-items: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 50%;
        font-weight: 700;
        color: #ffffff;
        background: linear-gradient(135deg, #7c3aed, #0ea5e9);
      }
      .user-meta {
        display: grid;
        min-width: 0;
      }
      .user-email {
        color: #ffffff;
        font-size: 0.82rem;
        font-weight: 600;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .user-role {
        color: #8b96ad;
        font-size: 0.75rem;
        text-transform: capitalize;
      }
      .sign-out,
      .sign-in {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.55rem 0.75rem;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.14);
        background: rgba(255, 255, 255, 0.04);
        color: #e2e8f0;
        font-weight: 600;
        text-decoration: none;
      }
      .sign-out:hover:not(:disabled),
      .sign-in:hover {
        background: rgba(255, 255, 255, 0.1);
        border-color: rgba(255, 255, 255, 0.28);
        box-shadow: none;
      }
      main {
        padding: 2rem clamp(1rem, 3vw, 2.75rem) 3rem;
        min-width: 0;
        max-width: 90rem;
      }
      /* Removing the outline on a programmatically focused main would defeat the
         skip link, so only the ring is suppressed -- never focus visibility itself. */
      main:focus {
        outline: none;
      }
      @keyframes brand-glow {
        0%,
        100% {
          background-position: 0% 50%;
        }
        50% {
          background-position: 100% 50%;
        }
      }
      @keyframes pulse-draw {
        0% {
          stroke-dashoffset: 48;
        }
        45%,
        70% {
          stroke-dashoffset: 0;
        }
        100% {
          stroke-dashoffset: -48;
        }
      }
      /* Narrow screens: the sidebar becomes a top bar with a scrolling nav. */
      @media (max-width: 900px) {
        .layout {
          grid-template-columns: 1fr;
          grid-template-rows: auto 1fr;
        }
        .sidebar {
          position: static;
          height: auto;
          flex-direction: row;
          flex-wrap: wrap;
          align-items: center;
          padding: 0.75rem 1rem;
        }
        .brand {
          margin: 0;
        }
        nav {
          order: 3;
          flex-basis: 100%;
          display: flex;
          gap: 0.25rem;
          overflow-x: auto;
        }
        .nav-group {
          display: none;
        }
        .shell-nav {
          display: flex;
        }
        .shell-nav a {
          white-space: nowrap;
        }
        .sidebar-footer {
          margin: 0 0 0 auto;
          padding: 0;
          border: 0;
          display: flex;
        }
        .user-card {
          display: none;
        }
      }
    `,
  ],
})
export class ShellComponent {
  protected readonly auth = inject(AuthService);

  // FR-003: one uniform list for every role (see the class comment). Grouped only so
  // twelve links scan quickly; the groups carry no permission meaning.
  protected readonly navGroups = [
    {
      id: 'nav-governance',
      label: 'Governance',
      items: [
        { path: '/overview', label: 'Overview', icon: 'space_dashboard' },
        { path: '/inventory', label: 'Inventory', icon: 'inventory_2' },
        { path: '/findings', label: 'Findings', icon: 'flag' },
        { path: '/scans', label: 'Scan operations', icon: 'radar' },
      ],
    },
    {
      id: 'nav-insights',
      label: 'Cost & insights',
      items: [
        { path: '/cost', label: 'Cost', icon: 'payments' },
        { path: '/utilization', label: 'Utilization', icon: 'speed' },
        { path: '/forecasts', label: 'Forecasts', icon: 'trending_up' },
        { path: '/rightsizing', label: 'Rightsizing', icon: 'tune' },
        { path: '/iam-hygiene', label: 'IAM hygiene', icon: 'admin_panel_settings' },
        { path: '/coverage-proposals', label: 'Coverage proposals', icon: 'shield' },
      ],
    },
    {
      id: 'nav-setup',
      label: 'Setup',
      items: [
        { path: '/accounts', label: 'Accounts', icon: 'cloud' },
        { path: '/sdas', label: 'SDAs', icon: 'workspaces' },
      ],
    },
  ];

  protected signOut(): void {
    const config = resolveCognitoConfig();
    if (!config) {
      return;
    }
    this.auth.signOut(config.domain, config.clientId, window.location.origin);
  }
}
