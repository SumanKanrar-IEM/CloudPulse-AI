import { Component, EventEmitter, Output, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConnectionMode, ExternalIdResponse } from '../../api';
import { AccountsService } from './accounts.service';

/**
 * Register (and, from the list view, deactivate/reactivate) an account (FR-006,
 * FR-011, FR-011a). Rendered only when an admin has opened it -- `accounts-list
 * -component.ts` disables (never merely hides) the trigger for non-admin roles, per
 * spec 1's role-guard precedent; the real gate is server-side (FR-011a) regardless.
 *
 * Cross-account registration is two steps because it has to be: FR-003a requires the
 * platform to generate the ExternalId, but the admin needs that value *before* they
 * can deploy the cross-account template and get back a role ARN to submit here
 * (T016a's contract addition). Same-account mode skips both -- it needs only a
 * region list.
 */
@Component({
  selector: 'cp-account-form',
  standalone: true,
  imports: [FormsModule],
  template: `
    <form (ngSubmit)="submit()" aria-label="Register an AWS account">
      <fieldset>
        <legend>Connection mode</legend>
        <label>
          <input type="radio" name="mode" value="local" [(ngModel)]="mode" />
          Same account (this platform's own AWS account)
        </label>
        <label>
          <input type="radio" name="mode" value="assume_role" [(ngModel)]="mode" />
          Cross-account (a separate AWS account)
        </label>
      </fieldset>

      <div>
        <label for="alias">Alias (optional)</label>
        <input id="alias" type="text" [(ngModel)]="alias" name="alias" />
      </div>

      <div>
        <label for="regions">Regions (comma-separated)</label>
        <input
          id="regions"
          type="text"
          [(ngModel)]="regionsInput"
          name="regions"
          placeholder="us-east-1"
        />
      </div>

      @if (mode() === 'assume_role') {
        <div>
          <button type="button" (click)="getExternalId()" [disabled]="requestingExternalId()">
            {{ externalId() ? 'Regenerate ExternalId' : 'Get ExternalId' }}
          </button>

          @if (externalId(); as ext) {
            <p>
              1. Deploy the
              <a [href]="templateUrl()" target="_blank" rel="noopener">cross-account template</a>
              into the target account, supplying this ExternalId:
              <code>{{ ext }}</code>
            </p>
            <p>2. Enter the AWS account ID and the resulting role ARN below.</p>
          }
        </div>

        <div>
          <label for="awsAccountId">Target AWS account ID</label>
          <input id="awsAccountId" type="text" [(ngModel)]="awsAccountId" name="awsAccountId" />
        </div>

        <div>
          <label for="roleArn">Scanner role ARN</label>
          <input id="roleArn" type="text" [(ngModel)]="roleArn" name="roleArn" />
        </div>
      }

      @if (formError(); as err) {
        <p role="alert">{{ err }}</p>
      }

      <button type="submit" [disabled]="submitting()">
        {{ submitting() ? 'Registering…' : 'Register' }}
      </button>
    </form>
  `,
})
export class AccountFormComponent {
  @Output() readonly registered = new EventEmitter<void>();

  private readonly accounts = inject(AccountsService);

  protected readonly mode = signal<ConnectionMode>(ConnectionMode.Local);
  protected readonly alias = signal('');
  protected readonly regionsInput = signal('');
  protected readonly awsAccountId = signal('');
  protected readonly roleArn = signal('');
  protected readonly externalId = signal<string | null>(null);
  protected readonly templateUrl = signal('');
  protected readonly requestingExternalId = signal(false);
  protected readonly submitting = signal(false);
  protected readonly formError = signal<string | null>(null);

  protected async getExternalId(): Promise<void> {
    this.requestingExternalId.set(true);
    this.formError.set(null);
    try {
      const response: ExternalIdResponse = await this.accounts.requestExternalId();
      this.externalId.set(response.externalId);
      this.templateUrl.set(response.cloudFormationTemplateUrl);
    } catch {
      this.formError.set('Could not generate an ExternalId. Try again.');
    } finally {
      this.requestingExternalId.set(false);
    }
  }

  protected async submit(): Promise<void> {
    this.formError.set(null);
    const regions = this.regionsInput()
      .split(',')
      .map((r) => r.trim())
      .filter((r) => r.length > 0);

    if (this.mode() === ConnectionMode.AssumeRole && !this.externalId()) {
      this.formError.set('Get an ExternalId and deploy the cross-account template first.');
      return;
    }

    this.submitting.set(true);
    try {
      await this.accounts.register({
        alias: this.alias() || undefined,
        connectionMode: this.mode(),
        scanRegions: regions,
        ...(this.mode() === ConnectionMode.AssumeRole
          ? {
              awsAccountId: this.awsAccountId(),
              roleArn: this.roleArn(),
              externalId: this.externalId() ?? undefined,
            }
          : {}),
      });
      this.registered.emit();
    } catch {
      this.formError.set(
        'Registration failed. Confirm the role is deployed correctly and try again.',
      );
    } finally {
      this.submitting.set(false);
    }
  }
}
