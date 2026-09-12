// shared/models/alert.model.ts
export type AlertPriority = 'critical' | 'high' | 'medium' | 'low';
export type AlertStateName = 'Abierto' | 'En Progreso' | 'Cerrado' | 'Escalado';

export interface AlertState {
  id: number;
  name: string;
  type: string;
  description?: string;
}

export interface Alert {
  id: number;
  title: string;
  description?: string;
  priority: AlertPriority;
  service_type?: string;
  location?: string;
  source?: string;
  state_id: number;
  state?: AlertState;
  created_by?: number;
  vehicle_id?: number | null;
  gps_device_id?: number | null;
  event_type_id?: number | null;
  client?: import('./master-data.model').Client | null;
  vehicle?: import('./master-data.model').Vehicle | null;
  gps_device?: import('./master-data.model').GpsDevice | null;
  event_type?: import('./master-data.model').EventType | null;
  opened_at?: string;
  acknowledged_at?: string;
  resolved_at?: string;
  response_time_minutes?: number;
  current_assignee?: UserSummary;
  history?: any[];
  created_at?: string;
  updated_at?: string;
}

export interface UserSummary {
  id: number;
  full_name: string;
  email?: string;
}

export interface AlertMetrics {
  total_alerts: number;
  by_state: Record<string, number>;
  critical_open: Alert[];
  avg_response_time_minutes: number;
}

export interface AlertsResponse {
  alerts: Alert[];
  total: number;
  pages: number;
  current_page: number;
}

export interface AlertFilters {
  client_id?: number;
  vehicle_id?: number;
  state?: string;
  priority?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  per_page?: number;
}
