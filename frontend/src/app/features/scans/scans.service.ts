import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AccountsService as GeneratedAccountsService, Scan } from '../../api';

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 30;
const FINAL_STATUSES = new Set(['succeeded', 'partial', 'failed']);

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Signal-based state wrapper around the generated `AccountsService`'s
 * `listScanHistory`/`triggerScan` (spec 004, S31, FR-021-FR-023, research.md
 * R-405).
 *
 * Triggering a scan polls scan history until the new scan reaches a final
 * state (Acceptance Scenario US5.2, FR-022) -- no manual reload needed.
 */
@Injectable({ providedIn: 'root' })
export class ScansService {
  private readonly api = inject(GeneratedAccountsService);

  private readonly historyState = signal<Record<string, Scan[]>>({});
  private readonly loadingState = signal<Record<string, boolean>>({});
  private readonly pollingState = signal<Set<string>>(new Set());
  private readonly errorState = signal<Record<string, string>>({});

  readonly history = this.historyState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly polling = this.pollingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async loadHistory(accountId: string): Promise<void> {
    this.loadingState.update((s) => ({ ...s, [accountId]: true }));
    this.errorState.update((s) => {
      const rest = { ...s };
      delete rest[accountId];
      return rest;
    });
    try {
      const result = await firstValueFrom(this.api.listScanHistory(accountId));
      this.historyState.update((h) => ({ ...h, [accountId]: result.scans }));
    } catch {
      this.errorState.update((s) => ({ ...s, [accountId]: 'Could not load scan history.' }));
    } finally {
      this.loadingState.update((s) => ({ ...s, [accountId]: false }));
    }
  }

  async triggerScan(accountId: string): Promise<void> {
    const scan = await firstValueFrom(this.api.triggerScan(accountId));
    this.pollingState.update((s) => new Set(s).add(accountId));
    try {
      await this.pollUntilFinal(accountId, scan.id);
    } finally {
      this.pollingState.update((s) => {
        const next = new Set(s);
        next.delete(accountId);
        return next;
      });
    }
  }

  private async pollUntilFinal(accountId: string, scanId: string): Promise<void> {
    for (let i = 0; i < MAX_POLLS; i++) {
      await this.loadHistory(accountId);
      const scan = this.historyState()[accountId]?.find((s) => s.id === scanId);
      if (scan && FINAL_STATUSES.has(scan.status)) {
        return;
      }
      await delay(POLL_INTERVAL_MS);
    }
  }
}
