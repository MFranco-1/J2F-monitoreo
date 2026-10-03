import { AuthService } from '../../../core/services/auth.service';
// features/alerts/alert-detail/alert-detail.component.ts
import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { NgFor, NgIf, DatePipe, TitleCasePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AlertService } from '../../../core/services/alert.service';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Alert } from '../../../shared/models/alert.model';
import { HistoryEntry } from '../../../shared/models/assignment.model';
import { firstError, validateForm, textError } from '../../../shared/validation';

@Component({
  selector: 'app-alert-detail',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, TitleCasePipe, FormsModule, RouterLink],
  templateUrl: './alert-detail.component.html',
  styleUrl: './alert-detail.component.scss',
})
export class AlertDetailComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private route = inject(ActivatedRoute);
  private alertService = inject(AlertService);
  private assignmentService = inject(AssignmentService);

  alert = signal<Alert | null>(null);
  history = signal<HistoryEntry[]>([]);
  loading = signal(true);
  successMsg = signal('');
  errorMsg = signal('');
  cancelling = signal(false);
  cancellationReason = '';
  private profileSubscription?: Subscription;
  private requestId = 0;

  // Para cambio de estado
  newStateName = '';
  stateNotes = '';
  readonly availableTransitions: Record<string, string[]> = {
    'Abierto': ['En Progreso', 'Escalado', 'Cerrado'],
    'En Progreso': ['Cerrado', 'Escalado', 'Abierto'],
    'Escalado': ['En Progreso', 'Cerrado'],
    'Cerrado': [],
    'Anulado': [],
  };

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.loadAlert(id);
    this.profileSubscription = this.auth.profileChanges.subscribe(() => {
      this.alert.set(null); this.history.set([]);
      this.cancellationReason = ''; this.cancelling.set(false);
      this.stateNotes = ''; this.newStateName = '';
      this.successMsg.set(''); this.errorMsg.set('');
      this.loadAlert(id);
    });
  }

  ngOnDestroy(): void { this.profileSubscription?.unsubscribe(); this.requestId++; }

  loadAlert(id: number): void {
    this.loading.set(true);
    const requestId = ++this.requestId;
    this.alertService.getAlertById(id).subscribe({
      next: ({ alert }) => {
        if (requestId !== this.requestId) return;
        this.alert.set(alert);
        this.history.set(alert.history ?? []);
        this.loading.set(false);
      },
      error: (err) => { if (requestId !== this.requestId) return; this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.'); },
    });
  }

  get canAttend(): boolean {
    return !!this.alert() && !this.isTerminal && (this.auth.isAdmin() || (this.auth.isTechnician()
      && this.alert()?.current_assignee?.id === this.auth.currentUser()?.id));
  }

  get isTerminal(): boolean { return ['Cerrado', 'Anulado'].includes(this.alert()?.state?.name || ''); }
  get canCancel(): boolean { return !!this.alert() && !this.isTerminal && this.auth.canCancelAlert(); }

  cancelAlert(): void {
    if (!this.canCancel || this.cancelling()) return;
    const error = textError(this.cancellationReason, { label: 'Motivo de anulación', min: 5, max: 1000, letters: 2, required: true });
    if (error) { this.errorMsg.set(error); return; }
    const id = this.alert()!.id;
    const requestId = this.requestId;
    this.cancelling.set(true); this.errorMsg.set('');
    this.alertService.cancelAlert(id, this.cancellationReason.trim()).subscribe({
      next: ({ alert, message }) => {
        if (requestId !== this.requestId) return;
        this.cancelling.set(false); this.cancellationReason = '';
        this.alert.set(alert); this.history.set(alert.history ?? []);
        this.successMsg.set(message);
      },
      error: err => {
        if (requestId !== this.requestId) return;
        this.cancelling.set(false);
        this.errorMsg.set(err?.status === 404 ?
          'La alerta no existe o el backend no tiene disponible la ruta de anulación. Comprueba que esté ejecutándose la versión actual.' :
          err?.error?.error || 'No se pudo anular la alerta');
      },
    });
  }

  get transitions(): string[] {
    const current = this.alert()?.state?.name ?? 'Abierto';
    const transitions = this.availableTransitions[current] ?? [];
    return this.isFuelAlert ? transitions.filter(state => state !== 'Cerrado') : transitions;
  }

  get isFuelAlert(): boolean { return this.alert()?.event_type?.code === 'LOW_FUEL'; }

  changeState(): void {
    if (!this.newStateName) { this.errorMsg.set('Selecciona un estado'); return; }
    if (this.newStateName === 'Cerrado' && !this.stateNotes.trim()) {
      this.errorMsg.set('Debes registrar la solución aplicada para cerrar la alerta');
      return;
    }
    const error = firstError(validateForm('assignment', { notes: this.stateNotes }));
    if (error) { this.errorMsg.set(error); return; }
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
    if (!this.auth.canAssign() || this.isTerminal) return;
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
      reassigned: ' Reasignada',
      cancelled: ' Anulada',
      fuel_coordinated: ' Coordinación de abastecimiento',
      fuel_confirmed: ' Abastecimiento confirmado',
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
