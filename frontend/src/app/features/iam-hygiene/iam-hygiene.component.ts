import { DatePipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IamHygieneFlag } from '../../api';
import { IamHygieneStateService } from './iam-hygiene.service';

/**
 * IAM hygiene (S56, FR-019, FR-020): roles, users, and keys that appear
 * unused, with the evidence behind each recommendation.
 *
 * Every flag shows its evidence inline rather than behind an expander. This
 * view asks a human to delete something, and a recommendation without its
 * basis is a guess presented as a fact.
 */
@Component({
  selector: 'cp-iam-hygiene',
  standalone: true,
  imports: [DatePipe, FormsModule],
  template: `
    <h1>IAM hygiene</h1>
    <p class="note">
      Flag-only recommendations. This platform never deletes or deactivates an IAM
      principal — acting on a flag is always a human decision.
    </p>

    <label>
      <input
        type="checkbox"
        [ngModel]="state.includeCleared()"
        (ngModelChange)="state.refresh($event)"
        name="includeCleared"
      />
      Include cleared flags
    </label>

    @if (state.loading()) {
      <p role="status">Loading flags…</p>
    }

    @if (state.error()) {
      <p role="alert">{{ state.error() }}</p>
    }

    @if (!state.loading() && state.flags().length === 0) {
      <p>No unused principals flagged.</p>
    } @else {
      <table>
        <caption class="visually-hidden">
          IAM principals that appear unused, with the evidence for each
        </caption>
        <thead>
          <tr>
            <th scope="col">Principal</th>
            <th scope="col">Type</th>
            <th scope="col">Last used</th>
            <th scope="col">Flagged</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          @for (flag of state.flags(); track flag.id) {
            <tr>
              <td class="identifier">{{ flag.principalIdentifier }}</td>
              <td>{{ flag.principalType }}</td>
              <td>{{ lastUsed(flag) }}</td>
              <td>{{ flag.flaggedAt | date: 'mediumDate' }}</td>
              <td>
                @if (flag.clearedAt) {
                  <span class="badge badge-cleared">Cleared</span>
                } @else {
                  <span class="badge badge-active">Unused</span>
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    }
  `,
})
export class IamHygieneComponent implements OnInit {
  protected readonly state = inject(IamHygieneStateService);

  ngOnInit(): void {
    void this.state.refresh();
  }

  /**
   * "Never used" and "used a long time ago" are different facts, and the
   * evidence keeps them apart rather than collapsing both into a blank cell.
   */
  protected lastUsed(flag: IamHygieneFlag): string {
    const days = flag.evidence?.['daysSinceLastUse'];
    if (typeof days === 'number') {
      return `${days} days ago`;
    }
    return String(flag.evidence?.['reason'] ?? 'never');
  }
}
