import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { NgFor, NgIf, DecimalPipe, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { interval, Subscription, switchMap, startWith, catchError, EMPTY } from 'rxjs';
import { AlertService } from '../../core/services/alert.service';
import { AuthService } from '../../core/services/auth.service';
import { AlertMetrics } from '../../shared/models/alert.model';
import { VehicleMapComponent } from './vehicle-map.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, DatePipe, FormsModule, RouterLink, VehicleMapComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private alertService = inject(AlertService);
  readonly auth = inject(AuthService);
  private pollSub?: Subscription;
  private refreshRequest?: Subscription;
  private metricsVersion = 0;
  metrics = signal<AlertMetrics | null>(null);
  loading = signal(false);
  selectingProfile = signal(false);
  selectionError = signal('');
  connectionError = signal(false);
  lastUpdate = signal<Date>(new Date());
  selectedProfileId: number | null = null;

  private readonly stateColors: Record<string, string> = {
    Abierto: 'var(--state-open)',
    'En Progreso': 'var(--state-progress)',
    Cerrado: 'var(--state-closed)',
    Escalado: 'var(--state-escalated)',
  };

  ngOnInit(): void {
    this.selectedProfileId = this.auth.currentUser()?.profile?.id || null;
    if (this.auth.hasActiveProfile()) this.startMetrics();
  }

  private startMetrics(): void {
    this.metricsVersion++;
    this.pollSub?.unsubscribe();
    this.refreshRequest?.unsubscribe();
    this.loading.set(true);
    this.metrics.set(null);
    this.pollSub = interval(30_000)
      .pipe(
        startWith(0),
        switchMap(() =>
          this.alertService.getMetrics().pipe(
            catchError(() => {
              this.loading.set(false);
              this.connectionError.set(true);
              return EMPTY;
            }),
          ),
        ),
      )
      .subscribe((data) => {
        this.connectionError.set(false);
        this.metrics.set(data);
        this.loading.set(false);
        this.lastUpdate.set(new Date());
      });
  }

  refreshMetrics(): void {
    if (!this.auth.hasActiveProfile()) return;
    this.refreshRequest?.unsubscribe();
    const version = this.metricsVersion;
    this.refreshRequest = this.alertService.getMetrics().subscribe({
      next: (data) => {
        if (version !== this.metricsVersion) return;
        this.metrics.set(data);
        this.connectionError.set(false);
        this.lastUpdate.set(new Date());
      },
      error: () => {
        if (version === this.metricsVersion) this.connectionError.set(true);
      },
    });
  }

  onProfileChange(): void {
    if (!this.selectedProfileId || this.selectingProfile()) return;
    this.selectingProfile.set(true);
    this.selectionError.set('');
    this.auth.selectProfile(this.selectedProfileId).subscribe({
      next: () => {
        this.selectingProfile.set(false);
        this.startMetrics();
      },
      error: (err) => {
        this.selectingProfile.set(false);
        this.selectedProfileId = null;
        this.selectionError.set(err?.error?.error || 'No se pudo seleccionar el perfil');
      },
    });
  }

  ngOnDestroy(): void {
    this.metricsVersion++;
    this.pollSub?.unsubscribe();
    this.refreshRequest?.unsubscribe();
  }

  getStateEntries(): { name: string; count: number; color: string; pct: number }[] {
    const data = this.metrics();
    if (!data) return [];
    const total = data.total_alerts || 1;
    return Object.entries(data.by_state).map(([name, count]) => ({
      name,
      count,
      color: this.stateColors[name] ?? 'var(--state-unknown)',
      pct: Math.round((count / total) * 100),
    }));
  }
}
