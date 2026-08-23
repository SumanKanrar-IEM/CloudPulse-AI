import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AccountsService as GeneratedAccountsService,
  Account,
  AccountCreate,
  ExternalIdResponse,
} from '../../api';

/**
 * Signal-based state wrapper around the generated `AccountsService` (spec 002).
 *
 * No hand-written HTTP calls here -- every request goes through the generated
 * client (Principle V, plan.md's "Generated-client wrapper, no hand-written API
 * calls"). This class only owns component-facing state (the current list, loading,
 * and the last error) so `accounts-list.component.ts` and `account-form.component.ts`
 * do not each duplicate that bookkeeping.
 */
@Injectable({ providedIn: 'root' })
export class AccountsService {
  private readonly api = inject(GeneratedAccountsService);

  private readonly accountsState = signal<Account[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly accounts = this.accountsState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const result = await firstValueFrom(this.api.listAccounts());
      this.accountsState.set(result.accounts);
    } catch {
      this.errorState.set('Could not load accounts. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  /** FR-003a: a fresh, platform-generated ExternalId ahead of cross-account registration. */
  async requestExternalId(): Promise<ExternalIdResponse> {
    return firstValueFrom(this.api.generateExternalId());
  }

  async register(body: AccountCreate): Promise<Account> {
    const account = await firstValueFrom(this.api.registerAccount(body));
    await this.refresh();
    return account;
  }

  async deactivate(accountId: string): Promise<void> {
    await firstValueFrom(this.api.deactivateAccount(accountId));
    await this.refresh();
  }

  async reactivate(accountId: string): Promise<void> {
    await firstValueFrom(this.api.reactivateAccount(accountId));
    await this.refresh();
  }
}
