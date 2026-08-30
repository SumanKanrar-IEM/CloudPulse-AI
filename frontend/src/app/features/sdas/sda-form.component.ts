import { Component, EventEmitter, Input, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Sda } from '../../api';
import { SdasService } from './sdas.service';

/**
 * Register or edit an SDA and its tag-value mapping (FR-007-FR-010, FR-010a).
 *
 * Rendered only when an admin has opened it -- `sdas-list.component.ts` disables
 * (never merely hides) the trigger for non-admin roles, per spec 002's
 * `account-form.component.ts` precedent; the real gate is server-side (FR-029)
 * regardless.
 *
 * `tagValues` is edited as a single "key=value" per line field rather than a
 * dynamic multi-row widget -- the same minimal-input style
 * `account-form.component.ts` already uses for its comma-separated region list.
 */
@Component({
  selector: 'cp-sda-form',
  standalone: true,
  imports: [FormsModule],
  template: `
    <form (ngSubmit)="submit()" [attr.aria-label]="editing() ? 'Edit SDA' : 'Register an SDA'">
      <div>
        @if (!editing()) {
          <label for="name">Name</label>
          <input id="name" type="text" [(ngModel)]="name" name="name" required />
        }
      </div>

      <div>
        <label for="ownerEmail">Owner email</label>
        <input id="ownerEmail" type="email" [(ngModel)]="ownerEmail" name="ownerEmail" required />
      </div>

      <div>
        <label for="team">Team (optional)</label>
        <input id="team" type="text" [(ngModel)]="team" name="team" />
      </div>

      <div>
        <label for="tagValues">Tag-value mapping (one "key=value" per line)</label>
        <textarea
          id="tagValues"
          [(ngModel)]="tagValuesInput"
          name="tagValues"
          rows="4"
          placeholder="team=platform&#10;env=prod"
        ></textarea>
      </div>

      @if (formError(); as err) {
        <p role="alert">{{ err }}</p>
      }

      <button type="submit" [disabled]="submitting()">
        {{ submitting() ? 'Saving…' : editing() ? 'Save changes' : 'Register' }}
      </button>
    </form>
  `,
})
export class SdaFormComponent {
  @Input() set sda(value: Sda | null) {
    this.editing.set(value);
    if (value) {
      this.ownerEmail.set(value.ownerEmail);
      this.team.set(value.team ?? '');
      this.tagValuesInput.set(
        Object.entries(value.tagValues)
          .map(([k, v]) => `${k}=${v}`)
          .join('\n'),
      );
    }
  }
  @Output() readonly saved = new EventEmitter<void>();

  private readonly sdas = inject(SdasService);

  protected readonly editing = signal<Sda | null>(null);
  protected readonly name = signal('');
  protected readonly ownerEmail = signal('');
  protected readonly team = signal('');
  protected readonly tagValuesInput = signal('');
  protected readonly submitting = signal(false);
  protected readonly formError = signal<string | null>(null);

  private parseTagValues(): Record<string, string> {
    const tagValues: Record<string, string> = {};
    for (const line of this.tagValuesInput().split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const [key, ...rest] = trimmed.split('=');
      if (key && rest.length > 0) {
        tagValues[key.trim()] = rest.join('=').trim();
      }
    }
    return tagValues;
  }

  protected async submit(): Promise<void> {
    this.formError.set(null);
    const tagValues = this.parseTagValues();
    if (Object.keys(tagValues).length === 0) {
      this.formError.set('Enter at least one tag-value mapping, formatted as key=value.');
      return;
    }

    this.submitting.set(true);
    try {
      const current = this.editing();
      if (current) {
        await this.sdas.update(current.id, {
          ownerEmail: this.ownerEmail(),
          team: this.team() || undefined,
          tagValues,
        });
      } else {
        await this.sdas.register({
          name: this.name(),
          ownerEmail: this.ownerEmail(),
          team: this.team() || undefined,
          tagValues,
        });
      }
      this.saved.emit();
    } catch {
      this.formError.set(
        'Save failed. Confirm the mapping does not overlap an existing SDA and try again.',
      );
    } finally {
      this.submitting.set(false);
    }
  }
}
