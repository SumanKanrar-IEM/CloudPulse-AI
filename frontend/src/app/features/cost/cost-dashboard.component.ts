import { Component, OnInit, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { CostService, defaultSpendRange } from './cost.service';

/**
 * Cost dashboard (S39, S42, FR-003): a trend chart, a per-project spend
 * table, and drill-down to the resources behind a project's spend line.
 */
@Component({
  selector: 'cp-cost-dashboard',
  standalone: true,
  imports: [FormsModule, BaseChartDirective],
  template: `
    <h1>Cost</h1>

    <form (ngSubmit)="applyRange()" aria-label="Date range">
      <label>
        From
        <input type="date" [(ngModel)]="from" name="from" />
      </label>
      <label>
        To
        <input type="date" [(ngModel)]="to" name="to" />
      </label>
      <button type="submit">Apply</button>
    </form>

    @if (cost.loading()) {
      <p role="status">Loading spend…</p>
    }

    @if (cost.error()) {
      <p role="alert">{{ cost.error() }}</p>
    }

    @if (cost.summary(); as summary) {
      <section class="score-cards">
        <div class="score-card">
          <h2>Total spend</h2>
          <p class="score">{{ totalDisplay() }}</p>
        </div>
      </section>

      <section>
        <h2>Daily trend</h2>
        <canvas
          baseChart
          [type]="'line'"
          [data]="trendChartData()"
          [options]="chartOptions"
          aria-label="Daily spend trend, with gap days shown as a break in the line"
          role="img"
        ></canvas>
      </section>

      <section>
        <h2>By project</h2>
        <table>
          <caption class="visually-hidden">
            Spend by project (SDA), with a drill-down to the resources behind each line
          </caption>
          <thead>
            <tr>
              <th scope="col">Project</th>
              <th scope="col">Spend</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            @for (row of summary.byProject; track row.sdaId ?? 'none') {
              <tr>
                <td>{{ row.sdaName ?? 'No SDA' }}</td>
                <td>{{ row.totalUsd }}</td>
                <td>
                  <button type="button" (click)="cost.drillDown(row.sdaId ?? null, row.sdaName ?? null)">
                    View resources
                  </button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    @if (cost.budgets().length > 0) {
      <section>
        <h2>Budgets</h2>
        <table>
          <caption class="visually-hidden">
            Each project's budget and which alert thresholds it has crossed this month
          </caption>
          <thead>
            <tr>
              <th scope="col">Project</th>
              <th scope="col">Budget</th>
              <th scope="col">Actual</th>
              <th scope="col">Forecast</th>
            </tr>
          </thead>
          <tbody>
            @for (budget of cost.budgets(); track budget.id) {
              <tr>
                <td>{{ budget.sdaName }}</td>
                <td>{{ budget.amountUsd }}</td>
                <!-- FR-015: 80% is dashboard-only and sends no notification, so this
                     table is the only place it is ever surfaced. 100% also opens a
                     finding (FR-016), but is still shown here so the two thresholds
                     read as one progression rather than two unrelated signals. -->
                <td>
                  <span class="badge" [class]="thresholdClass(budget.actual100CrossedAt, budget.actual80CrossedAt)">
                    {{ thresholdLabel(budget.actual100CrossedAt, budget.actual80CrossedAt) }}
                  </span>
                </td>
                <td>
                  <span class="badge" [class]="thresholdClass(budget.forecast100CrossedAt, budget.forecast80CrossedAt)">
                    {{ thresholdLabel(budget.forecast100CrossedAt, budget.forecast80CrossedAt) }}
                  </span>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </section>
    }

    @if (cost.drillDownSda(); as sda) {
      <section aria-label="Resources for this project">
        <h2>Resources -- {{ sda.name ?? 'No SDA' }}</h2>
        <button type="button" (click)="cost.closeDrillDown()">Close</button>
        @if (cost.drillDownLoading()) {
          <p role="status">Loading resources…</p>
        } @else if (cost.drillDownResources().length === 0) {
          <p>No resources attributed to this project.</p>
        } @else {
          <ul>
            @for (resource of cost.drillDownResources(); track resource.id) {
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
      form {
        display: flex;
        flex-wrap: wrap;
        align-items: end;
        gap: 1rem;
        margin-bottom: 1rem;
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
      /* The label carries the meaning; colour only reinforces it. */
      .badge {
        border-radius: 0.75rem;
        padding: 0.1rem 0.6rem;
        font-size: 0.85rem;
        font-weight: 600;
        white-space: nowrap;
      }
      .badge-over {
        background: #7a1f1f;
        color: #ffffff;
      }
      .badge-warning {
        background: #8a5a00;
        color: #ffffff;
      }
      .badge-ok {
        background: #e4e4e4;
        color: #333333;
      }
    `,
  ],
})
export class CostDashboardComponent implements OnInit {
  protected readonly cost = inject(CostService);

  protected readonly chartOptions: ChartConfiguration['options'] = {
    responsive: true,
    plugins: { legend: { display: false } },
  };

  protected from = defaultSpendRange().from;
  protected to = defaultSpendRange().to;

  protected readonly totalDisplay = computed(() => {
    const summary = this.cost.summary();
    return summary ? `$${summary.totalUsd}` : '';
  });

  protected readonly trendChartData = computed((): ChartConfiguration<'line'>['data'] => {
    const trend = this.cost.summary()?.trend ?? [];
    return {
      labels: trend.map((point) => point.date),
      datasets: [
        {
          data: trend.map((point) =>
            point.totalUsd === null || point.totalUsd === undefined
              ? null
              : Number(point.totalUsd),
          ),
          label: 'Daily spend',
        },
      ],
    };
  });

  ngOnInit(): void {
    void this.cost.refresh(this.from, this.to);
  }

  protected applyRange(): void {
    void this.cost.refresh(this.from, this.to);
  }

  /** A crossed-100 timestamp outranks a crossed-80 one: both are set once spend
   * passes 100%, and reporting the lesser of the two would understate it. */
  protected thresholdLabel(crossed100?: string | null, crossed80?: string | null): string {
    if (crossed100) {
      return 'Over budget';
    }
    return crossed80 ? 'Over 80%' : 'Within budget';
  }

  protected thresholdClass(crossed100?: string | null, crossed80?: string | null): string {
    if (crossed100) {
      return 'badge-over';
    }
    return crossed80 ? 'badge-warning' : 'badge-ok';
  }
}
