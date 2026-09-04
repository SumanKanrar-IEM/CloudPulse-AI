import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { IamHygieneFlag, IamHygieneService as IamHygieneApi } from '../../api';

/**
 * Signal-based state for the IAM hygiene view (spec 005, FR-019, FR-020).
 *
 * Read-only by requirement, not by omission: FR-019 fixes these as flag-only
 * recommendations, never an automatic deletion or deactivation, so there is
 * deliberately no method here that acts on a flag.
 */
@Injectable({ providedIn: 'root' })
export class IamHygieneStateService {
  private readonly api = inject(IamHygieneApi);

  private readonly flagsState = signal<IamHygieneFlag[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly includeClearedState = signal(false);

  readonly flags = this.flagsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly includeCleared = this.includeClearedState.asReadonly();

  async refresh(includeCleared = this.includeClearedState()): Promise<void> {
    this.includeClearedState.set(includeCleared);
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      // The generated signature is (accountId, includeCleared) -- passing
      // includeCleared positionally would silently filter by it as an account.
      const result = await firstValueFrom(
        this.api.listIamHygieneFlags(undefined, includeCleared),
      );
      this.flagsState.set(result.flags);
    } catch {
      this.errorState.set('Could not load IAM hygiene flags. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }
}
