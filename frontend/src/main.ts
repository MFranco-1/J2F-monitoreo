import { bootstrapApplication } from '@angular/platform-browser';
import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';

bootstrapApplication(AppComponent, appConfig).catch((error) => {
  console.error(error);
  const host = document.querySelector('app-root');
  if (host) host.textContent = 'No se pudo iniciar J2F. Comprueba el backend y la instalación de los scripts SQL; después recarga la página.';
});
