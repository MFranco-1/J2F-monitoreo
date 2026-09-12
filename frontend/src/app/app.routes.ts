// app.routes.ts
import { Routes } from '@angular/router';
import { authGuard, adminGuard, activeProfileGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login/login.component').then((m) => m.LoginComponent),
  },
  {
    path: '',
    loadComponent: () =>
      import('./layout/shell/shell.component').then((m) => m.ShellComponent),
    canActivate: [authGuard],
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'alerts',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/alerts/alert-list/alert-list.component').then((m) => m.AlertListComponent),
      },
      {
        path: 'alerts/:id',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/alerts/alert-detail/alert-detail.component').then((m) => m.AlertDetailComponent),
      },
      {
        path: 'assignments',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/assignments/assignment-list/assignment-list.component').then((m) => m.AssignmentListComponent),
      },
      {
        path: 'history',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/history/history-list/history-list.component').then((m) => m.HistoryListComponent),
      },
      {
        path: 'reports',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/reports/report-list/report-list.component').then((m) => m.ReportListComponent),
      },
      {
        path: 'admin/users',
        canActivate: [adminGuard],
        loadComponent: () =>
          import('./features/admin/users/user-list/user-list.component').then((m) => m.UserListComponent),
      },
      {
        path: 'admin/profiles',
        canActivate: [adminGuard],
        loadComponent: () =>
          import('./features/admin/profiles/profile-list/profile-list.component').then((m) => m.ProfileListComponent),
      },
      {
        path: 'master-data',
        canActivate: [activeProfileGuard],
        loadComponent: () =>
          import('./features/admin/master-data/master-data.component').then((m) => m.MasterDataComponent),
      },
      {
        path: 'admin/menu-options',
        canActivate: [adminGuard],
        loadComponent: () =>
          import('./features/admin/menu-options/menu-option-list/menu-option-list.component').then((m) => m.MenuOptionListComponent),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
