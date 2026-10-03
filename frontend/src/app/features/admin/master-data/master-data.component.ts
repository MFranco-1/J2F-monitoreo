import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin, Subscription } from 'rxjs';
import { MasterDataService } from '../../../core/services/master-data.service';
import { UserService } from '../../../core/services/user.service';
import { Client, Vehicle, MasterKind } from '../../../shared/models/master-data.model';
import { State } from '../../../shared/models/user.model';
import { AuthService } from '../../../core/services/auth.service';
import { firstError, validateForm } from '../../../shared/validation';
import { normalizeClientName, phoneCountries, splitClientPhone } from '../../../shared/client-inputs';

@Component({ selector: 'app-master-data', standalone: true, imports: [NgFor, NgIf, FormsModule],
  templateUrl: './master-data.component.html', styleUrl: './master-data.component.scss' })
export class MasterDataComponent implements OnInit, OnDestroy {
  private readonly service = inject(MasterDataService);
  private readonly users = inject(UserService);
  readonly auth = inject(AuthService);
  readonly tabs: { kind: MasterKind; label: string }[] = [
    { kind: 'clients', label: 'Clientes' }, { kind: 'vehicles', label: 'Vehículos' },
    { kind: 'gps-devices', label: 'Dispositivos GPS' }, { kind: 'event-types', label: 'Tipos de evento' },
  ];
  kind: MasterKind = 'clients';
  records = signal<any[]>([]);
  states = signal<State[]>([]);
  clients = signal<Client[]>([]);
  vehicles = signal<Vehicle[]>([]);
  loading = signal(true);
  showModal = signal(false);
  saving = signal(false);
  editing = signal<any | null>(null);
  error = signal('');
  success = signal('');
  form: any = {};
  readonly phoneCountries = phoneCountries();
  fieldErrors = signal<Record<string, string>>({});
  private listRequestId = 0;
  private referenceRequestId = 0;
  private profileSubscription?: Subscription;

  ngOnInit(): void {
    this.profileSubscription = this.auth.profileChanges.subscribe(() => {
      this.showModal.set(false); this.editing.set(null);
      this.listRequestId++; this.referenceRequestId++;
      this.clients.set([]); this.vehicles.set([]); this.records.set([]); this.load();
      if (this.auth.isAdmin()) this.loadReferences();
    });
    // Perfiles y estados administrativos solo son necesarios para el CRUD.
    if (this.auth.isAdmin()) {
      this.users.getProfiles().subscribe({
        next: ({ states }) => this.states.set(states),
        error: err => this.error.set(err?.error?.error || 'No se pudieron cargar los estados administrativos'),
      });
      this.loadReferences();
    }
    this.load();
  }

  select(kind: MasterKind): void {
    if (this.kind === kind) return;
    this.showModal.set(false);
    this.kind = kind;
    this.load();
  }

  load(): void {
    const kind = this.kind;
    const requestId = ++this.listRequestId;
    this.loading.set(true);
    this.error.set('');
    this.service.list<any>(kind).subscribe({
      next: data => {
        if (requestId !== this.listRequestId || kind !== this.kind) return;
        this.records.set(data[kind.replace('-', '_')] || []);
        this.loading.set(false);
      },
      error: err => {
        if (requestId !== this.listRequestId || kind !== this.kind) return;
        this.error.set(err?.error?.error || 'No se pudieron cargar los datos');
        this.loading.set(false);
      },
    });
  }

  loadReferences(): void {
    if (!this.auth.isAdmin()) return;
    const requestId = ++this.referenceRequestId;
    forkJoin({ clients: this.service.clients(false), vehicles: this.service.vehicles(undefined, false) })
      .subscribe({
        next: data => {
          if (requestId !== this.referenceRequestId) return;
          this.clients.set(data.clients['clients'] || []);
          this.vehicles.set(data.vehicles['vehicles'] || []);
        },
        error: err => {
          if (requestId !== this.referenceRequestId) return;
          this.error.set(err?.error?.error || 'No se pudieron cargar las relaciones de datos maestros');
        },
      });
  }

