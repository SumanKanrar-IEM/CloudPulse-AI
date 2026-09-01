import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  Account,
  AccountsService,
  ComplianceScore,
  ComplianceService,
  Finding,
  FindingStatus,
  FindingsService,
} from '../../api';

export interface AccountOverview {
  account: Account;
  /** Null means "not yet scanned" (FR-009) -- distinct from a real zero score. */
  score: ComplianceScore | null;
  openFindingCount: number;
}

/**
 * Signal-based state wrapper around the generated Accounts/Compliance/Findings
 * services (spec 004, FR-006-FR-009). Every score and count comes straight from
 * an API response -- the "overall" score is a sum of the same per-account
 * `compliantCount`/`totalCount` values the API already returned, not a separately
 * invented formula, so it still matches a hand count exactly (SC-004).
 */
@Injectable({ providedIn: 'root' })
export class OverviewService {
  private readonly accountsApi = inject(AccountsService);
  private readonly complianceApi = inject(ComplianceService);
  private readonly findingsApi = inject(FindingsService);

  private readonly accountOverviewsState = signal<AccountOverview[]>([]);
  private readonly findingsState = signal<Finding[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly accountOverviews = this.accountOverviewsState.asReadonly();
  readonly findings = this.findingsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const { accounts } = await firstValueFrom(this.accountsApi.listAccounts());

      const overviews = await Promise.all(
        accounts.map(async (account): Promise<AccountOverview> => {
          if (!account.lastScan) {
            return { account, score: null, openFindingCount: 0 };
          }
          const [score, { findings }] = await Promise.all([
            firstValueFrom(this.complianceApi.getAccountComplianceScore(account.id)),
            firstValueFrom(this.findingsApi.listFindings(account.id, undefined, FindingStatus.Open)),
          ]);
          return { account, score, openFindingCount: findings.length };
        }),
      );
      this.accountOverviewsState.set(overviews);

      // No accounts at all -- nothing to fetch, and fetching anyway means one
      // more request that can fail for no reason and mask the empty state
      // behind an error instead.
      if (accounts.length === 0) {
        this.findingsState.set([]);
      } else {
        const { findings } = await firstValueFrom(
          this.findingsApi.listFindings(undefined, undefined, FindingStatus.Open),
        );
        this.findingsState.set(findings);
      }
    } catch {
      this.errorState.set('Could not load the compliance overview. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }
}
