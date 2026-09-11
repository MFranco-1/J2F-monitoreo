// core/services/alert.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Alert, AlertMetrics, AlertsResponse, AlertFilters } from '../../shared/models/alert.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class AlertService {
  private readonly BASE = `${environment.apiUrl}/alerts`;

  constructor(private http: HttpClient) {}

  getMetrics(): Observable<AlertMetrics> {
    return this.http.get<AlertMetrics>(`${this.BASE}/metrics`);
  }

  getAlerts(filters: AlertFilters = {}): Observable<AlertsResponse> {
    let params = new HttpParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, String(value));
      }
    });
    return this.http.get<AlertsResponse>(this.BASE + '/', { params });
  }

  getAlertById(id: number): Observable<{ alert: Alert }> {
    return this.http.get<{ alert: Alert }>(`${this.BASE}/${id}`);
  }

  createAlert(data: Partial<Alert>): Observable<{ alert: Alert; message: string }> {
    return this.http.post<{ alert: Alert; message: string }>(this.BASE + '/', data);
  }

  updateAlert(id: number, data: Partial<Alert> & { state_name?: string; notes?: string }): Observable<{ alert: Alert; message: string }> {
    return this.http.put<{ alert: Alert; message: string }>(`${this.BASE}/${id}`, data);
  }

  deleteAlert(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.BASE}/${id}`);
  }
}
