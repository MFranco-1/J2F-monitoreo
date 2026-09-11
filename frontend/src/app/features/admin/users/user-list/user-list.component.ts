// features/admin/users/user-list/user-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../../../core/services/user.service';
import { User, Profile, State } from '../../../../shared/models/user.model';

@Component({
  selector: 'app-user-list',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './user-list.component.html',
  styleUrl: './user-list.component.scss',
})
export class UserListComponent implements OnInit {
  private userService = inject(UserService);

  users = signal<User[]>([]);
  profiles = signal<Profile[]>([]);
  states = signal<State[]>([]);
  private activeStateId(): number { return this.states().find(s => s.name === 'Activo')?.id ?? 0; }
  loading = signal(true);
  showModal = signal(false);
  saving = signal(false);
  editingUser = signal<User | null>(null);
  successMsg = signal('');
  errorMsg = signal('');
  searchTerm = '';
  private requestVersion = 0;

  form: any = {
    dni: '', full_name: '', email: '',
    password: '', profile_id: null as number | null, state_id: this.activeStateId(),
  };

  ngOnInit(): void {
    this.loadUsers();
    this.userService.getProfiles().subscribe({
      next: ({ profiles, states }) => { this.profiles.set(profiles); this.states.set(states); },
      error: () => this.errorMsg.set('No se pudieron cargar los perfiles y estados')
    });
  }

  loadUsers(): void {
    const version = ++this.requestVersion;
    this.loading.set(true);
    this.userService.getUsers({ search: this.searchTerm }).subscribe({
      next: ({ users }) => { if (version !== this.requestVersion) return; this.users.set(users); this.loading.set(false); },
      error: (err) => { if (version !== this.requestVersion) return; this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los usuarios'); },
    });
  }

  openNew(): void {
    this.editingUser.set(null);
    this.form = { dni: '', full_name: '', email: '', password: '', profile_id: null as number | null, state_id: this.activeStateId() };
    this.showModal.set(true);
  }

  openEdit(user: User): void {
    this.editingUser.set(user);
    this.form = {
      dni: user.dni, full_name: user.full_name, email: user.email,
      password: '', profile_id: user.profile_id ?? null, state_id: user.state_id,
    };
    this.showModal.set(true);
  }

  closeModal(): void { if (this.saving()) return; this.showModal.set(false); this.errorMsg.set(''); }

  save(): void {
    if (this.saving()) return;
    this.saving.set(true);
    const editing = this.editingUser();
    const obs = editing
      ? this.userService.updateUser(editing.id, this.form)
      : this.userService.createUser(this.form);

    obs.subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeModal();
        this.loadUsers();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => { this.saving.set(false); this.errorMsg.set(err?.error?.error || 'Error al guardar'); },
    });
  }

  delete(user: User): void {
    if (!confirm(`¿Desactivar al usuario "${user.full_name}"? Se conservará su historial.`)) return;
    this.userService.deleteUser(user.id).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.loadUsers();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error'),
    });
  }

  onSearch(): void { this.loadUsers(); }
  getStateBadge(user: User): string {
    return user.state?.name === 'Activo' ? 'badge-active' : 'badge-inactive';
  }
}
