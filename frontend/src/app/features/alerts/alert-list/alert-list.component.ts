import { AuthService } from '../../../core/services/auth.service';
// features/alerts/alert-list/alert-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AlertService } from '../../../core/services/alert.service';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Alert, AlertFilters } from '../../../shared/models/alert.model';

@Component({
  selector: 'app-alert-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, TitleCasePipe, FormsModule, RouterLink],
  templateUrl: './alert-list.component.html',
  styleUrl: './alert-list.component.scss',
})
export class AlertListComponent implements OnInit {
  readonly auth = inject(AuthService);
  private alertService = inject(AlertService);
  private assignmentService = inject(AssignmentService);

  alerts = signal<Alert[]>([]);
  loading = signal(true);
  saving = signal(false);
  showNewModal = signal(false);
  successMsg = signal('');
  errorMsg = signal('');
  totalPages = signal(1);

  filters: AlertFilters = { page: 1, per_page: 20 };

  newForm: any = {
    title: '', description: '', priority: 'medium',
    service_type: '', location: '', source: 'Manual',
  };

  ngOnInit(): void { this.loadAlerts(); }

  loadAlerts(): void {
    this.loading.set(true);
    this.alertService.getAlerts(this.filters).subscribe({
      next: ({ alerts, pages }) => {
        this.alerts.set(alerts);
        this.totalPages.set(pages);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.'); },
    });
  }

  applyFilter(field: string, value: string): void {
    (this.filters as any)[field] = value || undefined;
    this.filters.page = 1;
    this.loadAlerts();
  }

  openNewModal(): void {
    this.newForm = { title: '', description: '', priority: 'medium', service_type: '', location: '', source: 'Manual' };
    this.showNewModal.set(true);
  }

  closeNewModal(): void { if (this.saving()) return; this.showNewModal.set(false); this.errorMsg.set(''); }

  createAlert(): void {
    if (this.saving()) return;
    if (!this.newForm.title) { this.errorMsg.set('El título es requerido'); return; }
    this.saving.set(true);
    this.alertService.createAlert(this.newForm).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeNewModal();
        this.loadAlerts();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => { this.saving.set(false); this.errorMsg.set(err?.error?.error || 'Error al crear alerta'); },
    });
  }

  autoAssign(alertId: number): void {
    this.assignmentService.autoAssign(alertId).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.loadAlerts();
        setTimeout(() => this.successMsg.set(''), 4000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error en asignación'),
    });
  }

  getPriorityLabel(p: string): string { return ({ critical: 'Crítica', high: 'Alta', medium: 'Media', low: 'Baja' } as Record<string, string>)[p] || p; }

  getPriorityClass(p: string): string { return `badge-${p}`; }
  getStateClass(stateName: string): string {
    const map: Record<string, string> = {
      'Abierto': 'badge-open', 'En Progreso': 'badge-progress',
      'Cerrado': 'badge-closed', 'Escalado': 'badge-escalated',
    };
    return map[stateName] ?? 'badge-inactive';
  }
  prevPage(): void { if (this.filters.page! > 1) { this.filters.page!--; this.loadAlerts(); } }
  nextPage(): void { if (this.filters.page! < this.totalPages()) { this.filters.page!++; this.loadAlerts(); } }
}
