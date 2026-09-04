import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  InventoryResourceSummary,
  ResourcesService,
  UtilizationReport,
  UtilizationService as UtilizationApi,
} from '../../api';

/**
 * Signal-based state for the utilization view (spec 005, FR-018).
 *
 * The report carries all three levels in one response, so account and project
 * figures need no request per expansion -- which is what keeps FR-018's
 * account -> project -> resource drill-down inside three navigation steps.
 */
@Injectable({ providedIn: 'root' })
export class UtilizationStateService {
  private readonly api = inject(UtilizationApi);
  private readonly resourcesApi = inject(ResourcesService);

  private readonly reportState = signal<UtilizationReport | null>(null);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly drillDownState = signal<{ id: string | null; name: string | null } | null>(null);
  private readonly resourcesState = signal<InventoryResourceSummary[]>([]);
  private readonly resourcesLoadingState = signal(false);

  readonly report = this.reportState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly drillDown = this.drillDownState.asReadonly();
  readonly resources = this.resourcesState.asReadonly();
  readonly resourcesLoading = this.resourcesLoadingState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      this.reportState.set(await firstValueFrom(this.api.getUtilization()));
    } catch {
      this.errorState.set('Could not load utilization. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  /** Step three of FR-018's drill-down: the resources behind a project's figure. */
  async openProject(sdaId: string | null, sdaName: string | null): Promise<void> {
    this.drillDownState.set({ id: sdaId, name: sdaName });
    this.resourcesLoadingState.set(true);
    try {
      const response = await firstValueFrom(
        this.resourcesApi.listResources(undefined, undefined, undefined, sdaId ?? 'none'),
      );
      this.resourcesState.set(response.resources);
    } catch {
      this.resourcesState.set([]);
    } finally {
      this.resourcesLoadingState.set(false);
    }
  }

  closeDrillDown(): void {
    this.drillDownState.set(null);
    this.resourcesState.set([]);
  }
}
