import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AdvisoryGapResponse,
  CoverageProposalResponse,
  CoverageProposalsService as CoverageProposalsApi,
} from '../../api';

/**
 * Signal-based state for the coverage advisor view (spec 006, FR-015a, FR-016,
 * FR-018).
 *
 * Two lists, and no method that acts on the advisory one. There is no client
 * for such a call because the API exposes no route for it: FR-015a's rule is
 * that a gap needing a code change is never offered for acceptance, and the
 * absence here mirrors the absence there rather than restating it as a check
 * someone could later delete.
 */
@Injectable({ providedIn: 'root' })
export class CoverageProposalsStateService {
  private readonly api = inject(CoverageProposalsApi);

  private readonly proposalsState = signal<CoverageProposalResponse[]>([]);
  private readonly gapsState = signal<AdvisoryGapResponse[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly decidingState = signal<string | null>(null);

  readonly proposals = this.proposalsState.asReadonly();
  readonly gaps = this.gapsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly deciding = this.decidingState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const [proposals, gaps] = await Promise.all([
        firstValueFrom(this.api.listCoverageProposals()),
        firstValueFrom(this.api.listCoverageAdvisoryGaps()),
      ]);
      this.proposalsState.set(proposals.proposals);
      this.gapsState.set(gaps.gaps);
    } catch {
      this.errorState.set('Could not load coverage proposals. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  /**
   * Accept or reject one proposal, then reload.
   *
   * Reloads rather than patching the row in place. The server decides what the
   * decision did — `appliedAt` in particular — and a locally-constructed row
   * would show an admin what the frontend assumed rather than what happened.
   */
  async decide(proposalId: string, accept: boolean): Promise<void> {
    this.decidingState.set(proposalId);
    this.errorState.set(null);
    try {
      await firstValueFrom(this.api.decideCoverageProposal(proposalId, { accept }));
      await this.refresh();
    } catch {
      this.errorState.set('Could not record that decision. Try again.');
    } finally {
      this.decidingState.set(null);
    }
  }
}
