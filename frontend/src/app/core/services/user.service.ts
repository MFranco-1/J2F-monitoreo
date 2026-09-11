// core/services/user.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, Subject, tap } from 'rxjs';
import { User, Profile, MenuOption, State } from '../../shared/models/user.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class UserService {
  private readonly BASE = environment.apiUrl;
  readonly menuChanges = new Subject<void>();

  constructor(private http: HttpClient) {}

  // --- Users ---
  getUsers(filters: { state?: string; profile_id?: number; search?: string } = {}): Observable<{ users: User[] }> {
    let params = new HttpParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) params = params.set(k, String(v)); });
    return this.http.get<{ users: User[] }>(`${this.BASE}/users/`, { params });
  }

  getUserById(id: number): Observable<{ user: User }> {
    return this.http.get<{ user: User }>(`${this.BASE}/users/${id}`);
  }

  createUser(data: Partial<User> & { password: string }): Observable<{ user: User; message: string }> {
    return this.http.post<{ user: User; message: string }>(`${this.BASE}/users/`, data);
  }

  updateUser(id: number, data: Partial<User> & { password?: string }): Observable<{ user: User; message: string }> {
    return this.http.put<{ user: User; message: string }>(`${this.BASE}/users/${id}`, data);
  }

  deleteUser(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.BASE}/users/${id}`);
  }

  // --- Profiles ---
  getProfiles(): Observable<{ profiles: Profile[]; states: State[] }> {
    return this.http.get<{ profiles: Profile[]; states: State[] }>(`${this.BASE}/profiles/`);
  }

  getProfileById(id: number): Observable<{ profile: Profile }> {
    return this.http.get<{ profile: Profile }>(`${this.BASE}/profiles/${id}`);
  }

  createProfile(data: Partial<Profile> & { menu_option_ids?: number[] }): Observable<{ profile: Profile; message: string }> {
    return this.http.post<{ profile: Profile; message: string }>(`${this.BASE}/profiles/`, data).pipe(tap(() => this.menuChanges.next()));
  }

  updateProfile(id: number, data: Partial<Profile> & { menu_option_ids?: number[] }): Observable<{ profile: Profile; message: string }> {
    return this.http.put<{ profile: Profile; message: string }>(`${this.BASE}/profiles/${id}`, data).pipe(tap(() => this.menuChanges.next()));
  }

  deleteProfile(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.BASE}/profiles/${id}`).pipe(tap(() => this.menuChanges.next()));
  }

  // --- Menu Options ---
  getMenuOptions(parentOnly = false, navigation = false): Observable<{ menu_options: MenuOption[]; configured?: boolean }> {
    let params = parentOnly ? new HttpParams().set('parent_only', 'true') : new HttpParams();
    if (navigation) params = params.set('navigation', 'true');
    return this.http.get<{ menu_options: MenuOption[]; configured?: boolean }>(`${this.BASE}/menu-options/`, { params });
  }

  createMenuOption(data: Partial<MenuOption> & { profile_ids?: number[] }): Observable<{ menu_option: MenuOption; message: string }> {
    return this.http.post<{ menu_option: MenuOption; message: string }>(`${this.BASE}/menu-options/`, data).pipe(tap(() => this.menuChanges.next()));
  }

  updateMenuOption(id: number, data: Partial<MenuOption> & { profile_ids?: number[] }): Observable<{ menu_option: MenuOption; message: string }> {
    return this.http.put<{ menu_option: MenuOption; message: string }>(`${this.BASE}/menu-options/${id}`, data).pipe(tap(() => this.menuChanges.next()));
  }

  deleteMenuOption(id: number): Observable<{ message: string }> {
    return this.http.delete<{ message: string }>(`${this.BASE}/menu-options/${id}`).pipe(tap(() => this.menuChanges.next()));
  }
}
