// features/history/history-list/history-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AssignmentService } from '../../../core/services/assignment.service';
import { HistoryEntry } from '../../../shared/models/assignment.model';

@Component({
  selector: 'app-history-list',
  standalone: true,
  imports: [NgFor, NgIf, DatePipe, FormsModule],
  templateUrl: './history-list.component.html',
  styleUrl: './history-list.component.scss',
})
export class HistoryListComponent implements OnInit {
  private assignmentService = inject(AssignmentService);

  history = signal<HistoryEntry[]>([]);
  loading = signal(true);
  errorMsg = signal('');
  total = signal(0);
  totalPages = signal(1);

  filters: any = { page: 1, per_page: 30 };

  ngOnInit(): void { this.loadHistory(); }

  loadHistory(): void {
    this.loading.set(true);
    this.assignmentService.getGlobalHistory(this.filters).subscribe({
      next: ({ history, total, pages }) => {
        this.history.set(history);
        this.total.set(total);
        this.totalPages.set(pages);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudo cargar el historial'); },
    });
  }

  applyFilter(field: string, value: string): void {
    this.filters[field] = value || undefined;
    this.filters.page = 1;
    this.loadHistory();
  }

  prevPage(): void { if (this.filters.page > 1) { this.filters.page--; this.loadHistory(); } }
  nextPage(): void { if (this.filters.page < this.totalPages()) { this.filters.page++; this.loadHistory(); } }

  getActionLabel(action: string): string {
    const map: Record<string, string> = {
      created: ' Creada', state_changed: ' Estado cambiado',
      assigned: ' Asignada', escalated: ' Escalada',
      closed: ' Cerrada', updated: ' Actualizada', note_added: ' Nota',
    };
    return map[action] ?? action;
  }
}
