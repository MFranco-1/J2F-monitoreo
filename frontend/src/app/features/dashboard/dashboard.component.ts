// features/dashboard/dashboard.component.ts
import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { interval, Subscription, switchMap, startWith, catchError, EMPTY } from 'rxjs';
import { AlertService } from '../../core/services/alert.service';
import { AlertMetrics, Alert } from '../../shared/models/alert.model';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, DatePipe, RouterLink],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private alertService = inject(AlertService);
  private pollSub?: Subscription;

  metrics = signal<AlertMetrics | null>(null);
  loading = signal(true);
  connectionError = signal(false);
  lastUpdate = signal<Date>(new Date());

  // Datos para representación visual de barras
  stateColors: Record<string, string> = {
    'Abierto': '#2563eb',
    'En Progreso': '#f97316',
    'Cerrado': '#22c55e',
    'Escalado': '#a855f7',
  };

  priorityLabels: Record<string, string> = {
    critical: ' Crítica',
    high: ' Alta',
    medium: ' Media',
    low: ' Baja',
  };

  ngOnInit(): void {
    // Polling cada 30 segundos
    this.pollSub = interval(30_000)
      .pipe(
        startWith(0),
        switchMap(() => this.alertService.getMetrics().pipe(catchError(() => {
          this.loading.set(false);
          this.connectionError.set(true);
          return EMPTY;
        }))),
      )
      .subscribe({
        next: (data) => {
          this.connectionError.set(false);
          this.metrics.set(data);
          this.loading.set(false);
          this.lastUpdate.set(new Date());
        },
        error: () => this.loading.set(false),
      });
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  getStateEntries(): { name: string; count: number; color: string; pct: number }[] {
    const m = this.metrics();
    if (!m) return [];
    const total = m.total_alerts || 1;
    return Object.entries(m.by_state).map(([name, count]) => ({
      name,
      count,
      color: this.stateColors[name] ?? '#8b949e',
      pct: Math.round((count / total) * 100),
    }));
  }

  getPriorityLabel(p: string): string {
    return this.priorityLabels[p] ?? p;
  }

  getPriorityClass(p: string): string {
    return `badge-${p}`;
  }
}
