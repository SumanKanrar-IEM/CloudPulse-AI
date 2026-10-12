import { Component, inject } from '@angular/core';
import { SdasService } from './sdas.service';

/**
 * The "No SDA" bucket triage view (FR-009, FR-012) -- resources not matched
 * to any registered SDA. Read-only; a resource leaves this list only by
 * matching a registered SDA on the next scan (FR-008/FR-010), never by an
 * action taken here.
 */
@Component({
  selector: 'cp-no-sda-triage',
  standalone: true,
  template: `
    <h2>"No SDA" bucket</h2>
    <p>Resources not matched to any registered SDA.</p>

    @if (sdas.unmatched().length === 0 && !sdas.loading()) {
      <p>Every resource is matched to an SDA.</p>
    }

    @if (sdas.unmatched().length > 0) {
      <table>
        <caption class="visually-hidden">Resources not matched to any SDA</caption>
        <thead>
          <tr>
            <th scope="col">Resource type</th>
            <th scope="col">ARN</th>
            <th scope="col">Region</th>
          </tr>
        </thead>
        <tbody>
          @for (resource of sdas.unmatched(); track resource.id) {
            <tr>
              <td>{{ resource.resourceType }}</td>
              <td>{{ resource.arn }}</td>
              <td>{{ resource.region }}</td>
            </tr>
          }
        </tbody>
      </table>
    }
  `,
})
export class NoSdaTriageComponent {
  protected readonly sdas = inject(SdasService);
}
