import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, Subscription } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { environment } from '../../../environments/environment';

interface Contract {
  plan: string;
  service_start: string;
  first_period: string;
  equipment_paid: boolean;
}
interface Catalog {
  clients: { id: number; name: string }[];
  vehicles: { id: number; client_id: number; plate: string; contract: Contract | null }[];
}
interface Invoice {
  id?: number;
  number?: string;
  signature?: string;
  status?: string;
  message?: string;
  sunat_status?: string;
  external_id?: number;
  missing?: string[];
  total: number;
  lines: { plate: string; label: string; period: string; gross: number }[];
}

@Component({
  selector: 'app-billing',
  standalone: true,
  imports: [FormsModule, DecimalPipe],
  templateUrl: './billing.component.html',
  styleUrl: './billing.component.scss',
})
export class BillingComponent implements OnInit, OnDestroy {
  private http = inject(HttpClient);
  private auth = inject(AuthService);
  private router = inject(Router);
  private base = environment.apiUrl + '/billing';
  private pending?: Subscription;
  private profile?: Subscription;
  readonly catalog = signal<Catalog>({ clients: [], vehicles: [] });
  readonly invoice = signal<Invoice | null>(null);
  readonly busy = signal(false);
  readonly message = signal('');
  readonly states: Record<string, string> = {
    reserved: 'Pendiente de creación',
    creating: 'Creación en curso',
    uncertain: 'Creación por verificar',
    created: 'Creada, pendiente de envío',
    sending: 'Envío en curso',
    accepted: 'Aceptada',
    rejected: 'Envío rechazado',
    send_unknown: 'Respuesta SUNAT por verificar',
    mismatch: 'Requiere revisión',
  };
  client: number | null = null;
  vehicle: number | null = null;
  period = this.currentMonth();
  plan = 'monthly';
  start = '';
  first = this.currentMonth();
  paid = false;

  private currentMonth() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }

  ngOnInit() {
    this.load();
    this.profile = this.auth.profileChanges.subscribe(() => {
      this.pending?.unsubscribe();
      this.catalog.set({ clients: [], vehicles: [] });
      this.client = this.vehicle = null;
      this.clear();
      if (this.auth.hasPermission('billing')) this.load();
      else void this.router.navigateByUrl('/dashboard');
    });
  }
  ngOnDestroy() {
    this.profile?.unsubscribe();
    this.pending?.unsubscribe();
  }

  private run<T>(req: Observable<T>, onSuccess: (r: T) => void) {
    this.pending?.unsubscribe();
    this.busy.set(true);
    this.message.set('');
    this.pending = req.subscribe({
      next: (r) => {
        this.busy.set(false);
        onSuccess(r);
      },
      error: (e) => {
        this.busy.set(false);
        this.message.set(e.error?.error || 'No se completó la operación. Consulta el período.');
      },
    });
  }
  load(feedback = '') {
    this.run(this.http.get<Catalog>(this.base + '/catalog'), (r) => {
      this.catalog.set(r);
      this.message.set(feedback);
    });
  }
  clear() {
    this.invoice.set(null);
    this.message.set('');
  }
  changeClient() {
    this.vehicle = null;
    this.editPlan();
  }
  editPlan() {
    this.clear();
    const c = this.catalog().vehicles.find((v) => v.id === this.vehicle)?.contract;
    this.plan = c?.plan || 'monthly';
    this.start = c?.service_start || '';
    this.first = c?.first_period.slice(0, 7) || this.currentMonth();
    this.paid = c?.equipment_paid || false;
  }
  savePlan() {
    if (this.busy() || !this.vehicle) return;
    this.clear();
    this.run(
      this.http.put(this.base + '/plans/' + this.vehicle, {
        plan: this.plan,
        service_start: this.start,
        first_period: this.first,
        equipment_paid: this.plan === 'monthly' && this.paid,
      }),
      () => this.load('Plan guardado.'),
    );
  }
  preview() {
    if (this.busy() || !this.client) return;
    this.clear();
    this.run(
      this.http.get<Invoice>(this.base + '/preview', {
        params: { client: this.client, period: this.period },
      }),
      (r) => this.invoice.set(r),
    );
  }
  issue() {
    const v = this.invoice();
    if (this.busy() || !v || v.missing?.length || !v.lines.length) return;
    this.run(
      this.http.post<Invoice>(this.base + '/invoices', {
        client: this.client,
        period: this.period,
        signature: v.signature,
      }),
      (r) => this.invoice.set(r),
    );
  }
  openPdf() {
    const id = this.invoice()?.id;
    if (!id || this.busy()) return;
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      this.message.set('Permite abrir una nueva pestaña para ver la factura.');
      return;
    }
    tab.opener = null;
    tab.document.title = 'Abriendo factura…';
    this.busy.set(true);
    this.message.set('');
    let opened = false;
    this.pending = this.http.get(this.base + '/invoices/' + id + '/pdf', { responseType: 'blob' })
      .subscribe({
        next: blob => {
          if (tab.closed) return;
          const url = URL.createObjectURL(blob);
          tab.location.replace(url);
          opened = true;
          window.setTimeout(() => URL.revokeObjectURL(url), 60000);
        },
        error: () => this.message.set('No se pudo abrir el PDF. Inténtalo de nuevo.'),
      });
    this.pending.add(() => {
      this.busy.set(false);
      if (!opened) tab.close();
    });
  }

  action(action: 'send' | 'consult') {
    const id = this.invoice()?.id;
    if (this.busy() || !id) return;
    this.run(this.http.post<Invoice>(this.base + '/invoices/' + id + '/' + action, {}), (r) =>
      this.invoice.set(r),
    );
  }
}
