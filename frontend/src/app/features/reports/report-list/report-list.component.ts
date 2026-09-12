// features/reports/report-list/report-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe, JsonPipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Report } from '../../../shared/models/assignment.model';

@Component({
  selector: 'app-report-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, JsonPipe, TitleCasePipe, FormsModule],
  templateUrl: './report-list.component.html',
  styleUrl: './report-list.component.scss',
})
export class ReportListComponent implements OnInit {
  private assignmentService = inject(AssignmentService);

  reports = signal<Report[]>([]);
  loading = signal(true);
  saving = signal(false);
  showNewModal = signal(false);
  generatingId = signal<number | null>(null);
  successMsg = signal('');
  errorMsg = signal('');
  selectedResult = signal<any>(null);

  newForm: any = {
    name: '', type: 'alerts_summary', description: '',
    date_range_start: '', date_range_end: '',
  };

  readonly reportTypes = [
    { value: 'alerts_summary', label: ' Resumen de Alertas' },
    { value: 'operator_performance', label: ' Rendimiento por Técnico' },
    { value: 'response_times', label: ' Tiempos de Respuesta' },
  ];

  ngOnInit(): void { this.loadReports(); }

  loadReports(): void {
    this.loading.set(true);
    this.assignmentService.getReports().subscribe({
      next: ({ reports }) => { this.reports.set(reports); this.loading.set(false); },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.'); },
    });
  }

  openNewModal(): void {
    this.newForm = { name: '', type: 'alerts_summary', description: '', date_range_start: '', date_range_end: '' };
    this.showNewModal.set(true);
  }

  closeNewModal(): void { if (this.saving()) return; this.showNewModal.set(false); this.errorMsg.set(''); }

  createReport(): void {
    if (this.saving()) return;
    if (!this.newForm.name) { this.errorMsg.set('Nombre requerido'); return; }
    this.saving.set(true);
    this.assignmentService.createReport(this.newForm).subscribe({
      next: ({ report }) => {
        this.saving.set(false);
        this.closeNewModal();
        this.generateReport(report.id);
      },
      error: (err) => { this.saving.set(false); this.errorMsg.set(err?.error?.error || 'Error'); },
    });
  }

  generateReport(id: number): void {
    this.generatingId.set(id);
    this.assignmentService.generateReport(id).subscribe({
      next: ({ message, report }) => {
        this.successMsg.set(message);
        this.generatingId.set(null);
        this.loadReports();
        if (report.result_json) {
          this.selectedResult.set(JSON.parse(report.result_json));
        }
        setTimeout(() => this.successMsg.set(''), 4000);
      },
      error: (err) => {
        this.errorMsg.set(err?.error?.error || 'Error al generar');
        this.generatingId.set(null);
      },
    });
  }

  viewResult(report: Report): void {
    this.assignmentService.getReportById(report.id).subscribe({
      next: ({ report: detail }) => {
        if (detail.result_json) this.selectedResult.set(JSON.parse(detail.result_json));
        else this.errorMsg.set('Este reporte todavía no tiene un resultado generado');
      },
      error: err => this.errorMsg.set(err?.error?.error || 'No se pudo recuperar el reporte'),
    });
  }

  closeResult(): void { this.selectedResult.set(null); }

  deleteReport(id: number): void {
    if (!confirm('¿Eliminar este reporte?')) return;
    this.assignmentService.deleteReport(id).subscribe({
      next: ({ message }) => { this.successMsg.set(message); this.loadReports(); },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error'),
    });
  }

  getTypeLabel(type: string): string {
    return this.reportTypes.find((t) => t.value === type)?.label ?? type;
  }

  isObject(value: any): boolean {
    return typeof value === 'object' && value !== null;
  }

  resultEntries(): [string, any][] {
    const r = this.selectedResult();
    if (!r) return [];
    return Object.entries(r).filter(([k]) => !['type', 'generated_at'].includes(k));
  }
}
