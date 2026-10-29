// core/services/assignment.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Assignment, AssignmentNotes, Report, ReportForm, HistoryEntry } from '../../shared/models/assignment.model';
import { User } from '../../shared/models/user.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class AssignmentService {
  private readonly BASE = environment.apiUrl;

  constructor(private http: HttpClient) {}

  // --- Assignments ---
  getAssignments(filters: { alert_id?: number; user_id?: number; active_only?: boolean } = {}): Observable<{ assignments: Assignment[] }> {
    let params = new HttpParams();
    Object.entries(filters).forEach(([k, v]) => { if (v !== undefined) params = params.set(k, String(v)); });
    return this.http.get<{ assignments: Assignment[] }>(`${this.BASE}/assignments/`, { params });
  }

  createAssignment(alertId: number, userId: number, notes?: string): Observable<{ assignment: Assignment; message: string }> {
    return this.http.post<{ assignment: Assignment; message: string }>(`${this.BASE}/assignments/`, {
      alert_id: alertId, user_id: userId, notes,
    });
  }

  getTechnicians(): Observable<{ technicians: { id: number; full_name: string; active_assignments_count: number }[] }> {
    return this.http.get<{ technicians: { id: number; full_name: string; active_assignments_count: number }[] }>(
      `${this.BASE}/assignments/technicians`
    );
  }

  autoAssign(alertId: number): Observable<{ assignment: Assignment; technician: User; message: string }> {
    return this.http.post<{ assignment: Assignment; technician: User; message: string }>(
      `${this.BASE}/assignments/auto-assign`, { alert_id: alertId }
    );
  }

  updateAssignment(id: number, data: { notes?: string; complete?: boolean; solution?: string }): Observable<{ assignment: Assignment; message: string }> {
    return this.http.put<{ assignment: Assignment; message: string }>(`${this.BASE}/assignments/${id}`, data);
  }

  getAssignmentNotes(id: number): Observable<AssignmentNotes> {
    return this.http.get<AssignmentNotes>(`${this.BASE}/assignments/${id}/notes`);
  }

  addAssignmentNote(id: number, notes: string): Observable<{ note: HistoryEntry; message: string }> {
    return this.http.post<{ note: HistoryEntry; message: string }>(`${this.BASE}/assignments/${id}/notes`, { notes });
  }

  // --- Reports ---
  getReports(): Observable<{ reports: Report[] }> {
    return this.http.get<{ reports: Report[] }>(`${this.BASE}/reports/`);
  }

  getReportById(id: number): Observable<{ report: Report }> {
    return this.http.get<{ report: Report }>(`${this.BASE}/reports/${id}`);
  }

  createReport(data: ReportForm): Observable<{ report: Report; message: string }> {
    return this.http.post<{ report: Report; message: string }>(`${this.BASE}/reports/`, data);
  }

  generateReport(id: number): Observable<{ report: Report; message: string }> {
    return this.http.post<{ report: Report; message: string }>(`${this.BASE}/reports/${id}/generate`, {});
  }

  deleteReport(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.BASE}/reports/${id}`);
  }

  exportReport(id: number, format: 'csv' | 'json'): Observable<Blob> {
    return this.http.get(`${this.BASE}/reports/${id}/export`, { params: { format }, responseType: 'blob' });
  }

  // --- History ---
  getGlobalHistory(filters: { action?: string; user_id?: number; date_from?: string; date_to?: string; page?: number } = {}): Observable<{ history: HistoryEntry[]; total: number; pages: number }> {
    let params = new HttpParams();
    Object.entries(filters).forEach(([k, v]) => { if (v !== undefined && v !== '') params = params.set(k, String(v)); });
    return this.http.get<{ history: HistoryEntry[]; total: number; pages: number }>(`${this.BASE}/reports/history`, { params });
  }

  getAlertHistory(alertId: number): Observable<{ history: HistoryEntry[] }> {
    return this.http.get<{ history: HistoryEntry[] }>(`${this.BASE}/reports/history/alerts/${alertId}`);
  }
}
