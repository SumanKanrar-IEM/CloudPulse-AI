import { Component, OnInit, inject, signal } from '@angular/core';
import { AuthService } from '../../core/auth.service';
import { SdasService } from './sdas.service';
import { SdaFormComponent } from './sda-form.component';
import { NoSdaTriageComponent } from './no-sda-triage.component';
import { Sda } from '../../api';

/**
 * The SDA admin surface (FR-007-FR-010b, FR-011, S18b).
 *
 * Visible to all three roles -- it is a read surface. Only the state-changing
 * actions (register/edit/remove) are admin-gated, and gated by *disabling* the
 * control rather than hiding it, matching `accounts-list.component.ts`'s
 * established role-guard precedent.
 */
@Component({
  selector: 'cp-sdas-list',
  standalone: true,
  imports: [SdaFormComponent, NoSdaTriageComponent],
  template: `
    <h1>Service delivery areas</h1>

    @if (auth.role() === 'admin') {
      <button type="button" (click)="showRegisterForm.set(!showRegisterForm())">
        {{ showRegisterForm() ? 'Cancel' : 'Register an SDA' }}
      </button>
      @if (showRegisterForm()) {
        <cp-sda-form (saved)="showRegisterForm.set(false)" />
      }
    } @else {
      <p>
        Only an admin can register a new SDA.
        <button type="button" disabled aria-disabled="true">Register an SDA</button>
      </p>
    }

    @if (sdas.loading()) {
      <p role="status">Loading SDAs…</p>
    }

    @if (sdas.error()) {
      <p role="alert">{{ sdas.error() }}</p>
    }

    @if (!sdas.loading() && sdas.sdas().length === 0 && !sdas.error()) {
      <p>No SDAs registered yet.</p>
    }

    @if (sdas.sdas().length > 0) {
      <table>
        <caption class="visually-hidden">
          Registered SDAs, their owner, team, and tag-value mapping
        </caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Owner</th>
            <th scope="col">Team</th>
            <th scope="col">Tag values</th>
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          @for (sda of sdas.sdas(); track sda.id) {
            <tr>
              <td>{{ sda.name }}</td>
              <td>{{ sda.ownerEmail }}</td>
              <td>{{ sda.team || '—' }}</td>
              <td>
                @for (entry of tagValueEntries(sda); track entry) {
                  <div>{{ entry }}</div>
                }
              </td>
              <td>
                <button
                  type="button"
                  [disabled]="auth.role() !== 'admin'"
                  [attr.aria-disabled]="auth.role() !== 'admin'"
                  (click)="editingId.set(editingId() === sda.id ? null : sda.id)"
                >
                  {{ editingId() === sda.id ? 'Cancel' : 'Edit' }}
                </button>
                <button
                  type="button"
                  [disabled]="auth.role() !== 'admin'"
                  [attr.aria-disabled]="auth.role() !== 'admin'"
                  (click)="remove(sda.id)"
                >
                  Remove
                </button>
                @if (editingId() === sda.id) {
                  <cp-sda-form [sda]="sda" (saved)="editingId.set(null)" />
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    }

    <cp-no-sda-triage />
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
export class SdasListComponent implements OnInit {
  protected readonly auth = inject(AuthService);
  protected readonly sdas = inject(SdasService);
  protected readonly showRegisterForm = signal(false);
  protected readonly editingId = signal<string | null>(null);

  ngOnInit(): void {
    void this.sdas.refresh();
  }

  protected tagValueEntries(sda: Sda): string[] {
    return Object.entries(sda.tagValues).map(([k, v]) => `${k}=${v}`);
  }

  protected async remove(sdaId: string): Promise<void> {
    await this.sdas.remove(sdaId);
  }
}
