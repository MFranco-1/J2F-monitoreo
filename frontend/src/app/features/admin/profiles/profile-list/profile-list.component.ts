// features/admin/profiles/profile-list/profile-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../../../core/services/user.service';
import { Profile, State } from '../../../../shared/models/user.model';

@Component({
  selector: 'app-profile-list',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './profile-list.component.html',
  styleUrl: './profile-list.component.scss',
})
export class ProfileListComponent implements OnInit {
  private userService = inject(UserService);

  profiles = signal<Profile[]>([]);
  states = signal<State[]>([]);
  private activeStateId(): number { return this.states().find(s => s.name === 'Activo')?.id ?? 0; }
  loading = signal(true);
  showModal = signal(false);
  saving = signal(false);
  editingProfile = signal<Profile | null>(null);
  successMsg = signal('');
  errorMsg = signal('');

  // Form model
  form: Partial<Profile> & { state_id: number } = {
    name: '',
    description: '',
    state_id: this.activeStateId(),
  };

  ngOnInit(): void {
    this.loadProfiles();
  }

  loadProfiles(): void {
    this.loading.set(true);
    this.userService.getProfiles().subscribe({
      next: ({ profiles, states }) => {
        this.states.set(states);
        this.profiles.set(profiles);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los perfiles'); },
    });
  }

  openNew(): void {
    this.editingProfile.set(null);
    this.form = { name: '', description: '', state_id: this.activeStateId() };
    this.showModal.set(true);
  }

  openEdit(profile: Profile): void {
    this.editingProfile.set(profile);
    this.form = {
      name: profile.name,
      description: profile.description,
      state_id: profile.state_id,
    };
    this.showModal.set(true);
  }

  closeModal(): void {
    if (this.saving()) return;
    this.showModal.set(false);
    this.errorMsg.set('');
  }

  save(): void {
    if (this.saving()) return;
    this.saving.set(true);
    const editing = this.editingProfile();
    const obs = editing
      ? this.userService.updateProfile(editing.id, this.form)
      : this.userService.createProfile(this.form);

    obs.subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeModal();
        this.loadProfiles();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => { this.saving.set(false); this.errorMsg.set(err?.error?.error || 'Error al guardar'); },
    });
  }

  delete(profile: Profile): void {
    if (!confirm(`¿Eliminar el perfil "${profile.name}"?`)) return;
    this.userService.deleteProfile(profile.id).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.loadProfiles();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error al eliminar'),
    });
  }

  getStateBadge(profile: Profile): string {
    return profile.state?.name === 'Activo' ? 'badge-active' : 'badge-inactive';
  }
}
