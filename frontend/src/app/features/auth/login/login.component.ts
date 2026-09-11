// features/auth/login/login.component.ts
import { Component, signal, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { NgIf } from '@angular/common';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, NgIf],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {
  private authService = inject(AuthService);
  private router = inject(Router);

  identifier = '';
  password = '';
  loading = signal(false);
  errorMsg = signal('');

  onSubmit(): void {
    if (this.loading()) return;
    if (!this.identifier || !this.password) {
      this.errorMsg.set('Ingresa tu usuario y contraseña');
      return;
    }
    this.loading.set(true);
    this.errorMsg.set('');

    this.authService.login(this.identifier, this.password).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: (err) => {
        this.loading.set(false);
        this.errorMsg.set(
          err?.error?.error || 'Credenciales inválidas. Intenta nuevamente.'
        );
      },
      complete: () => this.loading.set(false),
    });
  }
}
