import { Component, Input, OnChanges, inject } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { InventoryService } from './inventory.service';

/**
 * A resource's detail panel: tags, owner + evidence, findings, enrichment
 * detail (FR-012).
 */
@Component({
  selector: 'cp-resource-detail',
  standalone: true,
  imports: [JsonPipe],
  template: `
    @if (inventory.detailLoading()) {
      <p role="status">Loading resource detail…</p>
    }
    @if (inventory.detailError()) {
      <p role="alert">{{ inventory.detailError() }}</p>
    }
    @if (!inventory.detailLoading() && inventory.detail(); as detail) {
      <h2>{{ detail.arn }}</h2>

      <h3>Tags</h3>
      @if (objectEntries(detail.tags).length === 0) {
        <p>No tags.</p>
      } @else {
        <dl>
          @for (entry of objectEntries(detail.tags); track entry[0]) {
            <dt>{{ entry[0] }}</dt>
            <dd>{{ entry[1] }}</dd>
          }
        </dl>
      }

      <h3>Owner</h3>
      @if (detail.owner) {
        <p>{{ detail.owner['ownerEmail'] }} ({{ detail.owner['confidence'] }} confidence)</p>
      } @else {
        <p>Unattributed</p>
      }

      <h3>Findings</h3>
      @if (detail.findings.length === 0) {
        <p>No findings.</p>
      } @else {
        <ul>
          @for (finding of detail.findings; track finding['id']) {
            <li>{{ finding['ruleKey'] }} ({{ finding['severity'] }}, {{ finding['status'] }})</li>
          }
        </ul>
      }

      <h3>Enrichment detail</h3>
      @if (objectEntries(detail.detail).length === 0) {
        <p>No enrichment detail captured.</p>
      } @else {
        <pre>{{ detail.detail | json }}</pre>
      }
    }
  `,
})
export class ResourceDetailComponent implements OnChanges {
  @Input({ required: true }) resourceId!: string;

  protected readonly inventory = inject(InventoryService);

  ngOnChanges(): void {
    if (this.resourceId) {
      void this.inventory.loadDetail(this.resourceId);
    }
  }

  protected objectEntries(value: Record<string, unknown>): [string, unknown][] {
    return Object.entries(value ?? {});
  }
}
