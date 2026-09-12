// Ejecuta el servicio e interceptor reales con transporte HTTP controlado.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import * as rx from 'rxjs';
import '@angular/compiler';
import * as angular from '@angular/core';
import * as http from '@angular/common/http';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let injectedAuth;
const cache = new Map();
const imports = {
  '@angular/core': { ...angular, Component: () => value => value,
    Injectable: () => value => value, inject: () => injectedAuth },
  '@angular/common': {},
  '@angular/common/http': http,
  '@angular/forms': {},
  '@angular/router': {},
  rxjs: rx,
};
function load(relative) {
  const filename = path.resolve(root, relative);
  if (cache.has(filename)) return cache.get(filename);
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      experimentalDecorators: true }
  }).outputText;
  const require = id => {
    if (imports[id]) return imports[id];
    if (id.startsWith('.')) return load(path.resolve(path.dirname(filename), id + '.ts'));
    throw new Error('Import no previsto: ' + id);
  };
  vm.runInThisContext('(function(require,module,exports){' + compiled + '\n})', { filename })(
    require, module, module.exports);
  cache.set(filename, module.exports);
  return module.exports;
}
const { AuthService } = load('src/app/core/services/auth.service.ts');
const { authInterceptor } = load('src/app/core/interceptors/auth.interceptor.ts');
const { UserService } = load('src/app/core/services/user.service.ts');
const { SidebarComponent } = load('src/app/layout/sidebar/sidebar.component.ts');
const { MenuOptionListComponent } = load('src/app/features/admin/menu-options/menu-option-list/menu-option-list.component.ts');
const { environment } = load('src/environments/environment.ts');

function setup() {
  const storage = new Map([
    ['j2f_access_token', 'old-access'], ['j2f_refresh_token', 'actual-refresh'],
    ['j2f_user', JSON.stringify({ id: 2, email: 'test@example.invalid', full_name: 'Prueba',
      profile: { id: 2, name: 'Técnico', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } },
      profiles: [{ id: 2, name: 'Técnico', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } }],
      requires_profile_selection: false })]
  ]);
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key)
  }});
  const pending = [];
  const navigations = [];
  const backend = request => {
    const response = new rx.Subject();
    pending.push({ request, response });
    return response;
  };
  const request = (method, url, body, options = {}) => rx.defer(() => {
    const req = new http.HttpRequest(method, url, body, { headers: new http.HttpHeaders(options.headers || {}) });
    return authInterceptor(req, backend).pipe(rx.map(event => event.body));
  });
  const client = { post: (url, body, options) => request('POST', url, body, options) };
  const auth = new AuthService(client, { navigate: value => navigations.push(value) });
  injectedAuth = auth;
  const success = (index, body) => {
    pending[index].response.next(new http.HttpResponse({ body }));
    pending[index].response.complete();
  };
  const fail = (index, status) => pending[index].response.error(new http.HttpErrorResponse({ status }));
  return { auth, pending, navigations, success, fail,
    get: route => request('GET', environment.apiUrl + route, null),
    outside: url => request('GET', url, null) };
}

test('conserva el refresh token explícito en Authorization', () => {
  const t = setup();
  t.auth.refreshToken().subscribe();
  assert.equal(t.pending[0].request.headers.get('Authorization'), 'Bearer actual-refresh');
  t.success(0, { access_token: 'new-access' });
  assert.equal(t.auth.getToken(), 'new-access');
});

test('dos respuestas 401 comparten una renovación y reintentan con el token nuevo', () => {
  const t = setup();
  const results = [];
  t.get('/alerts/').subscribe(value => results.push(value));
  t.get('/reports/').subscribe(value => results.push(value));
  t.fail(0, 401);
  t.fail(1, 401);
  assert.equal(t.pending.length, 3);
  assert.ok(t.pending[2].request.url.endsWith('/auth/refresh'));
  t.success(2, { access_token: 'new-access' });
  assert.equal(t.pending.length, 5);
  for (const index of [3, 4]) {
    assert.equal(t.pending[index].request.headers.get('Authorization'), 'Bearer new-access');
    t.success(index, { ok: true });
  }
  assert.equal(results.length, 2);
  assert.equal(t.navigations.length, 0);
});

