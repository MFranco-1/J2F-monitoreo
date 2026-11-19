import { Component, Input, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { NgFor, NgIf, NgTemplateOutlet } from '@angular/common';

import { AuthService } from '../../core/services/auth.service';
import { UserService } from '../../core/services/user.service';
import { MenuOption } from '../../shared/models/user.model';
import { merge, of, switchMap, catchError, Subscription } from 'rxjs';

const ICON_PATHS: Record<string, string> = {
  dashboard: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  alerts: 'M12 3 2 21h20L12 3Z M12 9v5 M12 17v1',
  assignments:
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M16 11l2 2 4-4',
  history: 'M3 12a9 9 0 1 0 3-6 M3 3v5h5 M12 7v5l3 2',
  reports: 'M5 3h10l4 4v14H5Z M14 3v5h5 M8 17v-3 M12 17v-6 M16 17v-4',
  users:
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-4',
  profiles: 'M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7Z M8 12l3 3 5-6',
  menu: 'M4 5h16 M4 12h16 M4 19h16',
  folder: 'M3 5h6l2 3h10v12H3Z',
  database: 'M4 5c0-2 16-2 16 0v14c0 2-16 2-16 0Z M4 5c0 2 16 2 16 0 M4 12c0 2 16 2 16 0',
};

interface NavItem {
  label: string;
  icon: string;
  route?: string;
  children?: NavItem[];
  expanded?: boolean;
  disabled?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgFor, NgIf, NgTemplateOutlet],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent implements OnInit, OnDestroy {
  @Input() collapsed = false;

  private auth = inject(AuthService);
  private users = inject(UserService);
  private subscription?: Subscription;
  readonly navSections = signal<NavSection[]>([]);
  private readonly routes = new Set([
    '/dashboard',
    '/alerts',
    '/assignments',
    '/history',
    '/reports',
    '/admin/users',
    '/admin/profiles',
    '/admin/menu-options',
    '/master-data',
  ]);

  readonly iconPaths: Record<string, string> = ICON_PATHS;

  private routeFor(url?: string): string | undefined {
    const value = (url || '').trim();
    const aliases: Record<string, string> = { 'home/Usuarios': '/admin/users' };
    const normalized = value.replace(/^\//, '');
    return aliases[normalized] || (value === '/' || !value ? undefined : '/' + normalized);
  }

  private menuItem(option: MenuOption, depth = 0): NavItem | null {
    if (depth > 20) return null;
    const route = this.routeFor(option.url);
    const children = (option.children || [])
      .map((child) => this.menuItem(child, depth + 1))
      .filter((child): child is NavItem => child !== null);
    if (!this.canUseRoute(route) && !children.length) return null;
    const icon = option.icon && ICON_PATHS[option.icon] ? option.icon : 'folder';
    return {
      label: option.name,
      icon,
      route,
      children: children.length ? children : undefined,
      expanded: true,
      disabled: !route || !this.routes.has(route),
    };
  }

  private canUseRoute(route?: string): boolean {
    if (route?.startsWith('/admin/')) return this.auth.isAdmin();
    if (route === '/reports') return this.auth.hasPermission('reports');
    return true;
  }

  private configuredSections(options: MenuOption[]): NavSection[] {
    return options.map(option => ({
      title: option.name,
      items: (option.children?.length ? option.children : [option])
        .map(child => this.menuItem(child))
        .filter((item): item is NavItem => item !== null),
    })).filter(section => section.items.length > 0);
  }

  ngOnInit(): void {
    this.subscription = merge(of(undefined), this.users.menuChanges, this.auth.profileChanges)
      .pipe(
        switchMap(() => {
          this.navSections.set([]);
          return this.auth.hasActiveProfile()
            ? this.users.getMenuOptions(false, true).pipe(catchError(() => of(null)))
            : of(null);
        }),
      )
      .subscribe((data) => {
        if (!this.auth.hasActiveProfile()) {
          this.navSections.set([]);
          return;
        }
        const configured = data?.configured ?? !!data?.menu_options.length;
        if (!data || !configured) {
          this.navSections.set([]);
          return;
        }
        this.navSections.set(this.configuredSections(data.menu_options));
      });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  toggleExpanded(item: NavItem): void {
    item.expanded = !item.expanded;
  }
}
