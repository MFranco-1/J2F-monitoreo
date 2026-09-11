import { HttpInterceptorFn, HttpErrorResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError, switchMap } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { environment } from '../../../environments/environment';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const base = environment.apiUrl.replace(/\/$/, '');
  if (req.url !== base && !req.url.startsWith(base + '/')) return next(req);
  const auth = inject(AuthService);
  const token = auth.getToken();
  const authReq = token && !req.headers.has('Authorization') && !req.url.endsWith('/auth/login')
    ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(authReq).pipe(catchError((error: HttpErrorResponse) => {
    if (error.status !== 401 || req.url.startsWith(base + '/auth/')) {
      return throwError(() => error);
    }
    return auth.refreshToken().pipe(
      catchError(refreshError => {
        auth.endSession();
        return throwError(() => refreshError);
      }),
      switchMap(response => next(req.clone({
        setHeaders: { Authorization: `Bearer ${response.access_token}` }
      })))
    );
  }));
};
