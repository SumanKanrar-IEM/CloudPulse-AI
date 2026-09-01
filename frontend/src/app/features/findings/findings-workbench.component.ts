import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/auth.service';
import { FindingStatus } from '../../api';
import { FindingsFilters, FindingsService } from './findings.service';

/**
 * List/filter findings, acknowledge them, and show each finding's
 * remediation suggestion inline (spec 004, S30, FR-014-FR-020a).
 */
@Component({
  selector: 'cp-findings-workbench',
  standalone: true,
  imports: [FormsModule],
  template: `
    <h1>Findings</h1>

    <form (ngSubmit)="applyFilters()" aria-label="Findings filters">
      <label>
        Status
        <select [(ngModel)]="statusFilter" name="status">
          <option [ngValue]="undefined">All</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="suppressed">Suppressed</option>
        </select>
      </label>
      <button type="submit">Apply</button>
    </form>

    @if (findings.loading()) {
      <p role="status">Loading findings…</p>
    }

    @if (findings.error()) {
      <p role="alert">{{ findings.error() }}</p>
    }

    @if (!findings.loading() && !findings.error()) {
      @if (findings.findings().length === 0) {
        <p>No matching findings.</p>
      } @else {
        <ul class="findings-list">
          @for (finding of findings.findings(); track finding.id) {
            <li>
              <div class="finding-row">
                <span>{{ finding.resource.arn }}</span>
                <span>{{ finding.ruleKey }}</span>
                <span>{{ finding.severity }}</span>
                <span>{{ finding.status }}</span>
                @if (finding.acknowledgedAt) {
                  <span data-testid="acknowledged-badge">Acknowledged</span>
                } @else if (canAcknowledge()) {
                  <button type="button" (click)="acknowledge(finding.id)">Acknowledge</button>
                }
                <button type="button" (click)="toggleSuggestion(finding.id)">
                  {{ expandedFindingId() === finding.id ? 'Hide suggestion' : 'Show suggestion' }}
                </button>
              </div>

              @if (expandedFindingId() === finding.id) {
                <div class="suggestion-panel">
                  @if (findings.suggestionErrors()[finding.id]; as suggestionError) {
                    <p role="alert">{{ suggestionError }}</p>
                  }
                  @if (!findings.suggestionErrors()[finding.id]) {
                    @if (findings.suggestions()[finding.id]; as suggestion) {
                      @if (suggestion.suggestionText) {
                        <p>
                          <strong>Suggestion{{ suggestion.source === 'admin_seeded' ? ' (test data)' : '' }}:</strong>
                          {{ suggestion.suggestionText }}
                        </p>
                        <p><strong>Blast radius:</strong> {{ suggestion.blastRadiusNote }}</p>
                      } @else {
                        <p>No suggestion available.</p>
                      }
                    } @else {
                      <p role="status">Loading suggestion…</p>
                    }
                  }

                  @if (isAdmin()) {
                    <form (ngSubmit)="seedSuggestion(finding.id)" aria-label="Attach demo suggestion">
                      <label>
                        Suggestion text
                        <input type="text" [(ngModel)]="seedText" name="seedText" />
                      </label>
                      <label>
                        Blast radius note
                        <input type="text" [(ngModel)]="seedBlastRadius" name="seedBlastRadius" />
                      </label>
                      <button type="submit">Attach demo suggestion</button>
                    </form>
                  }
                </div>
              }
            </li>
          }
        </ul>
      }
    }
  `,
  styles: [
    `
      form {
        display: flex;
        flex-wrap: wrap;
        gap: 1rem;
        align-items: flex-end;
        margin-bottom: 1rem;
      }
      .findings-list {
        list-style: none;
        padding: 0;
      }
      .finding-row {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding: 0.5rem 0;
        border-bottom: 1px solid #d0d0d0;
      }
      .suggestion-panel {
        padding: 0.5rem 1rem 1rem;
        background: #f7f7f7;
      }
    `,
  ],
})
export class FindingsWorkbenchComponent implements OnInit {
  protected readonly findings = inject(FindingsService);
  private readonly auth = inject(AuthService);

  protected statusFilter: FindingStatus | undefined = undefined;
  protected readonly expandedFindingId = signal<string | null>(null);
  protected seedText = '';
  protected seedBlastRadius = '';

  ngOnInit(): void {
    void this.findings.load({});
  }

  protected applyFilters(): void {
    const filters: FindingsFilters = { status: this.statusFilter };
    void this.findings.load(filters);
  }

  protected canAcknowledge(): boolean {
    const role = this.auth.role();
    return role === 'admin' || role === 'operator';
  }

  protected isAdmin(): boolean {
    return this.auth.role() === 'admin';
  }

  protected async acknowledge(findingId: string): Promise<void> {
    await this.findings.acknowledge(findingId);
  }

  protected toggleSuggestion(findingId: string): void {
    if (this.expandedFindingId() === findingId) {
      this.expandedFindingId.set(null);
      return;
    }
    this.expandedFindingId.set(findingId);
    if (!this.findings.suggestions()[findingId]) {
      void this.findings.loadSuggestion(findingId);
    }
  }

  protected async seedSuggestion(findingId: string): Promise<void> {
    await this.findings.seedSuggestion(findingId, this.seedText, this.seedBlastRadius);
    this.seedText = '';
    this.seedBlastRadius = '';
  }
}
