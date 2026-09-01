import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { InventoryResourceSummary, ResourceDetail, ResourcesService } from '../../api';

export interface InventoryFilters {
  accountId?: string;
  service?: string;
  region?: string;
  sdaId?: string;
  tagStatus?: string;
  ownerStatus?: string;
}

const PAGE_SIZE = 50;

/**
 * Signal-based state wrapper around the generated `ResourcesService`
 * (spec 004, FR-010-FR-013). Server-side paged and filtered (FR-011) --
 * this never fetches the full inventory into the browser.
 */
@Injectable({ providedIn: 'root' })
export class InventoryService {
  private readonly api = inject(ResourcesService);

  private readonly resourcesState = signal<InventoryResourceSummary[]>([]);
  private readonly pageState = signal(1);
  private readonly totalCountState = signal(0);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);
  private readonly detailState = signal<ResourceDetail | null>(null);
  private readonly detailLoadingState = signal(false);

  readonly resources = this.resourcesState.asReadonly();
  readonly page = this.pageState.asReadonly();
  readonly totalCount = this.totalCountState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();
  readonly detail = this.detailState.asReadonly();
  readonly detailLoading = this.detailLoadingState.asReadonly();

  readonly pageSize = PAGE_SIZE;

  async load(filters: InventoryFilters, page = 1): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const result = await firstValueFrom(
        this.api.listResources(
          filters.accountId,
          filters.service,
          filters.region,
          filters.sdaId,
          filters.tagStatus,
          filters.ownerStatus,
          page,
          PAGE_SIZE,
        ),
      );
      this.resourcesState.set(result.resources);
      this.pageState.set(result.page);
      this.totalCountState.set(result.totalCount);
    } catch {
      this.errorState.set('Could not load the inventory. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  async loadDetail(resourceId: string): Promise<void> {
    this.detailLoadingState.set(true);
    this.detailState.set(null);
    try {
      this.detailState.set(await firstValueFrom(this.api.getResourceDetail(resourceId)));
    } finally {
      this.detailLoadingState.set(false);
    }
  }

  clearDetail(): void {
    this.detailState.set(null);
  }
}
