import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  BudgetOverrun,
  BudgetOverrunsService,
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
  private readonly overrunsApi = inject(BudgetOverrunsService);

  private readonly findingsState = signal<Finding[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly suggestionsState = signal<Record<string, RemediationSuggestion>>({});
  private readonly suggestionErrorsState = signal<Record<string, string>>({});
  private readonly overrunsState = signal<BudgetOverrun[]>([]);

  readonly findings = this.findingsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly suggestions = this.suggestionsState.asReadonly();
  readonly suggestionErrors = this.suggestionErrorsState.asReadonly();
  /**
   * spec 005, FR-016. Budget overruns are the same `Finding` rows, moving
   * through the same lifecycle, but they attach to a project rather than a
   * resource -- a shape `GET /findings`'s response cannot carry -- so they are
   * read from their own endpoint and merged into this one workbench.
   */
  readonly overruns = this.overrunsState.asReadonly();

  async load(filters: FindingsFilters): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const [result, overruns] = await Promise.all([
        firstValueFrom(this.api.listFindings(filters.accountId, filters.resourceId, filters.status)),
        firstValueFrom(this.overrunsApi.listBudgetOverruns(filters.status)),
      ]);
      this.findingsState.set(result.findings);
      // Account and resource filters are meaningless for a project-level
      // finding, so an overrun is hidden whenever either is applied rather than
      // shown as though it had matched them.
      this.overrunsState.set(
        filters.accountId || filters.resourceId ? [] : overruns.overruns,
      );
    } catch {
      this.errorState.set('Could not load findings. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  async loadSuggestion(findingId: string): Promise<void> {
    this.suggestionErrorsState.update((existing) => {
      const rest = { ...existing };
      delete rest[findingId];
      return rest;
    });
    try {
      const suggestion = await firstValueFrom(this.api.getFindingSuggestion(findingId));
      this.suggestionsState.update((existing) => ({ ...existing, [findingId]: suggestion }));
    } catch {
      this.suggestionErrorsState.update((existing) => ({
        ...existing,
        [findingId]: 'Could not load this suggestion. Try again.',
      }));
    }
  }

  /** FR-015-FR-017, FR-020: idempotent, never changes `status`. */
  async acknowledge(findingId: string): Promise<void> {
    const ack = await firstValueFrom(this.api.acknowledgeFinding(findingId));
    this.findingsState.update((findings) =>
      findings.map((f) =>
        f.id === findingId
          ? { ...f, acknowledgedAt: ack.acknowledgedAt, escalatedAt: null }
          : f,
      ),
    );
    // Overruns are the same endpoint's rows and the same acknowledge call, so
    // they need the same local update -- without it, acknowledging one would
    // succeed on the server and leave the badge unchanged until a reload.
    // `escalatedAt` is cleared alongside because FR-009 stops displaying a
    // finding as escalated once it is acknowledged, which is what the next
    // server read would return anyway.
    this.overrunsState.update((overruns) =>
      overruns.map((o) =>
        o.id === findingId
          ? { ...o, acknowledgedAt: ack.acknowledgedAt, escalatedAt: null }
          : o,
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
