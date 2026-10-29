import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { NgFor, NgIf, NgSwitch, NgSwitchCase, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, takeUntil } from 'rxjs';
import { AssignmentService } from '../../../core/services/assignment.service';
import {
  Report,
  ReportForm,
  ReportResult,
  ResponseTimeStats,
} from '../../../shared/models/assignment.model';
import { MasterDataService } from '../../../core/services/master-data.service';
import { AuthService } from '../../../core/services/auth.service';
import { Client, Vehicle } from '../../../shared/models/master-data.model';
import { firstError, validateForm } from '../../../shared/validation';

@Component({
  selector: 'app-report-list',
  standalone: true,
  imports: [NgFor, NgIf, NgSwitch, NgSwitchCase, DatePipe, FormsModule],
  templateUrl: './report-list.component.html',
  styleUrl: './report-list.component.scss',
})
export class ReportListComponent implements OnInit, OnDestroy {
  private assignmentService = inject(AssignmentService);
  private masterData = inject(MasterDataService);
  readonly auth = inject(AuthService);
  private readonly reset$ = new Subject<void>();
  private readonly destroyed$ = new Subject<void>();
  private resultRequest = 0;

  reports = signal<Report[]>([]);
  loading = signal(true);
  saving = signal(false);
  showNewModal = signal(false);
  generatingId = signal<number | null>(null);
  exporting = signal(false);
  successMsg = signal('');
  errorMsg = signal('');
  selectedResult = signal<ReportResult | null>(null);
  selectedReport = signal<Report | null>(null);
  clients = signal<Client[]>([]);
  vehicles = signal<Vehicle[]>([]);
  newForm: ReportForm = this.blankForm();
  readonly reportTypes = [
    { value: 'alerts_summary', label: 'Resumen de alertas' },
    { value: 'operator_performance', label: 'Rendimiento por técnico' },
    { value: 'response_times', label: 'Tiempos de respuesta' },
  ];

  private canReport(): boolean {
    return this.auth.isAdmin() || this.auth.isSupervisor();
  }
  private blankForm(): ReportForm {
    return {
      name: '',
      type: 'alerts_summary',
      description: '',
      date_range_start: '',
      date_range_end: '',
      filters: { client_id: null, vehicle_id: null, priority: '', state: '' },
    };
  }

  ngOnInit(): void {
    this.auth.profileChanges.pipe(takeUntil(this.destroyed$)).subscribe(() => {
      this.reset$.next();
      this.resultRequest++;
      this.reports.set([]);
      this.clients.set([]);
      this.vehicles.set([]);
      this.closeResult();
      this.showNewModal.set(false);
      this.saving.set(false);
      this.generatingId.set(null);
      this.exporting.set(false);
      this.loading.set(false);
      this.successMsg.set('');
      this.errorMsg.set('');
      if (this.canReport()) this.load();
    });
    if (this.canReport()) this.load();
    else this.loading.set(false);
  }

