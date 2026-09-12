import { AuthService } from '../../../core/services/auth.service';
// features/alerts/alert-list/alert-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AlertService } from '../../../core/services/alert.service';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Alert, AlertFilters } from '../../../shared/models/alert.model';
import { MasterDataService } from '../../../core/services/master-data.service';
import { Client, Vehicle, GpsDevice, EventType } from '../../../shared/models/master-data.model';

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
  private masterData = inject(MasterDataService);

  alerts = signal<Alert[]>([]);
  loading = signal(true);
  saving = signal(false);
  showNewModal = signal(false);
  showAssignmentModal = signal(false);
  successMsg = signal('');
  errorMsg = signal('');
  totalPages = signal(1);
  clients = signal<Client[]>([]);
  filterVehicles = signal<Vehicle[]>([]);
  formVehicles = signal<Vehicle[]>([]);
  devices = signal<GpsDevice[]>([]);
  eventTypes = signal<EventType[]>([]);
  technicians = signal<{ id: number; full_name: string; active_assignments_count: number }[]>([]);
  assignmentAlert = signal<Alert | null>(null);
  assignmentForm = { user_id: null as number | null, notes: '' };

  filters: AlertFilters = { page: 1, per_page: 20 };

  newForm: any = {
    title: '', description: '', priority: 'medium',
    service_type: '', location: '', source: 'Manual', client_id: null,
    vehicle_id: null, gps_device_id: null, event_type_id: null,
  };

  ngOnInit(): void {
    this.loadAlerts();
    this.masterData.clients(true).subscribe(data => this.clients.set(data['clients'] || []));
    this.masterData.eventTypes(true).subscribe(data => this.eventTypes.set(
      (data['event_types'] || []).filter(item => item.generates_alert)));
    if (this.auth.canAssign()) {
      this.assignmentService.getTechnicians().subscribe({
        next: data => this.technicians.set(data.technicians || []),
        error: () => this.technicians.set([]),
      });
    }
  }

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
    this.newForm = { title: '', description: '', priority: 'medium', service_type: '', location: '', source: 'Manual',
      client_id: null, vehicle_id: null, gps_device_id: null, event_type_id: null };
    this.formVehicles.set([]); this.devices.set([]);
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

  onClientChange(): void {
    this.newForm.vehicle_id = null; this.newForm.gps_device_id = null; this.devices.set([]);
    if (!this.newForm.client_id) { this.formVehicles.set([]); return; }
    this.masterData.vehicles(this.newForm.client_id, true).subscribe(data => this.formVehicles.set(data['vehicles'] || []));
  }

  onFilterClientChange(value: number | null): void {
    const clientId = value || undefined;
    this.filters.client_id = clientId;
    this.filters.vehicle_id = undefined;
    this.filters.page = 1;
    this.filterVehicles.set([]);
    if (clientId) {
      this.masterData.vehicles(clientId, true).subscribe(data =>
        this.filterVehicles.set(data['vehicles'] || []));
    }
    this.loadAlerts();
  }

  onFilterVehicleChange(value: number | null): void {
    this.filters.vehicle_id = value || undefined;
    this.filters.page = 1;
    this.loadAlerts();
  }

  onVehicleChange(): void {
    this.newForm.gps_device_id = null;
    if (!this.newForm.vehicle_id) { this.devices.set([]); return; }
    this.masterData.devices(this.newForm.vehicle_id, true).subscribe(data => {
      const devices = data['gps_devices'] || []; this.devices.set(devices);
      if (devices.length === 1) this.newForm.gps_device_id = devices[0].id;
    });
  }

  onEventTypeChange(): void {
    const event = this.eventTypes().find(item => item.id === this.newForm.event_type_id);
    if (event) this.newForm.priority = event.default_priority;
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

  openAssignmentModal(alert: Alert): void {
    this.assignmentAlert.set(alert);
    this.assignmentForm = { user_id: alert.current_assignee?.id ?? null, notes: '' };
    this.errorMsg.set('');
    this.showAssignmentModal.set(true);
  }

  closeAssignmentModal(): void {
    if (this.saving()) return;
    this.showAssignmentModal.set(false);
    this.assignmentAlert.set(null);
    this.errorMsg.set('');
  }

  assignTechnician(): void {
    const alert = this.assignmentAlert();
    if (!alert || !this.assignmentForm.user_id || this.saving()) {
      this.errorMsg.set('Selecciona un técnico');
      return;
    }
    this.saving.set(true);
    this.assignmentService.createAssignment(alert.id, this.assignmentForm.user_id, this.assignmentForm.notes).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeAssignmentModal();
        this.loadAlerts();
        setTimeout(() => this.successMsg.set(''), 4000);
      },
      error: err => {
        this.saving.set(false);
        this.errorMsg.set(err?.error?.error || 'Error al asignar la alerta');
      },
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
