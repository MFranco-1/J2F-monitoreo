// features/admin/menu-options/menu-option-list/menu-option-list.component.ts
import { Component, OnInit, signal, inject } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { UserService } from '../../../../core/services/user.service';
import { MenuOption, Profile, State } from '../../../../shared/models/user.model';

@Component({
  selector: 'app-menu-option-list',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './menu-option-list.component.html',
  styleUrl: './menu-option-list.component.scss',
})
export class MenuOptionListComponent implements OnInit {
  private userService = inject(UserService);

  menuOptions = signal<MenuOption[]>([]);
  profiles = signal<Profile[]>([]);
  parentOptions = signal<MenuOption[]>([]);
  states = signal<State[]>([]);
  private activeStateId(): number { return this.states().find(s => s.name === 'Activo')?.id ?? 0; }
  loading = signal(true);
  showModal = signal(false);
  saving = signal(false);
  editingOption = signal<MenuOption | null>(null);
  successMsg = signal('');
  errorMsg = signal('');

  form: any = {
    name: '', url: '',
    parent_id: null, order: 0, state_id: this.activeStateId(),
    profile_ids: [] as number[],
  };

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.loading.set(true);
    this.userService.getMenuOptions().subscribe({
      next: ({ menu_options }) => {
        this.menuOptions.set(menu_options);
        this.parentOptions.set(menu_options);
        this.loading.set(false);
      },
      error: (err) => { this.loading.set(false); this.errorMsg.set(err?.error?.error || 'No se pudieron cargar las opciones'); },
    });
    this.userService.getProfiles().subscribe({
      next: ({ profiles, states }) => { this.profiles.set(profiles); this.states.set(states); },
      error: () => this.errorMsg.set('No se pudieron cargar los perfiles y estados')
    });
  }

  openNew(): void {
    this.editingOption.set(null);
    this.parentOptions.set(this.menuOptions());
    this.form = { name: '', url: '', parent_id: null, order: 0, state_id: this.activeStateId(), profile_ids: [] };
    this.showModal.set(true);
  }

  openEdit(opt: MenuOption): void {
    this.editingOption.set(opt);
    this.parentOptions.set(this.menuOptions().filter(o => o.id !== opt.id));
    this.form = {
      name: opt.name, url: opt.url,
      parent_id: opt.parent_id, order: opt.order ?? 0, state_id: opt.state_id,
      profile_ids: (opt.profiles ?? []).map((p) => p.id),
    };
    this.showModal.set(true);
  }

  closeModal(): void { if (this.saving()) return; this.showModal.set(false); this.errorMsg.set(''); }

  toggleProfile(profileId: number): void {
    const ids: number[] = this.form.profile_ids;
    const idx = ids.indexOf(profileId);
    if (idx > -1) ids.splice(idx, 1);
    else ids.push(profileId);
  }

  isProfileSelected(profileId: number): boolean {
    return this.form.profile_ids.includes(profileId);
  }

  save(): void {
    if (this.saving()) return;
    this.saving.set(true);
    const editing = this.editingOption();
    const obs = editing
      ? this.userService.updateMenuOption(editing.id, this.form)
      : this.userService.createMenuOption(this.form);

    obs.subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.closeModal();
        this.loadData();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => { this.saving.set(false); this.errorMsg.set(err?.error?.error || 'Error al guardar'); },
    });
  }

  delete(opt: MenuOption): void {
    if (!confirm(`¿Eliminar la opción "${opt.name}"?`)) return;
    this.userService.deleteMenuOption(opt.id).subscribe({
      next: ({ message }) => {
        this.saving.set(false);
        this.successMsg.set(message);
        this.loadData();
        setTimeout(() => this.successMsg.set(''), 3000);
      },
      error: (err) => this.errorMsg.set(err?.error?.error || 'Error'),
    });
  }

  getStateBadge(opt: MenuOption): string {
    return opt.state?.name === 'Activo' ? 'badge-active' : 'badge-inactive';
  }

  getProfileNames(opt: MenuOption): string {
    return (opt.profiles ?? []).map((p) => p.name).join(', ') || '—';
  }

  getParentName(opt: MenuOption): string {
    return opt.parent?.name ?? '—';
  }
}
