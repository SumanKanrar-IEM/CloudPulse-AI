import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  SdasService as GeneratedSdasService,
  Sda,
  SdaCreate,
  SdaUpdate,
  ResourceSummary,
} from '../../api';

/**
 * Signal-based state wrapper around the generated `SdasService` (spec 003).
 *
 * No hand-written HTTP calls here -- every request goes through the generated
 * client (Principle V), matching `accounts.service.ts`'s established pattern.
 */
@Injectable({ providedIn: 'root' })
export class SdasService {
  private readonly api = inject(GeneratedSdasService);

  private readonly sdasState = signal<Sda[]>([]);
  private readonly unmatchedState = signal<ResourceSummary[]>([]);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly sdas = this.sdasState.asReadonly();
  readonly unmatched = this.unmatchedState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  async refresh(): Promise<void> {
    this.loadingState.set(true);
    this.errorState.set(null);
    try {
      const [sdas, unmatched] = await Promise.all([
        firstValueFrom(this.api.listSdas()),
        firstValueFrom(this.api.listUnmatchedResources()),
      ]);
      this.sdasState.set(sdas.sdas);
      this.unmatchedState.set(unmatched.resources);
    } catch {
      this.errorState.set('Could not load SDAs. Try again.');
    } finally {
      this.loadingState.set(false);
    }
  }

  async register(body: SdaCreate): Promise<Sda> {
    const sda = await firstValueFrom(this.api.registerSda(body));
    await this.refresh();
    return sda;
  }

  async update(sdaId: string, body: SdaUpdate): Promise<Sda> {
    const sda = await firstValueFrom(this.api.updateSda(sdaId, body));
    await this.refresh();
    return sda;
  }

  async remove(sdaId: string): Promise<void> {
    await firstValueFrom(this.api.removeSda(sdaId));
    await this.refresh();
  }
}
