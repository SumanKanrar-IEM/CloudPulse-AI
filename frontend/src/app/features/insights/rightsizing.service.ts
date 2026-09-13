import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { RightsizingRecommendationResponse, RightsizingService as RightsizingApi } from '../../api';

/**
 * Signal-based state for the rightsizing view (spec 006, FR-023, FR-002).
 *
 * Read-only by requirement, not by omission. FR-002: nothing in this platform
 * applies a recommendation, so there is no method here that could -- the same
 * shape `IamHygieneStateService` has for the same reason.
 */
@Injectable({ providedIn: 'root' })
export class RightsizingStateService {
  private readonly api = inject(RightsizingApi);

  private readonly recommendationsState = signal<RightsizingRecommendationResponse[]>([]);
  private readonly pricingNoteState = signal('');
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly recommendations = this.recommendationsState.asReadonly();
  readonly pricingNote = this.pricingNoteState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const result = await firstValueFrom(this.api.listRightsizingRecommendations());
      this.recommendationsState.set(result.recommendations);
      this.pricingNoteState.set(result.pricingNote);
    } catch {
      this.errorState.set('Could not load rightsizing recommendations. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }
}
