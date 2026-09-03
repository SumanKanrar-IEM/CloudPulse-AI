import { Component, OnInit, computed, inject } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { OverviewService } from './overview.service';

/**
 * Compliance overview (S28, FR-006-FR-009). Score cards, findings-by-type/
 * severity charts, and a per-account summary table -- every number sourced
 * directly from `OverviewService`'s API-fetched state, nothing computed here
 * beyond simple counting/grouping of already-fetched values (FR-006).
 */
@Component({
  selector: 'cp-compliance-overview',
  standalone: true,
  imports: [BaseChartDirective],
  template: `
    <h1>Compliance overview</h1>

    @if (overview.loading()) {
      <p role="status">Loading compliance overview…</p>
    }

    @if (overview.error()) {
      <p role="alert">{{ overview.error() }}</p>
    }

    @if (!overview.loading() && !overview.error()) {
      @if (overview.accountOverviews().length === 0) {
        <p>No connected accounts yet.</p>
      } @else {
        <section class="score-cards">
          <div class="score-card">
            <h2>Overall</h2>
            <p class="score">{{ overallScorePercent() }}</p>
            <p>{{ overallCompliantCount() }} / {{ overallTotalCount() }} resources compliant</p>
          </div>
        </section>

        <section>
          <h2>Findings by type</h2>
          @if (byTypeChartData().labels!.length > 0) {
            <canvas
              baseChart
              [type]="'bar'"
              [data]="byTypeChartData()"
              [options]="chartOptions"
              aria-label="Open findings by tag rule"
              role="img"
            ></canvas>
          } @else {
            <p>No open findings.</p>
          }
        </section>

        <section>
          <h2>Findings by severity</h2>
          @if (bySeverityChartData().labels!.length > 0) {
            <canvas
              baseChart
              [type]="'bar'"
              [data]="bySeverityChartData()"
              [options]="chartOptions"
              aria-label="Open findings by severity"
              role="img"
            ></canvas>
          } @else {
            <p>No open findings.</p>
          }
        </section>

        <section>
          <h2>Accounts</h2>
          <table>
            <caption class="visually-hidden">
              Per-account compliance score, resource count, and open finding count
            </caption>
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col">Score</th>
                <th scope="col">Resources</th>
                <th scope="col">Open findings</th>
              </tr>
            </thead>
            <tbody>
              @for (row of overview.accountOverviews(); track row.account.id) {
                <tr>
                  <td>{{ row.account.alias || row.account.awsAccountId }}</td>
                  @if (row.score) {
                    <td>{{ (row.score.score * 100).toFixed(0) }}%</td>
                    <td>{{ row.score.totalCount }}</td>
                    <td>{{ row.openFindingCount }}</td>
                  } @else {
                    <td colspan="3">Not yet scanned</td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </section>
      }
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
        min-width: 12rem;
      }
      .score {
        font-size: 2rem;
        font-weight: bold;
        margin: 0;
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
      canvas {
        max-width: 100%;
      }
    `,
  ],
})
export class ComplianceOverviewComponent implements OnInit {
  protected readonly overview = inject(OverviewService);

  protected readonly chartOptions: ChartConfiguration['options'] = {
    responsive: true,
    plugins: { legend: { display: false } },
  };

  // FR-006: the overall score is a sum of the same per-account compliantCount/
  // totalCount the API already returned -- never an independently invented
  // formula -- so SC-004's "matches the API on every check" still holds.
  protected readonly overallCompliantCount = computed(() =>
    this.overview
      .accountOverviews()
      .reduce((sum, row) => sum + (row.score?.compliantCount ?? 0), 0),
  );
  protected readonly overallTotalCount = computed(() =>
    this.overview.accountOverviews().reduce((sum, row) => sum + (row.score?.totalCount ?? 0), 0),
  );
  protected readonly overallScorePercent = computed(() => {
    const total = this.overallTotalCount();
    if (total === 0) {
      return 'No data yet';
    }
    return `${((this.overallCompliantCount() / total) * 100).toFixed(0)}%`;
  });

  // spec 005, R-508: a budget_overrun finding has no rule, so it groups under its
  // kind instead. Grouping it under a blank key would collapse every overrun into
  // one unlabelled bar; filtering it out would make this chart's total disagree
  // with the severity chart beside it, which does count them.
  protected readonly byTypeChartData = computed(() =>
    this.groupedChartData((f) => f.ruleKey ?? f.kind),
  );
  protected readonly bySeverityChartData = computed(() =>
    this.groupedChartData((f) => f.severity),
  );

  ngOnInit(): void {
    void this.overview.refresh();
  }

  private groupedChartData(
    keyOf: (finding: { ruleKey?: string | null; kind: string; severity: string }) => string,
  ): ChartConfiguration<'bar'>['data'] {
    const counts = new Map<string, number>();
    for (const finding of this.overview.findings()) {
      const key = keyOf(finding);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const labels = [...counts.keys()];
    return {
      labels,
      datasets: [{ data: labels.map((label) => counts.get(label)!), label: 'Open findings' }],
    };
  }
}
