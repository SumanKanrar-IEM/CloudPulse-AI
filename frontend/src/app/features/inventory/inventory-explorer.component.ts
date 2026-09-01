import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { InventoryFilters, InventoryService } from './inventory.service';
import { ResourceDetailComponent } from './resource-detail.component';

/**
 * Server-side paged/filtered inventory table (FR-010, FR-011).
 */
@Component({
  selector: 'cp-inventory-explorer',
  standalone: true,
  imports: [FormsModule, ResourceDetailComponent],
  template: `
    <h1>Inventory</h1>

    <form (ngSubmit)="applyFilters()" aria-label="Inventory filters">
      <label>
        Account ID
        <input type="text" [(ngModel)]="filters.accountId" name="accountId" />
      </label>
      <label>
        Service
        <input type="text" [(ngModel)]="filters.service" name="service" />
      </label>
      <label>
        Region
        <input type="text" [(ngModel)]="filters.region" name="region" />
      </label>
      <label>
        SDA ID (or "none" for the No SDA bucket)
        <input type="text" [(ngModel)]="filters.sdaId" name="sdaId" />
      </label>
      <label>
        Tag status ("compliant" or "missing:&lt;ruleKey&gt;")
        <input type="text" [(ngModel)]="filters.tagStatus" name="tagStatus" />
      </label>
      <label>
        <input
          type="checkbox"
          [ngModel]="filters.ownerStatus === 'unattributed'"
          (ngModelChange)="setUnattributedOnly($event)"
          name="unattributedOnly"
        />
        Missing owner attribution only
      </label>
      <button type="submit">Apply filters</button>
    </form>

    @if (inventory.loading()) {
      <p role="status">Loading inventory…</p>
    }

    @if (inventory.error()) {
      <p role="alert">{{ inventory.error() }}</p>
    }

    @if (!inventory.loading() && !inventory.error()) {
      @if (inventory.resources().length === 0) {
        <p>No matching resources.</p>
      } @else {
        <table>
          <caption class="visually-hidden">
            Resource inventory: ARN, service, region, tag status, and owner status
          </caption>
          <thead>
            <tr>
              <th scope="col">ARN</th>
              <th scope="col">Service</th>
              <th scope="col">Region</th>
              <th scope="col">Tag status</th>
              <th scope="col">Owner status</th>
            </tr>
          </thead>
          <tbody>
            @for (resource of inventory.resources(); track resource.id) {
              <tr>
                <td>
                  <button type="button" (click)="selectedResourceId.set(resource.id)">
                    {{ resource.arn }}
                  </button>
                </td>
                <td>{{ resource.service }}</td>
                <td>{{ resource.region }}</td>
                <td>{{ resource.tagStatus }}</td>
                <td>{{ resource.ownerStatus }}</td>
              </tr>
            }
          </tbody>
        </table>

        <nav aria-label="Inventory pagination">
          <button
            type="button"
            [disabled]="inventory.page() <= 1"
            (click)="goToPage(inventory.page() - 1)"
          >
            Previous
          </button>
          <span>Page {{ inventory.page() }} of {{ totalPages() }}</span>
          <button
            type="button"
            [disabled]="inventory.page() >= totalPages()"
            (click)="goToPage(inventory.page() + 1)"
          >
            Next
          </button>
        </nav>
      }
    }

    @if (selectedResourceId(); as id) {
      <cp-resource-detail [resourceId]="id" />
    }
  `,
  styles: [
    `
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
      }
      form {
        display: flex;
        flex-wrap: wrap;
        gap: 1rem;
        margin-bottom: 1rem;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th,
      td {
        text-align: left;
        padding: 0.5rem;
        border-bottom: 1px solid #d0d0d0;
      }
    `,
  ],
})
export class InventoryExplorerComponent implements OnInit {
  protected readonly inventory = inject(InventoryService);
  protected readonly filters: InventoryFilters = {};
  protected readonly selectedResourceId = signal<string | null>(null);

  ngOnInit(): void {
    void this.inventory.load(this.filters);
  }

  protected applyFilters(): void {
    void this.inventory.load(this.filters);
  }

  protected setUnattributedOnly(checked: boolean): void {
    this.filters.ownerStatus = checked ? 'unattributed' : undefined;
  }

  protected goToPage(page: number): void {
    void this.inventory.load(this.filters, page);
  }

  protected totalPages(): number {
    return Math.max(1, Math.ceil(this.inventory.totalCount() / this.inventory.pageSize));
  }
}
