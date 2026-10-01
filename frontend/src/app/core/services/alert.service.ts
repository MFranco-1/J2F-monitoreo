// core/services/alert.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Alert, AlertMetrics, AlertsResponse, AlertFilters, FuelStation, MapVehicle, StreetRoute } from '../../shared/models/alert.model';
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

  getMapVehicles(clientId?: number): Observable<{ vehicles: MapVehicle[] }> {
    let params = new HttpParams();
    if (clientId) params = params.set('client_id', String(clientId));
    return this.http.get<{ vehicles: MapVehicle[] }>(`${this.BASE}/map/vehicles`, { params });
  }

  createMapEvent(data: {
    vehicle_id: number;
    event_code: 'SPEEDING' | 'GPS_SIGNAL_LOSS' | 'SOS' | 'LOW_FUEL';
    latitude: number;
    longitude: number;
    speed: number;
    fuel_percent?: number;
  }): Observable<{ message: string; created: boolean; alert: Alert }> {
    return this.http.post<{ message: string; created: boolean; alert: Alert }>(
      `${this.BASE}/map/events`, data
    );
  }

  getFuelStations(latitude: number, longitude: number, radius = 3000) {
    const params = new HttpParams().set('latitude', latitude).set('longitude', longitude).set('radius', radius);
    return this.http.get<{ stations: FuelStation[]; source: string }>(`${this.BASE}/map/fuel-stations`, { params });
  }

  getStreetRoute(originLat: number, originLng: number, destinationLat: number, destinationLng: number) {
    const params = new HttpParams().set('origin_lat', originLat).set('origin_lng', originLng)
      .set('destination_lat', destinationLat).set('destination_lng', destinationLng);
    return this.http.get<StreetRoute>(`${this.BASE}/map/route`, { params });
  }

  recordFuelAction(alertId: number, action: 'coordinate' | 'confirm', detail: string) {
    return this.http.post<{ message: string; fuel_status: 'pending' | 'coordinated' | 'confirmed' }>(
      `${this.BASE}/${alertId}/fuel-actions`, { action, detail });
  }
}
