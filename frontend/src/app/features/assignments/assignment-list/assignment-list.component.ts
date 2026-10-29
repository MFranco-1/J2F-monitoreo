import { AuthService } from '../../../core/services/auth.service';
import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Assignment, AssignmentNotes } from '../../../shared/models/assignment.model';
import { textError } from '../../../shared/validation';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-assignment-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, FormsModule, RouterLink],
  templateUrl: './assignment-list.component.html',
  styleUrl: './assignment-list.component.scss',
})
export class AssignmentListComponent implements OnInit, OnDestroy {
  readonly auth = inject(AuthService);
  private assignmentService = inject(AssignmentService);

  assignments = signal<Assignment[]>([]);
  loading = signal(true);
  successMsg = signal('');
  errorMsg = signal('');
  showNoteModal = signal(false);
  showCloseModal = signal(false);
  editingAssignment = signal<Assignment | null>(null);
  noteText = '';
  solutionText = '';
  showActiveOnly = true;
  caseNotes = signal<AssignmentNotes | null>(null);
  loadingNotes = signal(false);
  savingNote = signal(false);
  closing = signal(false);
  noteError = signal('');
  readonly noteGroups = [
    { category: 'technical', title: 'Notas del técnico' },
    { category: 'coordination', title: 'Notas de Supervisión y Administración' },
    { category: 'assignment', title: 'Indicaciones de asignación' },
  ];
  private listRequest?: Subscription;
  private notesRequest?: Subscription;
  private writeRequest?: Subscription;
  private profileSubscription?: Subscription;
  private listVersion = 0;
  private notesVersion = 0;
  private destroyed = false;

  ngOnInit(): void {
    this.profileSubscription = this.auth.profileChanges.subscribe(() => {
      this.resetDialogs();
      this.assignments.set([]);
      this.successMsg.set('');
      this.errorMsg.set('');
      this.loadAssignments();
    });
    this.loadAssignments();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.listVersion++;
    this.listRequest?.unsubscribe();
    this.profileSubscription?.unsubscribe();
    this.resetDialogs();
  }

  private resetDialogs(): void {
    this.notesVersion++;
    this.notesRequest?.unsubscribe();
    this.writeRequest?.unsubscribe();
    this.showNoteModal.set(false);
    this.showCloseModal.set(false);
    this.editingAssignment.set(null);
    this.caseNotes.set(null);
    this.noteText = '';
    this.solutionText = '';
    this.noteError.set('');
    this.loadingNotes.set(false);
    this.savingNote.set(false);
    this.closing.set(false);
  }

  loadAssignments(): void {
    const version = ++this.listVersion;
    this.listRequest?.unsubscribe();
    this.loading.set(true);
    this.listRequest = this.assignmentService.getAssignments({ active_only: this.showActiveOnly }).subscribe({
      next: ({ assignments }) => {
        if (this.destroyed || version !== this.listVersion) return;
        this.assignments.set(assignments);
        this.loading.set(false);
      },
      error: (err) => {
        if (this.destroyed || version !== this.listVersion) return;
        this.assignments.set([]);
        this.loading.set(false);
        this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.');
      },
    });
  }

  toggleFilter(): void {
    this.showActiveOnly = !this.showActiveOnly;
    this.loadAssignments();
  }

  openNoteModal(assignment: Assignment): void {
    if (this.savingNote() || this.closing()) return;
    this.resetDialogs();
    this.editingAssignment.set(assignment);
    this.showNoteModal.set(true);
    this.loadNotes();
  }

  closeNoteModal(): void {
    if (!this.savingNote()) this.resetDialogs();
  }

  loadNotes(): void {
    const assignment = this.editingAssignment();
    if (!assignment || !this.showNoteModal() || this.savingNote()) return;
    const version = ++this.notesVersion;
    this.notesRequest?.unsubscribe();
    this.caseNotes.set(null);
    this.noteError.set('');
    this.loadingNotes.set(true);
    this.notesRequest = this.assignmentService.getAssignmentNotes(assignment.id).subscribe({
      next: result => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.caseNotes.set(result);
        this.loadingNotes.set(false);
      },
      error: err => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.loadingNotes.set(false);
        this.noteError.set(err?.error?.error || 'No se pudieron cargar las notas del caso. Vuelve a intentarlo.');
      },
    });
  }

  notesFor(category: string) {
    return this.caseNotes()?.notes.filter(note => note.metadata?.category === category) ?? [];
  }

  get canAddNote(): boolean {
    const assignment = this.editingAssignment();
    return !!assignment && !!this.caseNotes()?.can_add && !this.loadingNotes() &&
      this.isCurrent(assignment) && (this.auth.isAdmin() || this.auth.isSupervisor() ||
        (this.auth.isTechnician() && assignment.user_id === this.auth.currentUser()?.id));
  }

  saveNote(): void {
    const a = this.editingAssignment();
    if (!a || !this.canAddNote || this.savingNote()) return;
    const error = textError(this.noteText, { label: 'Nota', min: 5, max: 2000, letters: 2, required: true });
    if (error) { this.noteError.set(error); return; }
    const version = this.notesVersion;
    this.noteError.set('');
    this.savingNote.set(true);
    this.writeRequest = this.assignmentService.addAssignmentNote(a.id, this.noteText.trim()).subscribe({
      next: ({ message, note }) => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.caseNotes.update(current => current ? { ...current, notes: [...current.notes, note] } : current);
        this.noteText = '';
        this.savingNote.set(false);
        this.successMsg.set(message);
      },
      error: err => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.savingNote.set(false);
        this.noteError.set(err?.error?.error || 'No se pudo añadir la nota. Comprueba las notas antes de reintentar.');
        if (err?.status === 403 || err?.status === 409) {
          this.caseNotes.update(current => current ? { ...current, can_add: false } : current);
        }
      },
    });
  }

  private isCurrent(a: Assignment): boolean {
    return !a.completed_at && !['Cerrado', 'Anulado'].includes(a.alert_state || '') &&
      !['Completada', 'Reasignada', 'Anulada'].includes(a.status || '');
  }

  canEdit(a: Assignment): boolean {
    return this.isCurrent(a) && (this.auth.isAdmin() || (this.auth.isTechnician() && a.user_id === this.auth.currentUser()?.id));
  }

  openCloseModal(a: Assignment): void {
    if (!this.canEdit(a) || this.savingNote() || this.closing()) return;
    this.resetDialogs();
    this.editingAssignment.set(a);
    this.solutionText = '';
    this.showCloseModal.set(true);
  }

  closeCloseModal(): void { if (!this.closing()) this.resetDialogs(); }

  completeAssignment(): void {
    const assignment = this.editingAssignment();
    if (!assignment || !this.canEdit(assignment) || this.closing()) return;
    if (!this.solutionText.trim()) {
      this.errorMsg.set('Debes registrar la solución aplicada');
      return;
    }
    const error = textError(this.solutionText, { label: 'Solución', min: 5, max: 2000, letters: 2, required: true });
    if (error) { this.errorMsg.set(error); return; }
    const version = this.notesVersion;
    this.closing.set(true);
    this.writeRequest = this.assignmentService.updateAssignment(assignment.id, {
      complete: true, solution: this.solutionText.trim(),
    }).subscribe({
      next: ({ message }) => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.closing.set(false);
        this.successMsg.set(message);
        this.closeCloseModal();
        this.loadAssignments();
      },
      error: err => {
        if (this.destroyed || version !== this.notesVersion) return;
        this.closing.set(false);
        this.errorMsg.set(err?.error?.error || 'No se pudo cerrar la atención');
      },
    });
  }
}
