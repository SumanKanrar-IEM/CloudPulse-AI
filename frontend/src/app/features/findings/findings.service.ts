import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  Finding,
  FindingsService as FindingsApi,
  FindingStatus,
  RemediationSuggestion,
} from '../../api';

export interface FindingsFilters {
  accountId?: string;
  resourceId?: string;
  status?: FindingStatus;
}

/**
 * Signal-based state wrapper around the generated `FindingsService`
 * (spec 004, FR-014-FR-020a).
 */
@Injectable({ providedIn: 'root' })
export class FindingsService {
  private readonly api = inject(FindingsApi);

  private readonly findingsState = signal<Finding[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly suggestionsState = signal<Record<string, RemediationSuggestion>>({});

  readonly findings = this.findingsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly suggestions = this.suggestionsState.asReadonly();

  async load(filters: FindingsFilters): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const result = await firstValueFrom(
        this.api.listFindings(filters.accountId, filters.resourceId, filters.status),
      );
      this.findingsState.set(result.findings);
    } catch {
      this.errorState.set('Could not load findings. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  async loadSuggestion(findingId: string): Promise<void> {
    const suggestion = await firstValueFrom(this.api.getFindingSuggestion(findingId));
    this.suggestionsState.update((existing) => ({ ...existing, [findingId]: suggestion }));
  }

  /** FR-015-FR-017, FR-020: idempotent, never changes `status`. */
  async acknowledge(findingId: string): Promise<void> {
    const ack = await firstValueFrom(this.api.acknowledgeFinding(findingId));
    this.findingsState.update((findings) =>
      findings.map((f) =>
        f.id === findingId ? { ...f, acknowledgedAt: ack.acknowledgedAt } : f,
      ),
    );
  }

  /** FR-020a, admin-only: always displays exactly as a real suggestion would. */
  async seedSuggestion(
    findingId: string,
    suggestionText: string,
    blastRadiusNote: string,
  ): Promise<void> {
    const suggestion = await firstValueFrom(
      this.api.setFindingSuggestionSeed(findingId, { suggestionText, blastRadiusNote }),
    );
    this.suggestionsState.update((existing) => ({ ...existing, [findingId]: suggestion }));
  }
}
