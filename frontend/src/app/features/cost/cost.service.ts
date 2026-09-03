import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  Budget,
  BudgetsService,
  InventoryResourceSummary,
  SpendService,
  SpendSummary,
  ResourcesService,
} from '../../api';

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Default window: the trailing 30 days, ending today (S39, S42). */
export function defaultSpendRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - 29);
  return { from: isoDate(from), to: isoDate(to) };
}

/**
 * Signal-based state wrapper around the generated Spend/Resources services
 * (spec 005, FR-001-FR-003). Drill-down bottoms out at the SDA/service level
 * per research.md R-512 -- Cost Explorer has no per-resource dollar figure,
 * so "drill down" here means "list the resources that make up this line",
 * not a per-resource price.
 */
@Injectable({ providedIn: 'root' })
export class CostService {
  private readonly spendApi = inject(SpendService);
  private readonly resourcesApi = inject(ResourcesService);
  private readonly budgetsApi = inject(BudgetsService);

  private readonly summaryState = signal<SpendSummary | null>(null);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  private readonly drillDownSdaState = signal<{ id: string | null; name: string | null } | null>(
    null,
  );
  private readonly drillDownResourcesState = signal<InventoryResourceSummary[]>([]);
  private readonly drillDownLoadingState = signal(false);
  private readonly budgetsState = signal<Budget[]>([]);

  readonly summary = this.summaryState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly drillDownSda = this.drillDownSdaState.asReadonly();
  readonly drillDownResources = this.drillDownResourcesState.asReadonly();
  readonly drillDownLoading = this.drillDownLoadingState.asReadonly();
  readonly budgets = this.budgetsState.asReadonly();

  async refresh(from: string, to: string): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      // Budgets are fetched alongside spend, not lazily on expand: FR-015 makes
      // the 80% threshold dashboard-only precisely because it sends no
      // notification, so it has to be on screen with the spend it warns about.
      const [summary, budgets] = await Promise.all([
        firstValueFrom(this.spendApi.getSpendSummary(from, to)),
        firstValueFrom(this.budgetsApi.listBudgets()),
      ]);
      this.summaryState.set(summary);
      this.budgetsState.set(budgets.budgets);
    } catch {
      this.errorState.set('Could not load spend. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  /** FR-003, R-512: which resources make up this project's spend line. */
  async drillDown(sdaId: string | null, sdaName: string | null): Promise<void> {
    this.drillDownSdaState.set({ id: sdaId, name: sdaName });
    this.drillDownLoadingState.set(true);
    try {
      const { resources } = await firstValueFrom(
        this.resourcesApi.listResources(undefined, undefined, undefined, sdaId ?? 'none'),
      );
      this.drillDownResourcesState.set(resources);
    } finally {
      this.drillDownLoadingState.set(false);
    }
  }

  closeDrillDown(): void {
    this.drillDownSdaState.set(null);
    this.drillDownResourcesState.set([]);
  }
}