  blank(): any {
    const state_id = this.states().find(state => state.name === 'Activo')?.id;
    return this.kind === 'clients' ? { document_type: 'RUC', document_number: '', business_name: '', contact_name: '', phone_country: 'PE', phone: '', email: '', address: '', state_id } :
      this.kind === 'vehicles' ? { client_id: null, plate: '', brand: '', model: '', color: '', vehicle_type: '', state_id } :
      this.kind === 'gps-devices' ? { vehicle_id: null, imei: '', serial_number: '', model: '', provider: '', sim_number: '', state_id } :
      { code: '', name: '', description: '', default_priority: 'medium', generates_alert: true, expected_action: '', state_id };
  }

  open(record: any = null): void {
    if (!this.auth.isAdmin()) return;
    this.editing.set(record);
    this.form = record ? { ...record } : { ...this.blank() };
    if (this.kind === 'clients' && record) Object.assign(this.form, splitClientPhone(record.phone, record.phone_country));
    this.error.set('');
    this.fieldErrors.set({});
    this.showModal.set(true);
  }
  close(): void { if (!this.saving()) this.showModal.set(false); }
  ngOnDestroy(): void {
    this.profileSubscription?.unsubscribe();
    this.listRequestId++; this.referenceRequestId++;
  }
  registerGps(vehicle: Vehicle): void {
    if (!this.auth.isAdmin()) return;
    // Puede haberse registrado en otro navegador después de cargar referencias.
    if (!this.vehicles().some(item => item.id === vehicle.id)) this.vehicles.update(items => [...items, vehicle]);
    this.select('gps-devices'); this.open(); this.form.vehicle_id = vehicle.id;
  }
  gpsLabel(vehicle: Vehicle): string {
    const devices = vehicle.gps_devices || [];
    return devices.length ? devices.map(device => `${device.serial_number || device.imei} (${device.state?.name || 'Sin estado'})`).join(', ') : 'Sin GPS registrado';
  }
  normalizeName(field: 'business_name' | 'contact_name'): void {
    if (typeof this.form[field] === 'string') this.form[field] = normalizeClientName(this.form[field]);
  }
  save(): void {
    if (!this.auth.isAdmin() || this.saving()) return;
    this.fieldErrors.set(validateForm(this.kind, this.form, !!this.editing()));
    const error = firstError(this.fieldErrors());
    if (error) { this.error.set(error); return; }
    if (this.kind === 'clients') {
      this.normalizeName('business_name'); this.normalizeName('contact_name');
    }
    const data = { ...this.form };
    delete data.verification; delete data.verification_json;
    this.saving.set(true);
    const item = this.editing();
    const request = item ? this.service.update(this.kind, item.id, data) : this.service.create(this.kind, data);
    request.subscribe({
      next: response => {
        this.saving.set(false);
        this.success.set(response.message);
        this.showModal.set(false);
        this.loadReferences();
        this.load();
        setTimeout(() => this.success.set(''), 3000);
      },
      error: err => { this.saving.set(false); this.error.set(err?.error?.error || 'No se pudo guardar'); },
    });
  }
  remove(record: any): void {
    if (!this.auth.isAdmin() || !confirm('¿Eliminar este registro? Si tiene relaciones, deberá cambiarlo a Inactivo.')) return;
    this.service.delete(this.kind, record.id).subscribe({
      next: response => { this.success.set(response.message); this.loadReferences(); this.load(); },
      error: err => this.error.set(err?.error?.error || 'No se pudo eliminar'),
    });
  }
  title(record: any): string { return this.kind === 'gps-devices' ? record.serial_number || record.imei : record.business_name || record.plate || record.name; }
  detail(record: any): string {
    if (this.kind === 'gps-devices') return [record.model, record.imei ? `IMEI ${record.imei}` : ''].filter(Boolean).join(' · ');
    return this.kind === 'event-types' ? record.description || record.name :
      record.document_number || [record.brand, record.model].filter(Boolean).join(' ') || record.serial_number || record.code;
  }
}
