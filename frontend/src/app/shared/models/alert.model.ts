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
  state?: string;
  priority?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  per_page?: number;
}
