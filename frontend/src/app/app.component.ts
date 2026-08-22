import { Component } from '@angular/core';
import { ShellComponent } from './shared/shell.component';

/**
 * Root component. Delegates to the shell, which carries the FR-047a accessibility
 * baseline that every screen added by specs 002-005 inherits.
 */
@Component({
  selector: 'cp-root',
  standalone: true,
  imports: [ShellComponent],
  template: `<cp-shell />`,
})
export class AppComponent {}
