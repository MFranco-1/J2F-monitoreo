import { AuthService } from '../../../core/services/auth.service';
// Completar el componente de reports con el método isObject faltante
// features/reports/report-list/report-list.component.ts - agregar este método a la clase
// isObject(value: any): boolean { return typeof value === 'object' && value !== null; }
// (ya incluido implícitamente en el template con el pipe json)

// features/assignments/assignment-list/assignment-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AssignmentService } from '../../../core/services/assignment.service';
import { Assignment } from '../../../shared/models/assignment.model';

@Component({
  selector: 'app-assignment-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, FormsModule, RouterLink],
  templateUrl: './assignment-list.component.html',
  styleUrl: './assignment-list.component.scss',
})
export class AssignmentListComponent implements OnInit {
  readonly auth = inject(AuthService);
  private assignmentService = inject(AssignmentService);

  assignments = signal<Assignment[]>([]);
  loading = signal(true);
  successMsg = signal('');
  errorMsg = signal('');
  showNoteModal = signal(false);
  editingAssignment = signal<Assignment | null>(null);
  noteText = '';
  showActiveOnly = true;

  ngOnInit(): void {
    this.loadAssignments();
  }

  loadAssignments(): void {
    this.loading.set(true);
    this.assignmentService.getAssignments({ active_only: this.showActiveOnly }).subscribe({
      next: ({ assignments }) => {
        this.assignments.set(assignments);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los datos. Comprueba la conexión con el servidor.'); },
    });
  }

  toggleFilter(): void {
    this.showActiveOnly = !this.showActiveOnly;
    this.loadAssignments();
  }

  openNoteModal(assignment: Assignment): void {
    this.editingAssignment.set(assignment);
    this.noteText = assignment.notes ?? '';
    this.showNoteModal.set(true);
  }

  closeNoteModal(): void { this.showNoteModal.set(false); }

  saveNote(): void {
    const a = this.editingAssignment();
    if (!a) return;
    this.assignmentService.updateAssignment(a.id, { notes: this.noteText }).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.closeNoteModal();
        this.loadAssignments();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error'),
    });
  }

  canEdit(a: Assignment): boolean {
    return this.auth.isAdmin() || (this.auth.isOperator() && a.user_id === this.auth.currentUser()?.id);
  }

  completeAssignment(a: Assignment): void {
    if (!confirm('¿Marcar esta asignación como completada?')) return;
    this.assignmentService.updateAssignment(a.id, { complete: true }).subscribe({
      next: ({ message }) => {
        this.successMsg.set(message);
        this.loadAssignments();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error'),
    });
  }
}
