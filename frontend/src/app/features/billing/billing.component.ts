import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, LowerCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { catchError, from, Observable, retry, Subscription, throwError, timer } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { environment } from '../../../environments/environment';

interface Contract {
  plan: string;
  service_start: string;
  first_period: string;
  equipment_paid: boolean;
}
interface BilledPeriod {
  id: number;
  number: string | null;
  plan: string;
  period: string;
  start: string;
  end: string;
  amount: number;
}
interface Catalog {
  billed_periods?: Record<number, BilledPeriod[]>;
  coverage?: Record<number, { plan: string; start: string; end: string; status: string }>;
  clients: { id: number; name: string }[];
  vehicles: { id: number; client_id: number; plate: string; contract: Contract | null }[];
}
interface InvoiceRow {
  id: number;
  number: string | null;
  issue_date: string;
  created_at: string | null;
  client_name: string;
  total: number;
  status: string;
  external_id: number | null;
}
interface Invoice {
  sale_start?: string;
  recipient?: { razon_social: string };
  id?: number;
  number?: string;
  signature?: string;
  status?: string;
  message?: string;
  sunat_status?: string;
  external_id?: number;
  missing?: string[];
  total: number;
  lines: { plate: string; concept: string; label: string; period: string; gross: number }[];
}

@Component({
  selector: 'app-billing',
  standalone: true,
  imports: [FormsModule, DecimalPipe, DatePipe, LowerCasePipe],
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
  private quote?: Subscription;
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
  tab: 'service' | 'history' = 'service';
  rows: InvoiceRow[] = [];
  more = false;
  historyClient: number | null = null;
  dateFrom = '';
  dateTo = '';

  resetFilters() {
    this.historyClient = null;
    this.dateFrom = this.dateTo = '';
    this.history();
  }

  plates: number[] = [];

  switchTab(tab: 'service' | 'history') {
    this.closePlates();
    this.tab = tab;
    this.clear();
    if (tab === 'history') this.history();
    else this.changeClient();
  }

  history(append = false) {
    const before = append ? this.rows[this.rows.length - 1]?.id : null;
    const params: Record<string, string | number> = {};
    if (!append) {
      this.rows = [];
      this.more = false;
      this.clear();
    }
    if (this.dateFrom && this.dateTo && this.dateFrom > this.dateTo) {
      this.message.set('La fecha final debe ser igual o posterior a la inicial.');
      return;
    }
    if (before) params['before'] = before;
    if (this.historyClient) params['client'] = this.historyClient;
    if (this.dateFrom) params['from'] = this.dateFrom;
    if (this.dateTo) params['to'] = this.dateTo;
    this.run(this.http.get<{ items: InvoiceRow[]; has_more: boolean }>(this.base + '/invoices', { params }), page => {
      this.rows = append ? [...this.rows, ...page.items] : page.items;
      this.more = page.has_more;
    });
  }

  showInvoice(id: number) {
    this.clear();
    this.run(this.http.get<Invoice>(this.base + '/invoices/' + id), (r) => this.invoice.set(r));
  }

  client: number | null = null;
  plan = 'monthly';
  start = '';

  platesOpen = false;
  plateSearch = '';

  get vehicles() {
    return this.catalog().vehicles.filter(v => v.client_id === this.client);
  }

  get selectedVehicles() {
    const ids = new Set(this.plates);
    return this.vehicles.filter(v => ids.has(v.id));
  }

  togglePicker() {
    if (this.platesOpen) this.closePlates();
    else this.platesOpen = true;
  }

  get selectedPlans() {
    const catalog = this.catalog();
    return this.selectedVehicles.flatMap(v => {
      const periods = catalog.billed_periods?.[v.id] || [];
      const selected = this.start ? periods.find(p => p.period.slice(0, 7) === this.start.slice(0, 7))
        || periods.find(p => p.start <= this.start && this.start <= p.end) : undefined;
      const coverage = selected || catalog.coverage?.[v.id];
      if (!coverage && !v.contract) return [];
      return [{ plate: v.plate, periods, selected,
        name: coverage?.plan || (v.contract?.plan === 'annual' ? 'Anual' : 'Mensual'),
        start: coverage?.start || v.contract!.service_start, end: coverage?.end || '' }];
    });
  }

  private readonly monthFormat = new Intl.DateTimeFormat('es-PE', {
    month: 'long', year: 'numeric', timeZone: 'UTC',
  });

  monthLabel(period: string) {
    return this.monthFormat.format(new Date(period + 'T00:00:00Z'));
  }

  get hasNewPlan() {
    return this.vehicles.some(v => this.plates.includes(v.id) && !v.contract);
  }

  get visibleVehicles() {
    const query = this.plateSearch.trim().toLowerCase();
    return this.vehicles.filter(v => v.plate.toLowerCase().includes(query));
  }

  get plateSummary() {
    if (!this.plates.length) return 'Seleccionar placas';
    if (this.plates.length === 1) return this.vehicles.find(v => v.id === this.plates[0])?.plate;
    return this.plates.length === this.vehicles.length ? 'Todas las placas' : this.plates.length + ' placas';
  }

  get existingPlans() {
    return new Set(this.vehicles.filter(v => this.plates.includes(v.id) && v.contract)
      .map(v => v.contract!.plan));
  }

  get renewal() {
    return this.plates.length > 0 && !this.hasNewPlan;
  }

  get commonStartDay() {
    const days = new Set(this.selectedVehicles.map(v => v.contract?.service_start.slice(-2)));
    return days.size === 1 ? Number([...days][0]) : null;
  }

  chooseMonth(month: string) {
    if (!month || !this.commonStartDay) this.start = '';
    else {
      const [year, index] = month.split('-').map(Number);
      const last = new Date(Date.UTC(year, index, 0)).getUTCDate();
      this.start = month + '-' + String(Math.min(last, this.commonStartDay)).padStart(2, '0');
    }
    this.quoteSale();
  }

  get chargeLabel() {
    if (!this.renewal) return 'Vender y generar factura';
    if (this.existingPlans.size > 1) return 'Facturar servicios';
    return this.plan === 'annual' ? 'Facturar renovación anual' : 'Facturar mensualidad';
  }


  // Un listener global que devuelve false cancela tambi?n el clic nativo de los select.
  closePlatesIfOutside(picker: HTMLElement, target: EventTarget | null): void {
    if (this.platesOpen && target instanceof Node && !picker.contains(target)) this.closePlates();
  }

  closePlates() {
    this.platesOpen = false;
    this.plateSearch = '';
  }

  selectPlates(ids: number[]) {
    const previousDay = this.commonStartDay;
    const wasRenewal = this.renewal;
    this.plates = ids;
    if (wasRenewal !== this.renewal || (this.renewal && previousDay !== this.commonStartDay)) this.start = '';
    const plans = this.existingPlans;
    if (ids.length && !this.hasNewPlan) this.plan = plans.size === 1 ? [...plans][0] : 'existing';
    else if (this.plan === 'existing') this.plan = 'monthly';
    this.quoteSale();
  }

  togglePlate(id: number) {
    this.selectPlates(this.plates.includes(id) ? this.plates.filter(v => v !== id) : [...this.plates, id]);
  }

  toggleAll() {
    this.selectPlates(this.plates.length === this.vehicles.length ? [] : this.vehicles.map(v => v.id));
  }

  newSale() {
    this.client = null;
    this.changeClient();
  }

  ngOnInit() {
    this.load();
    this.profile = this.auth.profileChanges.subscribe(() => {
      this.pending?.unsubscribe();
      this.catalog.set({ clients: [], vehicles: [] });
      this.client = null;
      this.changeClient();
      this.rows = [];
      this.historyClient = null;
      this.dateFrom = this.dateTo = '';
      this.tab = 'service';
      this.clear();
      if (this.auth.hasPermission('billing')) this.load();
      else void this.router.navigateByUrl('/dashboard');
    });
  }
  ngOnDestroy() {
    this.quote?.unsubscribe();
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
        this.message.set(e.error?.error || 'No se completó la operación. Vuelve a intentarlo.');
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
    this.quote?.unsubscribe();
    this.invoice.set(null);
    this.message.set('');
  }
  changeClient() {
    this.closePlates();
    this.plates = [];
    this.start = '';
    this.plan = 'monthly';
    this.clear();
  }

  private saleData() {
    return { client: this.client, vehicles: this.plates, plan: this.plan === 'existing' ? [...this.existingPlans][0] : this.plan, start: this.start };
  }

  quoteSale() {
    this.clear();
    if (!this.plates.length || !this.start) return;
    this.quote = this.http.post<Invoice>(this.base + '/sales/preview', this.saleData()).subscribe({
      next: draft => this.invoice.set(draft),
      error: e => {
        const reason = e.error?.error;
        const billed = this.selectedPlans.filter(item => item.selected);
        if (typeof reason === 'string' && reason.startsWith('Sin cargos pendientes') && billed.length) {
          if (billed.length !== this.plates.length) this.message.set('Selecciona las placas pendientes para continuar.');
        } else this.message.set(reason || 'No se pudo calcular el importe.');
      },
    });
  }

  issue() {
    const v = this.invoice();
    if (this.busy() || !this.plates.length || !v || v.id || v.missing?.length || !v.lines.length) return;
    this.run(this.http.post<Invoice>(this.base + '/sales', { ...this.saleData(), signature: v.signature }), invoice => {
      this.invoice.set(invoice);
      this.load(invoice.number ? 'Venta registrada. Tu factura está lista.' : 'Venta registrada. Revisa el estado de la factura.');
    });
  }

  downloadXml(id: number, number?: string | null) {
    if (this.busy()) return;
    this.run(
      this.http.get(this.base + '/invoices/' + id + '/xml', { responseType: 'blob' }),
      (blob) => {
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = (number || 'factura-' + id) + '.xml';
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      },
    );
  }

  openPdf(id = this.invoice()?.id) {
    if (!id || this.busy()) return;
    const tab = window.open('about:blank', '_blank');
    if (!tab) {
      this.message.set('Permite abrir una nueva pestaña para ver la factura.');
      return;
    }
    tab.opener = null;
    tab.document.title = 'Abriendo factura…';
    tab.document.body.textContent = 'Preparando el PDF de la factura…';
    this.busy.set(true);
    this.message.set('');
    let opened = false;
    this.pending = this.http
      .get(this.base + '/invoices/' + id + '/pdf', { responseType: 'blob' })
      .pipe(
        retry({
          count: 2,
          delay: (err, attempt) => {
            if (![0, 503, 504].includes(err.status)) return throwError(() => err);
            if (!tab.closed)
              tab.document.body.textContent = 'Esperando al servicio de facturación…';
            return timer(attempt * 2500);
          },
        }),
        catchError((err) =>
          from(
            (async (): Promise<never> => {
              let reason = err.error;
              if (reason instanceof Blob) {
                try {
                  reason = JSON.parse(await reason.text());
                } catch {
                  reason = null;
                }
              }
              throw new Error(
                typeof reason?.error === 'string'
                  ? reason.error
                  : 'No se pudo obtener el PDF. Vuelve a Servicio para intentarlo de nuevo.',
              );
            })(),
          ),
        ),
      )
      .subscribe({
        next: (blob) => {
          if (tab.closed) return;
          const url = URL.createObjectURL(blob);
          tab.location.replace(url);
          opened = true;
          window.setTimeout(() => URL.revokeObjectURL(url), 60000);
        },
        error: (err: Error) => {
          this.message.set(err.message);
          if (!tab.closed) {
            tab.document.title = 'PDF de la factura';
            tab.document.body.textContent = err.message;
            opened = true;
          }
        },
      });
    this.pending.add(() => {
      this.busy.set(false);
      if (!opened) tab.close();
    });
  }

  action(action: 'send' | 'consult' | 'create') {
    const id = this.invoice()?.id;
    if (this.busy() || !id) return;
    this.run(this.http.post<Invoice>(this.base + '/invoices/' + id + '/' + action, {}), (r) => {
      this.invoice.set(r);
      this.rows = this.rows.map((row) => (row.id === id ? ({ ...row, ...r } as InvoiceRow) : row));
    });
  }
}
