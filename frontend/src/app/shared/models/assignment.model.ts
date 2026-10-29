export interface Assignment {
  id: number;
  alert_id: number;
  user_id: number;
  user?: {
    id: number;
    full_name: string;
    email?: string;
  };
  notes?: string;
  assignment_type: 'manual' | 'auto';
  assigned_at?: string;
  completed_at?: string;
  response_time_minutes?: number;
  status?: 'En Curso' | 'Completada' | 'Reasignada' | 'Anulada';
  alert_state?: string | null;
  event_type_code?: string | null;
}

export interface HistoryEntry {
  id: number;
  alert_id: number;
  user_id?: number;
  user?: { id: number; full_name: string };
  profile_id?: number | null;
  profile?: { id: number; name: string } | null;
  action: string;
  previous_state?: string;
  new_state?: string;
  detail?: string;
  timestamp: string;
  metadata?: { kind?: string; assignment_id?: number; category?: string; text?: string } | null;
}

export interface AssignmentNotes {
  alert_id: number;
  notes: HistoryEntry[];
  legacy_notes: { assignment_id: number; detail: string }[];
  legacy_audits: HistoryEntry[];
  can_add: boolean;
}

export interface Report {
  id: number;
  name: string;
  type: 'alerts_summary' | 'operator_performance' | 'response_times' | 'custom';
  description?: string;
  date_range_start?: string;
  date_range_end?: string;
  generated_by?: number;
  generator?: { id: number; full_name: string };
  result_json?: string;
  has_result?: boolean;
  created_at?: string;
}

export type ReportType = 'alerts_summary' | 'operator_performance' | 'response_times';
export interface ReportFilters {
  client_id?: number | null;
  vehicle_id?: number | null;
  user_id?: number | null;
  priority?: string;
  state?: string;
}
export interface ReportForm {
  name: string;
  type: ReportType;
  description: string;
  date_range_start: string;
  date_range_end: string;
  filters: ReportFilters;
}
export interface ResponseTimeStats {
  count: number;
  avg_minutes: number | null;
  min_minutes: number | null;
  max_minutes: number | null;
}
export interface TechnicianPerformance {
  technician_id: number;
  technician: string;
  assigned: number;
  resolved: number;
  reassigned: number;
  cancelled: number;
  active: number;
  avg_response_minutes: number | null;
}
export interface ReportResult {
  type: ReportType;
  generated_at?: string;
  generated_by?: { id: number; full_name: string };
  date_range?: { start: string | null; end: string | null };
  filters?: ReportFilters;
  filter_labels?: Record<string, string>;
  total_alerts?: number;
  by_priority?: Record<string, number | ResponseTimeStats>;
  by_state?: Record<string, number>;
  rows?: TechnicianPerformance[];
}
