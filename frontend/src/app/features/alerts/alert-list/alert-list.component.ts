import { AuthService } from '../../../core/services/auth.service';
// features/alerts/alert-list/alert-list.component.ts
import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { interval, Subscription } from 'rxjs';
import { NgFor, NgIf, DatePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AlertService } from '../../../core/services/alert.service';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Alert, AlertFilters } from '../../../shared/models/alert.model';
import { MasterDataService } from '../../../core/services/master-data.service';
import { Client, Vehicle, GpsDevice, EventType } from '../../../shared/models/master-data.model';
import { firstError, validateForm } from '../../../shared/validation';

@Component({
  selector: 'app-alert-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, TitleCasePipe, FormsModule, RouterLink],
  templateUrl: './alert-list.component.html',
  styleUrl: './alert-list.component.scss',
})
export class AlertListComponent implements OnInit, OnDestroy {
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
  loadingTechnicians = signal(false);
  technicianError = signal('');
  assignmentAlert = signal<Alert | null>(null);
  assignmentForm = { user_id: null as number | null, notes: '' };
  private alertRequestId = 0;
  private formVehicleRequestId = 0;
  private filterVehicleRequestId = 0;
  private deviceRequestId = 0;
  private technicianRequestId = 0;
  private technicianRequest?: Subscription;
  private workloadPolling?: Subscription;
  private profileSubscription?: Subscription;

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
    this.loadTechnicians();
    this.workloadPolling = interval(5000).subscribe(() => {
      if (this.showAssignmentModal() && !this.loadingTechnicians()) this.loadTechnicians();
    });
    this.profileSubscription = this.auth.profileChanges.subscribe(() => {
      this.showAssignmentModal.set(false); this.assignmentAlert.set(null);
      this.technicians.set([]); this.loadTechnicians();
      this.loadAlerts();
    });
  }

  ngOnDestroy(): void {
    this.workloadPolling?.unsubscribe(); this.profileSubscription?.unsubscribe();
    this.technicianRequest?.unsubscribe(); this.technicianRequestId++;
    this.alertRequestId++; this.formVehicleRequestId++; this.filterVehicleRequestId++; this.deviceRequestId++;
  }

  loadTechnicians(): void {
    const requestId = ++this.technicianRequestId;
    this.technicianRequest?.unsubscribe();
    this.technicianError.set('');
    if (!this.auth.canAssign()) { this.technicians.set([]); this.loadingTechnicians.set(false); return; }
    this.loadingTechnicians.set(true);
    this.technicianRequest = this.assignmentService.getTechnicians().subscribe({
      next: data => {
        if (requestId !== this.technicianRequestId || !this.auth.canAssign()) return;
        this.technicians.set(data.technicians || []); this.loadingTechnicians.set(false);
      },
      error: err => {
        if (requestId !== this.technicianRequestId) return;
        this.loadingTechnicians.set(false); this.technicians.set([]);
        this.technicianError.set(err?.error?.error || 'No se pudo actualizar la carga de técnicos. Vuelve a abrir la asignación para reintentar.');
      },
    });
  }

  loadAlerts(): void {
    const requestId = ++this.alertRequestId;
    this.loading.set(true);
    this.alertService.getAlerts(this.filters).subscribe({
      next: ({ alerts, pages }) => {
        if (requestId !== this.alertRequestId) return;
        this.alerts.set(alerts);
        this.totalPages.set(pages);
        this.loading.set(false);
      },
      error: (err) => {
        if (requestId !== this.alertRequestId) return;
        this.loading.set(false);
        this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.');
      },
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
    const error = firstError(validateForm('alerts', this.newForm));
    if (error) { this.errorMsg.set(error); return; }
    if (this.isLowFuelSelected()) {
      const vehicle = this.formVehicles().find(item => item.id === this.newForm.vehicle_id);
      if (!this.newForm.client_id || !vehicle || vehicle.client_id !== this.newForm.client_id) {
        this.errorMsg.set('Combustible bajo requiere seleccionar un cliente y un vehículo válido de ese cliente');
        return;
      }
    }
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
    const requestId = ++this.formVehicleRequestId;
    ++this.deviceRequestId;
    this.newForm.vehicle_id = null; this.newForm.gps_device_id = null; this.devices.set([]);
    if (!this.newForm.client_id) { this.formVehicles.set([]); return; }
    const clientId = this.newForm.client_id;
    this.masterData.vehicles(clientId, true).subscribe({
      next: data => {
        if (requestId !== this.formVehicleRequestId || this.newForm.client_id !== clientId) return;
        this.formVehicles.set(data['vehicles'] || []);
      },
      error: err => {
        if (requestId !== this.formVehicleRequestId || this.newForm.client_id !== clientId) return;
        this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los vehículos del cliente');
      },
    });
  }

  onFilterClientChange(value: number | null): void {
    const requestId = ++this.filterVehicleRequestId;
    const clientId = value || undefined;
    this.filters.client_id = clientId;
    this.filters.vehicle_id = undefined;
    this.filters.page = 1;
    this.filterVehicles.set([]);
    if (clientId) {
      this.masterData.vehicles(clientId, true).subscribe({
        next: data => {
          if (requestId !== this.filterVehicleRequestId || this.filters.client_id !== clientId) return;
          this.filterVehicles.set(data['vehicles'] || []);
        },
        error: err => {
          if (requestId !== this.filterVehicleRequestId || this.filters.client_id !== clientId) return;
          this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los vehículos del filtro');
        },
      });
    }
    this.loadAlerts();
  }

  onFilterVehicleChange(value: number | null): void {
    this.filters.vehicle_id = value || undefined;
    this.filters.page = 1;
    this.loadAlerts();
  }

  onVehicleChange(): void {
    const requestId = ++this.deviceRequestId;
    this.newForm.gps_device_id = null;
    if (!this.newForm.vehicle_id) { this.devices.set([]); return; }
    const vehicleId = this.newForm.vehicle_id;
    this.masterData.devices(vehicleId, true).subscribe({ next: data => {
      if (requestId !== this.deviceRequestId || this.newForm.vehicle_id !== vehicleId) return;
      const devices = data['gps_devices'] || []; this.devices.set(devices);
      if (devices.length === 1) this.newForm.gps_device_id = devices[0].id;
    }, error: err => {
      if (requestId !== this.deviceRequestId || this.newForm.vehicle_id !== vehicleId) return;
      this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los dispositivos del vehículo');
    } });
  }

  onEventTypeChange(): void {
    const event = this.eventTypes().find(item => item.id === this.newForm.event_type_id);
    if (event) this.newForm.priority = event.default_priority;
  }

  isLowFuelSelected(): boolean {
    return this.eventTypes().find(item => item.id === this.newForm.event_type_id)?.code === 'LOW_FUEL';
  }

  autoAssign(alertId: number): void {
    if (!this.auth.canAssign()) return;
    this.assignmentService.autoAssign(alertId).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.loadAlerts();
        this.loadTechnicians();
        setTimeout(() => this.successMsg.set(''), 4000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error en asignación'),
    });
  }

  openAssignmentModal(alert: Alert): void {
    if (!this.auth.canAssign() || ['Cerrado', 'Anulado'].includes(alert.state?.name || '')) return;
    this.assignmentAlert.set(alert);
    this.assignmentForm = { user_id: alert.current_assignee?.id ?? null, notes: '' };
    this.errorMsg.set('');
    this.showAssignmentModal.set(true);
    this.loadTechnicians();
  }

  closeAssignmentModal(): void {
    if (this.saving()) return;
    this.showAssignmentModal.set(false);
    this.assignmentAlert.set(null);
    this.errorMsg.set('');
  }

  assignTechnician(): void {
    const alert = this.assignmentAlert();
    if (!this.auth.canAssign() || !alert || !this.assignmentForm.user_id || this.saving() || this.loadingTechnicians() || this.technicianError()) {
      this.errorMsg.set('Selecciona un técnico');
      return;
    }
    const error = firstError(validateForm('assignment', this.assignmentForm));
    if (error) { this.errorMsg.set(error); return; }
    this.saving.set(true);
    this.assignmentService.createAssignment(alert.id, this.assignmentForm.user_id, this.assignmentForm.notes).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeAssignmentModal();
        this.loadAlerts();
        this.loadTechnicians();
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