test('logout envía el refresh token y borra la sesión local', () => {
  const t = setup();
  t.auth.logout();
  assert.equal(t.pending[0].request.headers.get('Authorization'), 'Bearer actual-refresh');
  assert.equal(t.auth.getToken(), null);
  assert.equal(t.auth.isAuthenticated(), false);
  t.success(0, { message: 'OK' });
});

test('no envía credenciales a dominios externos', () => {
  const t = setup();
  t.outside('https://example.invalid/data').subscribe();
  assert.equal(t.pending[0].request.headers.has('Authorization'), false);
  t.success(0, {});
});

test('un refresh rechazado termina la sesión sin nuevas peticiones en bucle', () => {
  const t = setup();
  const errors = [];
  t.get('/alerts/').subscribe({ error: error => errors.push(error.status) });
  t.fail(0, 401);
  t.fail(1, 401);
  assert.equal(t.pending.length, 2);
  assert.equal(t.auth.getToken(), null);
  assert.deepEqual(errors, [401]);
});

test('una renovación pendiente no restaura una sesión ya cerrada', () => {
  const t = setup();
  const errors = [];
  t.auth.refreshToken().subscribe({ error: error => errors.push(error.message) });
  t.auth.endSession();
  t.success(0, { access_token: 'obsolete-response' });
  assert.equal(t.auth.getToken(), null);
  assert.equal(errors.length, 1);
});

test('un 403 en el reintento no elimina una sesión válida', () => {
  const t = setup();
  const errors = [];
  t.get('/users/').subscribe({ error: error => errors.push(error.status) });
  t.fail(0, 401);
  t.success(1, { access_token: 'new-access' });
  t.fail(2, 403);
  assert.deepEqual(errors, [403]);
  assert.equal(t.auth.getToken(), 'new-access');
  assert.equal(t.navigations.length, 0);
});


test('login conserva el perfil único sin asumir que Activo tiene id 1', () => {
  const t = setup();
  t.auth.login('prueba', 'clave').subscribe();
  t.success(0, { access_token: 'login-access', refresh_token: 'login-refresh',
    requires_profile_selection: false,
    profiles: [{ id: 4, name: 'Administrador', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } }],
    user: { id: 3, email: 'test@example.invalid', full_name: 'Prueba', profile_id: 4,
      profile: { id: 4, name: 'Administrador', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } } } });
  assert.equal(t.auth.currentUser().profile.id, 4);
  assert.equal(t.auth.isAdmin(), true);
  assert.equal(t.auth.isTechnician(), false);
  assert.equal(t.auth.isOperator(), false);
  assert.equal(t.auth.canAssign(), true);
  assert.equal(t.auth.roleNames(), 'Administrador');
});

test('un perfil inactivo no concede permisos en la interfaz', () => {
  const t = setup();
  t.auth.login('prueba', 'clave').subscribe();
  t.success(0, { access_token: 'login-access', refresh_token: 'login-refresh',
    requires_profile_selection: false,
    profiles: [{ id: 1, name: 'Administrador', state_id: 29, state: { id: 29, name: 'Inactivo', type: 'user' } }],
    user: { id: 3, email: 'test@example.invalid', full_name: 'Prueba',
      profile: { id: 1, name: 'Administrador', state_id: 29, state: { id: 29, name: 'Inactivo', type: 'user' } } } });
  assert.equal(t.auth.isAdmin(), false);
  assert.equal(t.auth.isTechnician(), false);
  assert.equal(t.auth.isOperator(), false);
  assert.equal(t.auth.canAssign(), false);
});

