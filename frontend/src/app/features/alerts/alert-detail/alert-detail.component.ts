import { AuthService } from '../../../core/services/auth.service';
// features/alerts/alert-detail/alert-detail.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { NgFor, NgIf, DatePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AlertService } from '../../../core/services/alert.service';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Alert } from '../../../shared/models/alert.model';
import { HistoryEntry } from '../../../shared/models/assignment.model';

@Component({
  selector: 'app-alert-detail',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, TitleCasePipe, FormsModule, RouterLink],
  templateUrl: './alert-detail.component.html',
  styleUrl: './alert-detail.component.scss',
})
export class AlertDetailComponent implements OnInit {
  readonly auth = inject(AuthService);
  private route = inject(ActivatedRoute);
  private alertService = inject(AlertService);
  private assignmentService = inject(AssignmentService);

  alert = signal<Alert | null>(null);
  history = signal<HistoryEntry[]>([]);
  loading = signal(true);
  successMsg = signal('');
  errorMsg = signal('');

  // Para cambio de estado
  newStateName = '';
  stateNotes = '';
  readonly availableTransitions: Record<string, string[]> = {
    'Abierto': ['En Progreso', 'Escalado', 'Cerrado'],
    'En Progreso': ['Cerrado', 'Escalado', 'Abierto'],
    'Escalado': ['En Progreso', 'Cerrado'],
    'Cerrado': [],
  };

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.loadAlert(id);
  }

  loadAlert(id: number): void {
    this.loading.set(true);
    this.alertService.getAlertById(id).subscribe({
      next: ({ alert }) => {
        this.alert.set(alert);
        this.history.set(alert.history ?? []);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.'); },
    });
  }

  get canAttend(): boolean {
    return this.auth.isAdmin() || (this.auth.isOperator()
      && this.alert()?.current_assignee?.id === this.auth.currentUser()?.id);
  }

  get transitions(): string[] {
    const current = this.alert()?.state?.name ?? 'Abierto';
    return this.availableTransitions[current] ?? [];
  }

  changeState(): void {
    if (!this.newStateName) { this.errorMsg.set('Selecciona un estado'); return; }
    const id = this.alert()!.id;
    this.alertService.updateAlert(id, { state_name: this.newStateName, notes: this.stateNotes }).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.newStateName = '';
        this.stateNotes = '';
        this.loadAlert(id);
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error al cambiar estado'),
    });
  }

  autoAssign(): void {
    const id = this.alert()!.id;
    this.assignmentService.autoAssign(id).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.loadAlert(id);
        setTimeout(() => this.successMsg.set(''), 4000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error en asignación'),
    });
  }

  getActionLabel(action: string): string {
    const labels: Record<string, string> = {
      created: ' Creada', state_changed: ' Estado cambiado',
      assigned: ' Asignada', note_added: ' Nota añadida',
      escalated: ' Escalada', closed: ' Cerrada', updated: ' Actualizada',
    };
    return labels[action] ?? action;
  }

  getPriorityLabel(p: string): string { return ({ critical: 'Crítica', high: 'Alta', medium: 'Media', low: 'Baja' } as Record<string, string>)[p] || p; }

  getPriorityClass(p: string): string { return `badge-${p}`; }
  getStateClass(stateName: string): string {
    const map: Record<string, string> = {
      'Abierto': 'badge-open', 'En Progreso': 'badge-progress',
      'Cerrado': 'badge-closed', 'Escalado': 'badge-escalated',
    };
    return map[stateName] ?? 'badge-inactive';
  }
}
