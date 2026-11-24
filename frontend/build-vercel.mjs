import { execFileSync } from 'node:child_process';

const origin = new URL(process.env.J2F_BACKEND_ORIGIN);
if (origin.protocol !== 'https:' || origin.href !== origin.origin + '/') {
  throw new Error('J2F_BACKEND_ORIGIN debe ser el origen HTTPS del backend.');
}
execFileSync(process.execPath, [
  'node_modules/@angular/cli/bin/ng.js', 'build',
  '--define', 'J2F_API_URL=' + JSON.stringify(origin.origin + '/api'),
], { stdio: 'inherit' });