test('el perfil Técnico se reconoce al restaurar una sesión', () => {
  const t = setup();
  assert.equal(t.auth.isAuthenticated(), true);
  assert.equal(t.auth.isTechnician(), true);
  assert.equal(t.auth.isOperator(), false);
  assert.equal(t.auth.canAssign(), false);
  assert.equal(t.auth.isAdmin(), false);
});

test('el perfil Operador asigna alertas pero no actúa como Técnico', () => {
  const t = setup();
  t.auth.login('operador', 'clave').subscribe();
  const profile = { id: 3, name: 'Operador', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } };
  t.success(0, { access_token: 'operator-access', refresh_token: 'operator-refresh',
    requires_profile_selection: false, profiles: [profile],
    user: { id: 4, email: 'operator@example.invalid', full_name: 'Operador Prueba', profile, profiles: [profile] } });
  assert.equal(t.auth.isOperator(), true);
  assert.equal(t.auth.isTechnician(), false);
  assert.equal(t.auth.canAssign(), true);
});

test('el perfil Supervisor puede asignar sin actuar como Técnico', () => {
  const t = setup();
  t.auth.login('supervisor', 'clave').subscribe();
  const profile = { id: 4, name: 'Supervisor', state_id: 17, state: { id: 17, name: 'Activo', type: 'user' } };
  t.success(0, { access_token: 'supervisor-access', refresh_token: 'supervisor-refresh',
    requires_profile_selection: false, profiles: [profile],
    user: { id: 5, email: 'supervisor@example.invalid', full_name: 'Supervisor Prueba', profile, profiles: [profile] } });
  assert.equal(t.auth.isSupervisor(), true);
  assert.equal(t.auth.isOperator(), false);
  assert.equal(t.auth.isTechnician(), false);
  assert.equal(t.auth.canAssign(), true);
});

test('una sesión incompleta anterior requiere iniciar sesión de nuevo', () => {
  setup();
  localStorage.setItem('j2f_user', JSON.stringify({ id: 3, full_name: 'Anterior',
    profiles: [{ id: 1, name: 'Administrador', state_id: 1 }] }));
  const auth = new AuthService({}, { navigate: () => {} });
  assert.equal(auth.isAuthenticated(), false);
  assert.equal(auth.isAdmin(), false);
});

test('las mutaciones de menú notifican al sidebar después de completarse', () => {
  const client = {
    post: () => rx.of({}),
    put: () => rx.of({}),
    delete: () => rx.of({}),
  };
  const users = new UserService(client);
  let changes = 0;
  users.menuChanges.subscribe(() => changes++);
  users.createMenuOption({ name: 'Nueva' }).subscribe();
  users.updateMenuOption(1, { state_id: 2 }).subscribe();
  users.deleteMenuOption(1).subscribe();
  assert.equal(changes, 3);
});

test('el sidebar elige el menú configurado o el respaldo, nunca ambos', () => {
  const render = response => {
    injectedAuth = {
      isAdmin: () => true,
      hasActiveProfile: () => true,
      profileChanges: new rx.Subject(),
      menuChanges: new rx.Subject(),
      getMenuOptions: () => response,
    };
    const sidebar = new SidebarComponent();
    sidebar.ngOnInit();
    const sections = sidebar.navSections;
    sidebar.ngOnDestroy();
    return sections;
  };
  const dynamic = render(rx.of({ configured: true, menu_options: [
    { id: 1, name: 'MONITOREO', url: null, icon: 'folder', state_id: 1, children: [
      { id: 2, name: 'Alertas configuradas', url: '/alerts', icon: 'alerts', state_id: 1 }
    ] }
  ] }));
  assert.equal(dynamic.length, 1);
  assert.equal(dynamic[0].title, 'MONITOREO');
  assert.equal(dynamic[0].items[0].label, 'Alertas configuradas');

  assert.equal(render(rx.of({ configured: false, menu_options: [] })).length, 3);
  assert.equal(render(rx.throwError(() => new Error('API no disponible'))).length, 3);
  assert.deepEqual(render(rx.of({ configured: true, menu_options: [] })), []);
});

