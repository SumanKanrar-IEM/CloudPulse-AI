import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';
import { ForecastResponse, ProjectForecasts } from '../../api';
import { ForecastsStateService } from './forecasts.service';

/**
 * Forecasts (S51, FR-021, FR-021a, FR-022): where each project's spend and
 * capacity are heading, with the backtested error a reader can judge it by.
 *
 * **Every figure on this page is the server's.** The chart plots
 * `projectedValue` as returned; the table prints it as returned. Nothing is
 * rounded, summed or derived here -- the same discipline FR-024 will hold a
 * narrative to, applied to the page the narrative would sit on.
 *
 * **Not enough data is shown, not hidden.** A project below the minimum
 * history appears with its counts (FR-021a). Dropping it from the table would
 * make "no forecast" look like "no project".
 *
 * No narrative yet: T054 is deferred (tasks.md T054a). The chart and table
 * stand on their own, which is the point of a chart.
 */
@Component({
  selector: 'cp-forecasts',
  standalone: true,
  imports: [DatePipe, BaseChartDirective],
  template: `
    <h1>Forecasts</h1>
    <p class="note">
      Deterministic projections over collected history. Re-running over the same history
      gives the same figures; the backtest error is what the same calculation got wrong on
      the last week it never saw.
    </p>

    @if (state.loading()) {
      <p role="status">Loading forecasts…</p>
    }

    @if (state.error()) {
      <p role="alert">{{ state.error() }}</p>
    }

    @if (!state.loading() && state.projects().length === 0) {
      <p>No projects registered.</p>
    } @else {
      @if (spendChartData().labels?.length) {
        <section>
          <h2>Projected spend, next 30 days</h2>
          <canvas
            baseChart
            [type]="'bar'"
            [data]="spendChartData()"
            [options]="chartOptions"
            aria-label="Projected spend per project over the next thirty days"
            role="img"
          ></canvas>
        </section>
      }

      <section>
        <h2>By project</h2>
        <table>
          <caption class="visually-hidden">
            Spend and capacity forecasts per project, with history and backtest error
          </caption>
          <thead>
            <tr>
              <th scope="col">Project</th>
              <th scope="col">Kind</th>
              <th scope="col">Period</th>
              <th scope="col">Projected</th>
              <th scope="col">History</th>
              <th scope="col">Backtest error</th>
            </tr>
          </thead>
          <tbody>
            @for (project of state.projects(); track project.sdaId) {
              @for (f of project.forecasts; track f.kind) {
                <tr>
                  <td>{{ project.sdaName }}</td>
                  <td>{{ f.kind }}</td>
                  <td>
                    @if (f.periodStart) {
                      {{ f.periodStart | date: 'mediumDate' }} –
                      {{ f.periodEnd | date: 'mediumDate' }}
                    } @else {
                      —
                    }
                  </td>
                  <td>
                    @if (f.insufficientHistory) {
                      <span class="badge">Not enough data</span>
                    } @else {
                      {{ projected(f) }}
                    }
                  </td>
                  <td>{{ f.historyDays }} of {{ f.requiredDays }} days</td>
                  <td>{{ backtestLabel(f) }}</td>
                </tr>
              }
            }
          </tbody>
        </table>
      </section>

      @if (state.generatedAt(); as at) {
        <p class="note">Calculated {{ at | date: 'medium' }}.</p>
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
      .badge {
        border-radius: 0.75rem;
        padding: 0.1rem 0.6rem;
        font-size: 0.85rem;
        font-weight: 600;
        background: #e4e4e4;
        color: #333333;
        white-space: nowrap;
      }
    `,
  ],
})
export class ForecastsComponent implements OnInit {
  protected readonly state = inject(ForecastsStateService);

  protected readonly chartOptions: ChartConfiguration['options'] = {
    responsive: true,
    indexAxis: 'y',
    plugins: { legend: { display: false } },
  };

  /** One bar per project with a spend projection. Projects without one are
   * absent from the chart and present in the table -- a zero-height bar would
   * read as "projected nothing", which is the wrong statement. */
  protected readonly spendChartData = computed((): ChartConfiguration<'bar'>['data'] => {
    const rows = this.state
      .projects()
      .map((p) => ({ name: p.sdaName, spend: this.spendOf(p) }))
      .filter((r) => r.spend !== null);
    return {
      labels: rows.map((r) => r.name),
      datasets: [{ data: rows.map((r) => Number(r.spend)), label: 'Projected spend (USD)' }],
    };
  });

  ngOnInit(): void {
    void this.state.refresh();
  }

  private spendOf(project: ProjectForecasts): string | null {
    const spend = project.forecasts.find((f) => f.kind === 'spend');
    return spend && !spend.insufficientHistory ? (spend.projectedValue ?? null) : null;
  }

  protected projected(f: ForecastResponse): string {
    return f.kind === 'spend' ? `$${f.projectedValue}` : `${f.projectedValue}% CPU`;
  }

  /** "No backtest" and "error 0.000%" are different facts; and a null error
   * with a backtest present means the held-out actual was zero. */
  protected backtestLabel(f: ForecastResponse): string {
    if (!f.backtest) {
      return '—';
    }
    const error = f.backtest.absolutePercentageError;
    return error === null || error === undefined
      ? `held-out actual was 0 over ${f.backtest.heldOutDays} days`
      : `${error}% over ${f.backtest.heldOutDays} days`;
  }
}
