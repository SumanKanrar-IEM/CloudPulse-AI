import { Component, OnInit, inject } from '@angular/core';
import { RightsizingRecommendationResponse } from '../../api';
import { RightsizingStateService } from './rightsizing.service';

/**
 * Rightsizing (S52, FR-023, FR-002): resources provisioned larger than their
 * measured use, what to change them to, and roughly what that saves -- with
 * the measurements that justify it, inline.
 *
 * The evidence is in the row, not behind an expander. This view asks an
 * operator to shrink something, and a recommendation without its basis is a
 * guess presented as a fact -- the same argument the IAM hygiene view makes
 * before asking someone to delete something.
 *
 * No control applies anything. Not a disabled button, not a "request change"
 * link: nothing. FR-002 and acceptance scenario 3, and
 * `test_no_remediation_execution.py` scans this file for the alternative.
 */
@Component({
  selector: 'cp-rightsizing',
  standalone: true,
  template: `
    <h1>Rightsizing</h1>
    <p class="note">
      Recommendations only. Nothing here changes a resource — acting on one is a decision an
      operator makes in their own account.
    </p>

    @if (state.loading()) {
      <p role="status">Loading recommendations…</p>
    }

    @if (state.error()) {
      <p role="alert">{{ state.error() }}</p>
    }

    @if (!state.loading() && state.recommendations().length === 0) {
      <p>No resource has enough history of sustained low use to recommend a smaller class.</p>
    } @else {
      <table>
        <caption class="visually-hidden">
          Resources recommended for a smaller instance class, with the measurements behind each
        </caption>
        <thead>
          <tr>
            <th scope="col">Resource</th>
            <th scope="col">Current</th>
            <th scope="col">Recommended</th>
            <th scope="col">Est. monthly saving</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          @for (rec of state.recommendations(); track rec.resourceId) {
            <tr>
              <td class="identifier">{{ rec.arn }}</td>
              <td class="identifier">{{ rec.currentClass }}</td>
              <td class="identifier">{{ rec.recommendedClass }}</td>
              <td>{{ '$' + rec.estimatedMonthlySavingUsd }}</td>
              <td class="evidence">{{ evidence(rec) }}</td>
            </tr>
          }
        </tbody>
      </table>
      <p class="note">{{ state.pricingNote() }}</p>
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
      .note {
        color: #555555;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1rem;
      }
      th,
      td {
        text-align: left;
        padding: 0.5rem;
        border-bottom: 1px solid #d0d0d0;
        vertical-align: top;
      }
      .identifier {
        font-family: monospace;
        word-break: break-all;
      }
      .evidence {
        font-size: 0.9rem;
      }
    `,
  ],
})
export class RightsizingComponent implements OnInit {
  protected readonly state = inject(RightsizingStateService);

  ngOnInit(): void {
    void this.state.refresh();
  }

  /**
   * The measurements and the thresholds they were judged against, in one
   * sentence a reader can check. Every number here came from the server; the
   * view composes them and adds none (FR-024's discipline, applied to a table).
   */
  protected evidence(rec: RightsizingRecommendationResponse): string {
    const e = rec.evidence;
    return (
      `CPU averaged ${e['mean_percent']}% and peaked at ${e['peak_percent']}% ` +
      `over ${e['periods']} days (${e['period_first']} to ${e['period_last']}); ` +
      `thresholds ${e['low_threshold_percent']}% mean, ${e['peak_threshold_percent']}% peak.`
    );
  }
}
