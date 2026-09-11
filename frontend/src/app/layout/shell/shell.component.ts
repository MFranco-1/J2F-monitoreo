// layout/shell/shell.component.ts
import { Component, signal, computed, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { SidebarComponent } from '../sidebar/sidebar.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, SidebarComponent],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  readonly authService = inject(AuthService);
  protected sidebarCollapsed = signal(window.innerWidth < 900);

  protected userInitials = computed(() => {
    const name = this.authService.currentUser()?.full_name ?? '';
    return name
      .split(' ')
      .slice(0, 2)
      .map((n) => n[0]?.toUpperCase() ?? '')
      .join('');
  });

  protected toggleSidebar(): void {
    this.sidebarCollapsed.update((v) => !v);
  }

  protected logout(): void {
    this.authService.logout();
  }
}
