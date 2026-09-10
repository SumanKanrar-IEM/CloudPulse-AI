import { DatePipe } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { CoverageProposalResponse } from '../../api';
import { AuthService } from '../../core/auth.service';
import { CoverageProposalsStateService } from './coverage-proposals.service';

/**
 * Coverage advisor (S43, FR-015, FR-015a, FR-016, FR-018): gaps in what the
 * platform governs, split by whether a decision can close them.
 *
 * **Two sections, and the difference between them is the whole screen.**
 * Proposals carry Accept and Reject for an admin, because accepting one changes
 * configuration and takes effect on the next scan. Advisory gaps carry no
 * control at all — not a disabled button, not a greyed-out one. A disabled
 * control still tells the reader "this is acceptable, just not by you", which
 * is false here for everyone: closing these needs someone to write code, and
 * FR-015a judges an acceptance control that cannot take effect worse than not
 * surfacing the gap.
 *
 * A non-admin sees both lists in full and gets no decision buttons (FR-016).
 * The buttons are absent for them rather than disabled for the same reason
 * every other admin-gated control in this app is absent: the API refuses the
 * call regardless, so a rendered control would only promise something the
 * server will deny.
 */
@Component({
  selector: 'cp-coverage-proposals',
  standalone: true,
  imports: [DatePipe],
  template: `
    <h1>Coverage advisor</h1>
    <p class="note">
      Resource types this platform does not govern yet. Accepting a proposal changes
      configuration and takes effect on the next scan — nothing here is applied
      automatically, and nothing changes a cloud account.
    </p>

    @if (state.loading()) {
      <p role="status">Loading coverage gaps…</p>
    }

    @if (state.error()) {
      <p role="alert">{{ state.error() }}</p>
    }

    <section>
      <h2>Proposals</h2>
      @if (!state.loading() && state.proposals().length === 0) {
        <p>No coverage proposals are open.</p>
      } @else {
        <table>
          <caption class="visually-hidden">
            Coverage gaps that can be closed by accepting a configuration change
          </caption>
          <thead>
            <tr>
              <th scope="col">Resource type</th>
              <th scope="col">What accepting does</th>
              <th scope="col">Status</th>
              @if (isAdmin()) {
                <th scope="col">Decision</th>
              }
            </tr>
          </thead>
          <tbody>
            @for (proposal of state.proposals(); track proposal.id) {
              <tr>
                <td class="identifier">{{ proposal.resourceType }}</td>
                <td>{{ kindLabel(proposal) }}</td>
                <td>
                  @if (proposal.reviewState === 'accepted') {
                    <span class="badge badge-accepted">Accepted</span>
                    @if (proposal.appliedAt) {
                      <span class="applied"
                        >applies from {{ proposal.appliedAt | date: 'mediumDate' }}</span
                      >
                    }
                  } @else if (proposal.reviewState === 'rejected') {
                    <span class="badge badge-rejected">Rejected</span>
                  } @else {
                    <span class="badge badge-pending">Awaiting decision</span>
                  }
                </td>
                @if (isAdmin()) {
                  <td>
                    @if (proposal.reviewState === 'pending') {
                      <button
                        type="button"
                        (click)="state.decide(proposal.id, true)"
                        [disabled]="state.deciding() === proposal.id"
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        (click)="state.decide(proposal.id, false)"
                        [disabled]="state.deciding() === proposal.id"
                      >
                        Reject
                      </button>
                    } @else {
                      <span class="decided">Decided</span>
                    }
                  </td>
                }
              </tr>
            }
          </tbody>
        </table>
      }
    </section>

    <section>
      <h2>Needs a platform change</h2>
      <p class="note">
        These gaps cannot be closed by configuration. There is no decision to make here —
        closing one needs a change to the platform itself.
      </p>
      @if (!state.loading() && state.gaps().length === 0) {
        <p>No gaps of this kind were found.</p>
      } @else {
        <ul class="gaps">
          @for (gap of state.gaps(); track gap.resourceType) {
            <li>
              <span class="identifier">{{ gap.resourceType }}</span>
              <p class="reason">{{ gap.reason }}</p>
              <p class="observed">Last seen {{ gap.observedAt | date: 'mediumDate' }}</p>
            </li>
          }
        </ul>
      }
    </section>
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
      .badge {
        border-radius: 0.75rem;
        padding: 0.1rem 0.6rem;
        font-size: 0.85rem;
        font-weight: 600;
        white-space: nowrap;
      }
      .badge-pending {
        background: #8a5a00;
        color: #ffffff;
      }
      .badge-accepted {
        background: #1f6b3a;
        color: #ffffff;
      }
      .badge-rejected {
        background: #e4e4e4;
        color: #333333;
      }
      .applied,
      .observed,
      .decided {
        color: #555555;
        font-size: 0.85rem;
      }
      .applied {
        margin-left: 0.5rem;
      }
      button + button {
        margin-left: 0.5rem;
      }
      .gaps {
        list-style: none;
        padding: 0;
      }
      .gaps li {
        border-bottom: 1px solid #d0d0d0;
        padding: 0.5rem 0;
      }
      .reason {
        margin: 0.25rem 0 0;
      }
    `,
  ],
})
export class CoverageProposalsComponent implements OnInit {
  protected readonly state = inject(CoverageProposalsStateService);
  private readonly auth = inject(AuthService);

  ngOnInit(): void {
    void this.state.refresh();
  }

  protected isAdmin(): boolean {
    return this.auth.role() === 'admin';
  }

  /**
   * Says what accepting would do, not which enum value the row carries.
   * "enable_existing_enricher" is the platform's word for it; an admin deciding
   * needs to know what changes.
   */
  protected kindLabel(proposal: CoverageProposalResponse): string {
    if (proposal.proposalKind === 'enable_existing_enricher') {
      const fn = proposal.proposedChange?.['enrichment_function'];
      return fn
        ? `Collects detail for this type using ${String(fn)}`
        : 'Collects detail for this type';
    }
    return 'Adds or widens a tagging rule over fields already collected';
  }
}