  private load(): void {
    this.loadReports();
    this.masterData
      .clients()
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ clients }) => this.clients.set(clients),
        error: () => this.errorMsg.set('No se pudo cargar el catálogo de clientes'),
      });
    this.masterData
      .vehicles()
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ vehicles }) => this.vehicles.set(vehicles),
        error: () => this.errorMsg.set('No se pudo cargar el catálogo de vehículos'),
      });
  }

  loadReports(): void {
    if (!this.canReport()) return;
    this.loading.set(true);
    this.assignmentService
      .getReports()
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ reports }) => {
          this.reports.set(reports);
          this.loading.set(false);
        },
        error: (err) => {
          this.loading.set(false);
          this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los reportes');
        },
      });
  }

  openNewModal(): void {
    if (!this.canReport()) return;
    this.newForm = this.blankForm();
    this.errorMsg.set('');
    this.showNewModal.set(true);
  }
  closeNewModal(): void {
    if (!this.saving()) this.showNewModal.set(false);
  }
  onClientChange(): void {
    this.newForm.filters.vehicle_id = null;
  }

  createReport(): void {
    if (!this.canReport() || this.saving()) return;
    const error = firstError(validateForm('reports', this.newForm));
    if (error) {
      this.errorMsg.set(error);
      return;
    }
    this.saving.set(true);
    this.errorMsg.set('');
    this.assignmentService
      .createReport(this.newForm)
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ report }) => {
          this.saving.set(false);
          this.closeNewModal();
          this.generateReport(report.id);
        },
        error: (err) => {
          this.saving.set(false);
          this.errorMsg.set(err?.error?.error || 'No se pudo crear el reporte');
        },
      });
  }

  generateReport(id: number): void {
    if (!this.canReport() || this.generatingId() !== null) return;
    const version = ++this.resultRequest;
    this.generatingId.set(id);
    this.errorMsg.set('');
    this.assignmentService
      .generateReport(id)
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ message, report }) => {
          this.generatingId.set(null);
          this.successMsg.set(message);
          this.loadReports();
          if (version === this.resultRequest) this.showResult(report);
        },
        error: (err) => {
          this.generatingId.set(null);
          this.errorMsg.set(err?.error?.error || 'No se pudo generar el reporte');
        },
      });
  }

  viewResult(report: Report): void {
    if (!this.canReport()) return;
    const version = ++this.resultRequest;
    this.assignmentService
      .getReportById(report.id)
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ report: detail }) => {
          if (version === this.resultRequest) this.showResult(detail);
        },
        error: (err) => {
          if (version === this.resultRequest)
            this.errorMsg.set(err?.error?.error || 'No se pudo recuperar el reporte');
        },
      });
  }

  private showResult(report: Report): void {
    try {
      const parsed: unknown = JSON.parse(report.result_json || 'null');
      if (
        !parsed ||
        typeof parsed !== 'object' ||
        !('type' in parsed) ||
        !this.reportTypes.some((item) => item.value === parsed.type)
      )
        throw new Error('Resultado inválido');
      const result = parsed as Record<string, unknown>;
      const isObject = (value: unknown): value is Record<string, unknown> =>
        !!value && typeof value === 'object' && !Array.isArray(value);
      for (const key of [
        'generated_by',
        'date_range',
        'filter_labels',
        'filters',
        'by_priority',
        'by_state',
      ]) {
        if (key in result && !isObject(result[key])) throw new Error('Metadatos inválidos');
      }
      if (
        result['type'] === 'operator_performance' &&
        'rows' in result &&
        (!Array.isArray(result['rows']) || !result['rows'].every(isObject))
      )
        throw new Error('Filas inválidas');
      if (
        result['type'] === 'response_times' &&
        isObject(result['by_priority']) &&
        !Object.values(result['by_priority']).every(isObject)
      )
        throw new Error('Métricas inválidas');
      this.selectedResult.set(parsed as ReportResult);
      this.selectedReport.set(report);
      this.errorMsg.set('');
    } catch {
      this.closeResult();
      this.errorMsg.set('El reporte no tiene un resultado válido. Vuelve a generarlo.');
    }
  }

  closeResult(): void {
    this.resultRequest++;
    this.selectedResult.set(null);
    this.selectedReport.set(null);
  }

  download(format: 'csv' | 'json'): void {
    const report = this.selectedReport();
    if (!this.canReport() || !report || this.exporting()) return;
    this.exporting.set(true);
    this.errorMsg.set('');
    this.assignmentService
      .exportReport(report.id, format)
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: (blob) => {
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = `reporte-${report.id}.${format}`;
          link.click();
          URL.revokeObjectURL(url);
          this.exporting.set(false);
        },
        error: () => {
          this.exporting.set(false);
          this.errorMsg.set(
            'No se pudo descargar el reporte. Verifica tu sesión y que tenga un resultado generado.',
          );
        },
      });
  }

  deleteReport(id: number): void {
    if (!this.auth.isAdmin() || !confirm('¿Eliminar este reporte?')) return;
    this.assignmentService
      .deleteReport(id)
      .pipe(takeUntil(this.reset$))
      .subscribe({
        next: ({ message }) => {
          this.successMsg.set(message);
          if (this.selectedReport()?.id === id) this.closeResult();
          this.loadReports();
        },
        error: (err) => this.errorMsg.set(err?.error?.error || 'No se pudo eliminar el reporte'),
      });
  }

  getTypeLabel(type: string): string {
    return this.reportTypes.find((item) => item.value === type)?.label ?? type;
  }
  priorityLabel(priority: string): string {
    return (
      (
        { critical: 'Crítica', high: 'Alta', medium: 'Media', low: 'Baja' } as Record<
          string,
          string
        >
      )[priority] || priority
    );
  }
  priorityCounts(): [string, number][] {
    return Object.entries(this.selectedResult()?.by_priority || {}).filter(
      (entry): entry is [string, number] => typeof entry[1] === 'number',
    );
  }
  responseTimes(): [string, ResponseTimeStats][] {
    return Object.entries(this.selectedResult()?.by_priority || {}).filter(
      (entry): entry is [string, ResponseTimeStats] =>
        typeof entry[1] === 'object' && entry[1] !== null,
    );
  }
  stateCounts(): [string, number][] {
    return Object.entries(this.selectedResult()?.by_state || {});
  }
  filterEntries(): [string, string][] {
    const result = this.selectedResult();
    return result?.filter_labels
      ? Object.entries(result.filter_labels)
      : Object.entries(result?.filters || {}).map(([key, value]) => [key, String(value)]);
  }
  filteredVehicles(): Vehicle[] {
    const clientId = this.newForm.filters.client_id;
    return clientId
      ? this.vehicles().filter((vehicle) => vehicle.client_id === clientId)
      : this.vehicles();
  }
  ngOnDestroy(): void {
    this.reset$.next();
    this.reset$.complete();
    this.destroyed$.next();
    this.destroyed$.complete();
    this.resultRequest++;
  }
}