test('login multiperfil conserva solo el token temporal y permite seleccionar en dashboard', () => {
  const t = setup();
  t.auth.login('prueba', 'clave').subscribe();
  const profiles = [{ id: 1, name: 'Administrador', state: { name: 'Activo' } },
                    { id: 2, name: 'Técnico', state: { name: 'Activo' } }];
  t.success(0, { access_token: 'temporary', requires_profile_selection: true, profiles,
    user: { id: 3, email: 'multi@example.invalid', full_name: 'Usuario Multi', profiles } });
  assert.equal(t.auth.requiresProfileSelection(), true);
  assert.equal(t.auth.hasActiveProfile(), false);
  assert.equal(localStorage.getItem('j2f_refresh_token'), null);
  t.auth.selectProfile(2).subscribe();
  assert.ok(t.pending[1].request.url.endsWith('/auth/select-profile'));
  t.success(1, { access_token: 'final', refresh_token: 'refresh-final', requires_profile_selection: false,
    profiles, user: { id: 3, email: 'multi@example.invalid', full_name: 'Usuario Multi', profile: profiles[1], profiles } });
  assert.equal(t.auth.currentUser().profile.id, 2);
  assert.equal(t.auth.isTechnician(), true);
  assert.equal(t.auth.isOperator(), false);
  assert.equal(t.auth.canAssign(), false);
});

test('la interfaz requerida está integrada sin pantalla ni modal de selección adicional', () => {
  const dashboard = fs.readFileSync(path.join(root, 'src/app/features/dashboard/dashboard.component.html'), 'utf8');
  const dashboardTs = fs.readFileSync(path.join(root, 'src/app/features/dashboard/dashboard.component.ts'), 'utf8');
  const users = fs.readFileSync(path.join(root, 'src/app/features/admin/users/user-list/user-list.component.html'), 'utf8');
  const alerts = fs.readFileSync(path.join(root, 'src/app/features/alerts/alert-list/alert-list.component.html'), 'utf8');
  const routes = fs.readFileSync(path.join(root, 'src/app/app.routes.ts'), 'utf8');
  assert.match(dashboard, /Bienvenido, \{\{ auth\.currentUser\(\)\?\.full_name \}\}/);
  assert.match(dashboard, /profile-selector/);
  assert.doesNotMatch(dashboard, /Acciones Rápidas|btn-goto-alerts/);
  assert.match(dashboardTs, /if \(this\.auth\.hasActiveProfile\(\)\) this\.startMetrics/);
  assert.match(users, /type="checkbox"/);
  assert.match(alerts, /onClientChange|gps_device_id|event_type_id/);
  assert.match(alerts, /Todos los clientes|filter-client|filter-vehicle/);
  assert.match(alerts, /auth\.canAssign\(\)|assignment-technician|Reasignar/);
  assert.match(routes, /path: 'master-data'[\s\S]*activeProfileGuard/);
  const masters = fs.readFileSync(path.join(root, 'src/app/features/admin/master-data/master-data.component.html'), 'utf8');
  assert.match(masters, /\*ngIf="auth\.isAdmin\(\)"/);
  assert.doesNotMatch(routes, /select-profile/);
});

test('el CRUD muestra rutas y conserva las secciones solo como menús padre', () => {
  const parent = { id: 9, name: 'MONITOREO', url: null, parent_id: null, state_id: 1 };
  const child = { id: 3, name: 'Panel de control', url: '/dashboard', parent_id: 9, state_id: 1 };
  injectedAuth = {
    getMenuOptions: () => rx.of({ menu_options: [parent, child] }),
    getProfiles: () => rx.of({ profiles: [], states: [] }),
  };
  const component = new MenuOptionListComponent();
  component.loadData();
  assert.deepEqual(component.menuOptions().map(option => option.name), ['Panel de control']);
  assert.deepEqual(component.parentOptions().map(option => option.name), ['MONITOREO']);
});
