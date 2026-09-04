import { Component, OnInit, inject } from '@angular/core';
import { UtilizationFigure } from '../../api';
import { UtilizationStateService } from './utilization.service';

/**
 * Utilization (S54, S55, FR-018): overall, per account, per project, with
 * drill-down to the resources behind a project's figure.
 *
 * Every figure states the population it was measured over. Research.md R-509
 * excludes resources with no known state from both halves of the ratio, so a
 * bare percentage here would imply a claim over the whole inventory that the
 * data does not support.
 */
@Component({
  selector: 'cp-utilization',
  standalone: true,
  template: `
    <h1>Utilization</h1>

    @if (state.loading()) {
      <p role="status">Loading utilization…</p>
    }

    @if (state.error()) {
      <p role="alert">{{ state.error() }}</p>
    }

    @if (state.report(); as report) {
      <section class="score-cards">
        <div class="score-card">
          <h2>Overall</h2>
          <p class="score">{{ display(report.overall) }}</p>
          <p class="scope">{{ scope(report.overall) }}</p>
        </div>
      </section>

      <section>
        <h2>By account</h2>
        <table>
          <caption class="visually-hidden">
            Utilization per cloud account, over resources whose state is known
          </caption>
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col">Utilization</th>
              <th scope="col">Scope</th>
            </tr>
          </thead>
          <tbody>
            @for (row of report.byAccount; track row.accountId) {
              <tr>
                <td>{{ row.alias }}</td>
                <td>{{ display(row.utilization) }}</td>
                <td>{{ scope(row.utilization) }}</td>
              </tr>
            }
          </tbody>
        </table>
      </section>

      <section>
        <h2>By project</h2>
        <table>
          <caption class="visually-hidden">
            Utilization per project, with a drill-down to the resources behind each figure
          </caption>
          <thead>
            <tr>
              <th scope="col">Project</th>
              <th scope="col">Utilization</th>
              <th scope="col">Scope</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            @for (row of report.byProject; track row.sdaId ?? 'none') {
              <tr>
                <td>{{ row.sdaName ?? 'No SDA' }}</td>
                <td>{{ display(row.utilization) }}</td>
                <td>{{ scope(row.utilization) }}</td>
                <td>
                  <button type="button" (click)="state.openProject(row.sdaId ?? null, row.sdaName ?? null)">
                    View resources
                  </button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    @if (state.drillDown(); as project) {
      <section aria-label="Resources for this project">
        <h2>Resources -- {{ project.name ?? 'No SDA' }}</h2>
        <button type="button" (click)="state.closeDrillDown()">Close</button>
        @if (state.resourcesLoading()) {
          <p role="status">Loading resources…</p>
        } @else if (state.resources().length === 0) {
          <p>No resources attributed to this project.</p>
        } @else {
          <ul>
            @for (resource of state.resources(); track resource.id) {
              <li>{{ resource.arn }} ({{ resource.service }}, {{ resource.region }})</li>
            }
          </ul>
        }
      </section>
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
      .score-cards {
        display: flex;
        gap: 1rem;
      }
      .score-card {
        border: 1px solid #d0d0d0;
        border-radius: 4px;
        padding: 1rem;
        min-width: 14rem;
      }
      .score {
        font-size: 2rem;
        font-weight: bold;
        margin: 0;
      }
      .scope {
        margin: 0;
        color: #555555;
        font-size: 0.85rem;
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
export class UtilizationComponent implements OnInit {
  protected readonly state = inject(UtilizationStateService);

  ngOnInit(): void {
    void this.state.refresh();
  }

  /** R-509: "not enough data" is a real answer, and reads better than 0%. */
  protected display(figure: UtilizationFigure): string {
    return figure.percent === null || figure.percent === undefined
      ? 'Not enough data'
      : `${figure.percent}%`;
  }

  /** The population the figure was measured over, always shown beside it. */
  protected scope(figure: UtilizationFigure): string {
    return `${figure.used} of ${figure.provisioned} enriched resources`;
  }
}
