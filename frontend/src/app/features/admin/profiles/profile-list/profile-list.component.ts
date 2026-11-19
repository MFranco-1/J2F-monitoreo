import { runtimeCatalog } from '../../../../core/runtime-catalog';
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../../../core/services/user.service';
import { Profile, State } from '../../../../shared/models/user.model';
import { firstError, validateForm } from '../../../../shared/validation';

@Component({
  selector: 'app-profile-list',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './profile-list.component.html',
  styleUrl: './profile-list.component.scss',
})
export class ProfileListComponent implements OnInit {
  readonly permissions = runtimeCatalog.permissions;
  private userService = inject(UserService);

  profiles = signal<Profile[]>([]);
  states = signal<State[]>([]);
  private activeStateId(): number {
    return this.states().find((s) => s.is_active === true)?.id ?? 0;
  }
  loading = signal(true);
  showModal = signal(false);
  saving = signal(false);
  editingProfile = signal<Profile | null>(null);
  successMsg = signal('');
  errorMsg = signal('');

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
      error: (err) => {
        this.loading.set(false);
        this.errorMsg.set(err?.error?.error || 'No se pudieron cargar los perfiles');
      },
    });
  }

  openNew(): void {
    this.editingProfile.set(null);
    this.form = { name: '', description: '', state_id: this.activeStateId(), permissions: [] };
    this.showModal.set(true);
  }

  openEdit(profile: Profile): void {
    this.editingProfile.set(profile);
    this.form = {
      permissions: [...(profile.permissions || [])],
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

  togglePermission(code: string, checked: boolean): void {
    const permissions = new Set(this.form.permissions || []);
    if (checked) permissions.add(code); else permissions.delete(code);
    this.form.permissions = [...permissions];
  }

  save(): void {
    if (this.saving()) return;
    const error = firstError(validateForm('profiles', this.form));
    if (error) {
      this.errorMsg.set(error);
      return;
    }
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
      error: (err) => {
        this.saving.set(false);
        this.errorMsg.set(err?.error?.error || 'Error al guardar');
      },
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
    return profile.state?.is_active === true ? 'badge-active' : 'badge-inactive';
  }
}
