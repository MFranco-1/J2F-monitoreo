// layout/sidebar/sidebar.component.ts
import { Component, Input, OnInit, OnDestroy, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { NgFor, NgClass, NgIf, NgTemplateOutlet } from '@angular/common';

import { AuthService } from '../../core/services/auth.service';
import { UserService } from '../../core/services/user.service';
import { MenuOption } from '../../shared/models/user.model';
import { merge, of, switchMap, catchError, Subscription } from 'rxjs';

const ICON_PATHS: Record<string, string> = {"dashboard": "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z", "alerts": "M12 3 2 21h20L12 3Z M12 9v5 M12 17v1", "assignments": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M16 11l2 2 4-4", "history": "M3 12a9 9 0 1 0 3-6 M3 3v5h5 M12 7v5l3 2", "reports": "M5 3h10l4 4v14H5Z M14 3v5h5 M8 17v-3 M12 17v-6 M16 17v-4", "users": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-4", "profiles": "M12 3 3 7v5c0 5 9 10 9 10s9-5 9-10V7Z M8 12l3 3 5-6", "menu": "M4 5h16 M4 12h16 M4 19h16", "folder": "M3 5h6l2 3h10v12H3Z", "database": "M4 5c0-2 16-2 16 0v14c0 2-16 2-16 0Z M4 5c0 2 16 2 16 0 M4 12c0 2 16 2 16 0"};

interface NavItem {
  label: string;
  icon: string;
  route?: string;
  children?: NavItem[];
  expanded?: boolean;
  disabled?: boolean;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgFor, NgClass, NgIf, NgTemplateOutlet],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent implements OnInit, OnDestroy {
  @Input() collapsed = false;

  private readonly defaultSections: { title: string; items: NavItem[] }[] = [
    { title: 'MONITOREO', items: [
      { label: 'Panel de control', icon: 'dashboard', route: '/dashboard' },
      { label: 'Alertas', icon: 'alerts', route: '/alerts' },
      { label: 'Asignaciones', icon: 'assignments', route: '/assignments' }
    ] },
    { title: 'SEGUIMIENTO', items: [
      { label: 'Historial', icon: 'history', route: '/history' },
      { label: 'Reportes', icon: 'reports', route: '/reports' }
    ] },
    { title: 'ADMINISTRACIÓN', items: [
      { label: 'Usuarios', icon: 'users', route: '/admin/users' },
      { label: 'Perfiles', icon: 'profiles', route: '/admin/profiles' },
      { label: 'Opciones de menú', icon: 'menu', route: '/admin/menu-options' },
      { label: 'Datos maestros', icon: 'database', route: '/master-data' }
    ] }
  ];

  private auth = inject(AuthService);
  private users = inject(UserService);
  private subscription?: Subscription;
  navSections: { title: string; items: NavItem[] }[] = [];
  private readonly routes = new Set(['/dashboard', '/alerts', '/assignments', '/history', '/reports',
    '/admin/users', '/admin/profiles', '/admin/menu-options', '/master-data']);

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
    const children = (option.children || []).map(child => this.menuItem(child, depth + 1))
      .filter((child): child is NavItem => child !== null);
    if (!this.auth.isAdmin() && route?.startsWith('/admin/') && !children.length) return null;
    const icon = option.icon && ICON_PATHS[option.icon] ? option.icon : 'folder';
    return { label: option.name, icon, route, children: children.length ? children : undefined,
      expanded: true, disabled: !route || !this.routes.has(route) };
  }

  private fallbackSections(): { title: string; items: NavItem[] }[] {
    return this.defaultSections
      .filter(section => this.auth.isAdmin() || section.title !== 'ADMINISTRACIÓN')
      .map(section => ({ ...section, items: section.items.map(item => ({ ...item })) }));
  }

  private configuredSections(options: MenuOption[]): { title: string; items: NavItem[] }[] {
    const sections: { title: string; items: NavItem[] }[] = [];
    const standalone = new Map<string, NavItem[]>([
      ['MONITOREO', []], ['SEGUIMIENTO', []], ['ADMINISTRACIÓN', []]
    ]);
    for (const option of options) {
      if (!this.routeFor(option.url)) {
        const items = (option.children || []).map(child => this.menuItem(child))
          .filter((item): item is NavItem => item !== null);
        if (items.length) sections.push({ title: option.name, items });
        continue;
      }
      const item = this.menuItem(option);
      if (item) {
        const route = item.route || '';
        const title = ['/dashboard', '/alerts', '/assignments'].includes(route) ? 'MONITOREO'
          : ['/history', '/reports'].includes(route) ? 'SEGUIMIENTO'
          : 'ADMINISTRACIÓN';
        standalone.get(title)?.push(item);
      }
    }
    for (const [title, items] of standalone) {
      if (!items.length) continue;
      const existing = sections.find(section => section.title === title);
      if (existing) existing.items.push(...items);
      else sections.push({ title, items });
    }
    return sections;
  }

  ngOnInit(): void {
    this.subscription = merge(of(undefined), this.users.menuChanges, this.auth.profileChanges).pipe(
      switchMap(() => this.auth.hasActiveProfile()
        ? this.users.getMenuOptions(false, true).pipe(catchError(() => of(null)))
        : of(null))
    ).subscribe(data => {
      if (!this.auth.hasActiveProfile()) { this.navSections = []; return; }
      const configured = data?.configured ?? !!data?.menu_options.length;
      if (!data || !configured) {
        this.navSections = this.fallbackSections();
        return;
      }
      this.navSections = this.configuredSections(data.menu_options);
    });
  }

  ngOnDestroy(): void { this.subscription?.unsubscribe(); }

  toggleExpanded(item: NavItem): void {
    item.expanded = !item.expanded;
  }
}
