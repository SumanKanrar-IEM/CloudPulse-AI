import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { AccountsService } from './accounts.service';
import { AccountFormComponent } from './account-form.component';

/**
 * The accounts admin surface (FR-010, FR-010a, FR-012).
 *
 * Visible to all three roles -- it is a read surface. Only the state-changing
 * actions within it (register/deactivate/reactivate) are admin-gated, and gated by
 * *disabling* the control rather than hiding it (FR-011a, matching spec 1's
 * role-guard precedent: a control a caller cannot use is still useful context for
 * understanding what the screen can do).
 */
@Component({
  selector: 'cp-accounts-list',
  standalone: true,
  imports: [RouterLink, AccountFormComponent],
  template: `
    <h1>Connected accounts</h1>

    @if (auth.role() === 'admin') {
      <button type="button" (click)="showRegisterForm.set(!showRegisterForm())">
        {{ showRegisterForm() ? 'Cancel' : 'Register an account' }}
      </button>
      @if (showRegisterForm()) {
        <cp-account-form (registered)="showRegisterForm.set(false)" />
      }
    } @else {
      <p>
        Only an admin can register a new account.
        <button type="button" disabled aria-disabled="true">Register an account</button>
      </p>
    }

    @if (accounts.loading()) {
      <p role="status">Loading accounts…</p>
    }

    @if (accounts.error()) {
      <p role="alert">{{ accounts.error() }}</p>
    }

    @if (!accounts.loading() && accounts.accounts().length === 0 && !accounts.error()) {
      <p>No accounts connected yet.</p>
    }

    @if (accounts.accounts().length > 0) {
      <table>
        <caption class="visually-hidden">
          Connected AWS accounts, their mode, regions, and verification status
        </caption>
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col">Mode</th>
            <th scope="col">Regions</th>
            <th scope="col">Status</th>
            <th scope="col">Last scan</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          @for (account of accounts.accounts(); track account.id) {
            <tr>
              <td>{{ account.alias || account.awsAccountId }}</td>
              <td>{{ account.connectionMode }}</td>
              <td>{{ account.scanRegions.join(', ') }}</td>
              <td>{{ account.status }}</td>
              <td>{{ account.lastScan?.status ?? 'never scanned' }}</td>
              <td>
                @if (account.status === 'disabled') {
                  <button
                    type="button"
                    [disabled]="auth.role() !== 'admin'"
                    [attr.aria-disabled]="auth.role() !== 'admin'"
                    (click)="reactivate(account.id)"
                  >
                    Reactivate
                  </button>
                } @else {
                  <button
                    type="button"
                    [disabled]="auth.role() !== 'admin'"
                    [attr.aria-disabled]="auth.role() !== 'admin'"
                    (click)="deactivate(account.id)"
                  >
                    Deactivate
                  </button>
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    }
  `,
  styles: [
    `
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th,
      td {
        text-align: left;
        padding: 0.5rem;
        border-bottom: 1px solid #d0d0d0;
      }
    `,
  ],
})
export class AccountsListComponent implements OnInit {
  protected readonly auth = inject(AuthService);
  protected readonly accounts = inject(AccountsService);
  protected readonly showRegisterForm = signal(false);

  ngOnInit(): void {
    void this.accounts.refresh();
  }

  protected async deactivate(accountId: string): Promise<void> {
    await this.accounts.deactivate(accountId);
  }

  protected async reactivate(accountId: string): Promise<void> {
    await this.accounts.reactivate(accountId);
  }
}
