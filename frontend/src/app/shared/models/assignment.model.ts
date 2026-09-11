// shared/models/assignment.model.ts
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
}

export interface HistoryEntry {
  id: number;
  alert_id: number;
  user_id?: number;
  user?: { id: number; full_name: string };
  action: string;
  previous_state?: string;
  new_state?: string;
  detail?: string;
  timestamp: string;
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
