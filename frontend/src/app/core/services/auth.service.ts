import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, Subject, tap, throwError, finalize, shareReplay } from 'rxjs';
import { AuthResponse, CurrentUser } from '../../shared/models/user.model';
import { environment } from '../../../environments/environment';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'j2f_access_token';
  private readonly REFRESH_KEY = 'j2f_refresh_token';
  private readonly USER_KEY = 'j2f_user';
  private _currentUser = signal<CurrentUser | null>(this.loadSession());
  private refreshInFlight?: Observable<{ access_token: string }>;
  readonly profileChanges = new Subject<void>();
  readonly currentUser = this._currentUser.asReadonly();
  readonly isAuthenticated = computed(() => !!this._currentUser() && !!this.getToken());
  readonly requiresProfileSelection = computed(() => !!this._currentUser()?.requires_profile_selection);
  readonly hasActiveProfile = computed(() => !!this._currentUser()?.profile && !this.requiresProfileSelection());
  readonly availableProfiles = computed(() => this._currentUser()?.profiles || []);
  readonly isAdmin = computed(() => this.hasRole('administrador'));
  readonly isOperator = computed(() => this.hasRole('tecnico') || this.hasRole('operador'));
  readonly roleNames = computed(() => this._currentUser()?.profile?.name || 'Perfil pendiente');

  constructor(private http: HttpClient, private router: Router) {}

  private hasRole(role: string): boolean {
    const profile = this._currentUser()?.profile;
    return !!profile && profile.state?.name === 'Activo' &&
      profile.name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase() === role;
  }

  login(identifier: string, password: string): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${environment.apiUrl}/auth/login`, { identifier, password }).pipe(
      tap(response => this.storeResponse(response))
    );
  }

  selectProfile(profileId: number): Observable<AuthResponse> {
    return this.http.post<AuthResponse>(`${environment.apiUrl}/auth/select-profile`, { profile_id: profileId }).pipe(
      tap(response => {
        this.storeResponse(response);
        this.profileChanges.next();
      })
    );
  }

  private storeResponse(response: AuthResponse): void {
    localStorage.setItem(this.TOKEN_KEY, response.access_token);
    if (response.refresh_token) localStorage.setItem(this.REFRESH_KEY, response.refresh_token);
    else localStorage.removeItem(this.REFRESH_KEY);
    const user = response.user;
    const current: CurrentUser = {
      id: user.id, email: user.email, full_name: user.full_name,
      profile: response.requires_profile_selection ? null : (user.profile || null),
      profiles: response.profiles || user.profiles || [],
      requires_profile_selection: response.requires_profile_selection,
    };
    localStorage.setItem(this.USER_KEY, JSON.stringify(current));
    this._currentUser.set(current);
  }

  logout(): void {
    const token = localStorage.getItem(this.REFRESH_KEY) || this.getToken();
    if (token) this.http.post(`${environment.apiUrl}/auth/logout`, {}, {
      headers: { Authorization: `Bearer ${token}` }
    }).subscribe({ error: () => {} });
    this.endSession();
  }

  endSession(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.USER_KEY);
    this._currentUser.set(null);
    this.router.navigate(['/login']);
  }

  getToken(): string | null { return localStorage.getItem(this.TOKEN_KEY); }

  refreshToken(): Observable<{ access_token: string }> {
    if (this.refreshInFlight) return this.refreshInFlight;
    const refreshToken = localStorage.getItem(this.REFRESH_KEY);
    if (!refreshToken) return throwError(() => new Error('No hay sesión definitiva para renovar'));
    this.refreshInFlight = this.http.post<{ access_token: string }>(
      `${environment.apiUrl}/auth/refresh`, {},
      { headers: { Authorization: `Bearer ${refreshToken}` } }
    ).pipe(
      tap(({ access_token }) => {
        if (localStorage.getItem(this.REFRESH_KEY) !== refreshToken) throw new Error('La sesión cambió');
        localStorage.setItem(this.TOKEN_KEY, access_token);
      }),
      finalize(() => { this.refreshInFlight = undefined; }),
      shareReplay({ bufferSize: 1, refCount: false })
    );
    return this.refreshInFlight;
  }

  private loadSession(): CurrentUser | null {
    try {
      const value = JSON.parse(localStorage.getItem(this.USER_KEY) || 'null');
      return value && Number.isInteger(value.id) && typeof value.full_name === 'string'
        && Array.isArray(value.profiles) && typeof value.requires_profile_selection === 'boolean'
        && localStorage.getItem(this.TOKEN_KEY) ? value : null;
    } catch { return null; }
  }
}
