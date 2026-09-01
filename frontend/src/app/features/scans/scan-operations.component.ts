import { Component, OnInit, inject, signal } from '@angular/core';
import { AuthService } from '../../core/auth.service';
import { Scan } from '../../api';
import { AccountsService } from '../accounts/accounts.service';
import { ScansService } from './scans.service';

/**
 * Scan history and on-demand trigger per connected account (spec 004, S31,
 * FR-021-FR-023).
 */
@Component({
  selector: 'cp-scan-operations',
  standalone: true,
  imports: [],
  template: `
    <h1>Scan operations</h1>

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
      <ul class="accounts-list">
        @for (account of accounts.accounts(); track account.id) {
          <li>
            <div class="account-row">
              <span>{{ account.alias || account.awsAccountId }}</span>
              @if (scans.polling().has(account.id)) {
                <span role="status">Scanning…</span>
              } @else if (canTrigger()) {
                <button type="button" (click)="trigger(account.id)">Scan now</button>
              }
              <button type="button" (click)="toggleHistory(account.id)">
                {{ expandedAccountId() === account.id ? 'Hide history' : 'Show history' }}
              </button>
            </div>

            @if (expandedAccountId() === account.id) {
              <div class="history-panel">
                @if (scans.loading()[account.id]) {
                  <p role="status">Loading scan history…</p>
                }
                @if (scans.error()[account.id]) {
                  <p role="alert">{{ scans.error()[account.id] }}</p>
                }
                @if (historyFor(account.id).length === 0 && !scans.loading()[account.id]) {
                  <p>No scans yet.</p>
                }
                @if (historyFor(account.id).length > 0) {
                  <table>
                    <caption class="visually-hidden">
                      Scan history for {{ account.alias || account.awsAccountId }}: start time,
                      duration, status, and resource deltas
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Started</th>
                        <th scope="col">Duration</th>
                        <th scope="col">Status</th>
                        <th scope="col">Added</th>
                        <th scope="col">Removed</th>
                        <th scope="col">Changed</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (scan of historyFor(account.id); track scan.id) {
                        <tr>
                          <td>{{ scan.startedAt }}</td>
                          <td>{{ duration(scan) }}</td>
                          <td>{{ scan.status }}</td>
                          <td>{{ scan.added ?? '—' }}</td>
                          <td>{{ scan.removed ?? '—' }}</td>
                          <td>{{ scan.changed ?? '—' }}</td>
                        </tr>
                      }
                    </tbody>
                  </table>
                }
              </div>
            }
          </li>
        }
      </ul>
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
      .accounts-list {
        list-style: none;
        padding: 0;
      }
      .account-row {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 0.5rem 0;
        border-bottom: 1px solid #d0d0d0;
      }
      .history-panel {
        padding: 0.5rem 1rem 1rem;
        background: #f7f7f7;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th,
      td {
        text-align: left;
        padding: 0.5rem;
      }
    `,
  ],
})
export class ScanOperationsComponent implements OnInit {
  protected readonly accounts = inject(AccountsService);
  protected readonly scans = inject(ScansService);
  private readonly auth = inject(AuthService);

  protected readonly expandedAccountId = signal<string | null>(null);

  ngOnInit(): void {
    void this.accounts.refresh();
  }

  protected canTrigger(): boolean {
    const role = this.auth.role();
    return role === 'admin' || role === 'operator';
  }

  protected historyFor(accountId: string): Scan[] {
    return this.scans.history()[accountId] ?? [];
  }

  protected toggleHistory(accountId: string): void {
    if (this.expandedAccountId() === accountId) {
      this.expandedAccountId.set(null);
      return;
    }
    this.expandedAccountId.set(accountId);
    void this.scans.loadHistory(accountId);
  }

  protected async trigger(accountId: string): Promise<void> {
    await this.scans.triggerScan(accountId);
  }

  protected duration(scan: Scan): string {
    if (!scan.finishedAt) {
      return 'Running…';
    }
    const seconds = Math.round(
      (new Date(scan.finishedAt).getTime() - new Date(scan.startedAt).getTime()) / 1000,
    );
    return `${seconds}s`;
  }
}
