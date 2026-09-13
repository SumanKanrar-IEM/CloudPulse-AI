import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ForecastsService as ForecastsApi, ProjectForecasts } from '../../api';

/** Signal-based state for the forecasts view (spec 006, FR-021, FR-021a, FR-022). */
@Injectable({ providedIn: 'root' })
export class ForecastsStateService {
  private readonly api = inject(ForecastsApi);

  private readonly projectsState = signal<ProjectForecasts[]>([]);
  private readonly generatedAtState = signal<string | null>(null);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly projects = this.projectsState.asReadonly();
  readonly generatedAt = this.generatedAtState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const result = await firstValueFrom(this.api.listForecasts());
      this.projectsState.set(result.projects);
      this.generatedAtState.set(result.generatedAt);
    } catch {
      this.errorState.set('Could not load forecasts. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }
}
