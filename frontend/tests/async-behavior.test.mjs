import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import * as rx from 'rxjs';
import * as phoneNumbers from 'libphonenumber-js/max';
import '@angular/compiler';
import * as angular from '@angular/core';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let injections = [];
const emptyClass = class {};
const leafletLayer = () => ({ addTo() { return this; }, clearLayers() {} });
const imports = {
  '@angular/core': {
    ...angular,
    Component: () => value => value,
    Injectable: () => value => value,
    inject: () => {
      if (!injections.length) throw new Error('Falta dependencia de prueba');
      return injections.shift();
    },
  },
  '@angular/common': {
    NgFor: emptyClass, NgIf: emptyClass, DatePipe: emptyClass,
    DecimalPipe: emptyClass, TitleCasePipe: emptyClass,
  },
  '@angular/forms': { FormsModule: emptyClass },
  '@angular/router': { RouterLink: emptyClass, Router: emptyClass, ActivatedRoute: emptyClass },
  '@angular/common/http': { HttpParams: emptyClass, HttpClient: emptyClass },
  rxjs: { ...rx },
  'libphonenumber-js/max': phoneNumbers,
  leaflet: {
    layerGroup: leafletLayer,
    polyline: () => ({ addTo() { return this; }, getBounds() { return []; } }),
    marker: () => ({ on() { return this; }, addTo() { return this; } }),
    circleMarker: () => ({ bindTooltip() { return this; }, on() { return this; }, addTo() { return this; } }),
    divIcon: value => value,
  },
};

const cache = new Map();
function load(relative) {
  const filename = path.resolve(root, relative);
  if (cache.has(filename)) return cache.get(filename);
  const module = { exports: {} };
  cache.set(filename, module.exports);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      experimentalDecorators: true,
    },
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

const { AlertListComponent } = load('src/app/features/alerts/alert-list/alert-list.component.ts');
const { AlertDetailComponent } = load('src/app/features/alerts/alert-detail/alert-detail.component.ts');
const { AlertService } = load('src/app/core/services/alert.service.ts');
const { AssignmentListComponent } = load('src/app/features/assignments/assignment-list/assignment-list.component.ts');
const { HistoryListComponent } = load('src/app/features/history/history-list/history-list.component.ts');
const { MasterDataComponent } = load('src/app/features/admin/master-data/master-data.component.ts');
const { VehicleMapComponent } = load('src/app/features/dashboard/vehicle-map.component.ts');

const auth = (admin = false) => ({
  isAdmin: () => admin, isTechnician: () => false, canAssign: () => true,
  canCancelAlert: () => admin,
  currentUser: () => ({ id: 1 }), profileChanges: new rx.Subject(),
});

test('una alerta con solo título o descripción vacía no se envía', () => {
  const payloads = [];
  injections = [auth(true), {createAlert: data => {payloads.push(data); return rx.of({message:'Creada'});},
    getAlerts: () => rx.of({alerts:[], pages:1})}, {}, {}];
  const component = new AlertListComponent();
  for (const description of [undefined, '', '   ', 'A', '...', '12345']) {
    component.newForm = {title:'Incidencia registrada', description}; component.createAlert();
    assert.match(component.errorMsg(), /Descripción/);
  }
  assert.equal(payloads.length,0);
  component.newForm.description = 'La unidad requiere una revisión documentada'; component.createAlert();
  assert.equal(payloads.length,1);
});

test('la carga de técnicos se consulta al abrir y después de asignar manual o automáticamente', () => {
  const loads = []; const assigned = [];
  const assignment = {
    getTechnicians: () => { const response = new rx.Subject(); loads.push(response); return response; },
    createAssignment: (...args) => {assigned.push(args); return rx.of({message:'Asignada'});},
    autoAssign: () => rx.of({message:'Asignada automáticamente'}),
  };
  injections = [auth(true), {getAlerts: () => rx.of({alerts:[], pages:1})}, assignment, {}];
  const component = new AlertListComponent();
  const alert = {id:1, state:{name:'Abierto'}};
  component.openAssignmentModal(alert);
  assert.equal(loads.length,1); assert.equal(component.loadingTechnicians(),true);
  loads[0].next({technicians:[{id:8, full_name:'Técnico', active_assignments_count:0}]});
  component.assignmentForm.user_id=8; component.assignTechnician();
  assert.equal(assigned.length,1); assert.equal(loads.length,2);
  loads[1].next({technicians:[{id:8, full_name:'Técnico', active_assignments_count:1}]});
  assert.equal(component.technicians()[0].active_assignments_count,1);
  component.autoAssign(2); assert.equal(loads.length,3);
  loads[2].next({technicians:[{id:8, full_name:'Técnico', active_assignments_count:2}]});
  assert.equal(component.technicians()[0].active_assignments_count,2);
  component.ngOnDestroy();
});

test('consultas antiguas de técnicos y perfiles sin permiso no conservan cargas ajenas', () => {
  const loads = []; const session = auth(true);
  injections = [session, {}, {getTechnicians: () => {const response=new rx.Subject(); loads.push(response); return response;}}, {}];
  const component = new AlertListComponent();
  component.loadTechnicians(); component.loadTechnicians();
  loads[1].next({technicians:[{id:2, active_assignments_count:4}]});
  loads[0].next({technicians:[{id:1, active_assignments_count:9}]});
  assert.equal(component.technicians()[0].id,2);
  session.canAssign = () => false; component.loadTechnicians();
  loads[1].next({technicians:[{id:2, active_assignments_count:5}]});
  assert.deepEqual(component.technicians(),[]); assert.equal(loads.length,2);
  component.ngOnDestroy();
});

test('la ventana refresca cargas cada cinco segundos y detiene polling al destruir o perder permisos', () => {
  const ticks = new rx.Subject(); const oldInterval = imports.rxjs.interval;
  let component;
  try {
    imports.rxjs.interval = ms => {assert.equal(ms,5000); return ticks;};
    let requests=0, workload=0; const session=auth(true);
    injections = [session, {getAlerts: () => rx.of({alerts:[],pages:1})}, {
      getTechnicians: () => {requests++; return rx.of({technicians:[{id:1,active_assignments_count:workload}]});},
    }, {clients: () => rx.of({clients:[]}), eventTypes: () => rx.of({event_types:[]})}];
    component = new AlertListComponent(); component.ngOnInit();
    assert.equal(requests,1);
    component.openAssignmentModal({id:1,state:{name:'Abierto'}}); assert.equal(requests,2);
    workload=3; ticks.next(); assert.equal(requests,3);
    assert.equal(component.technicians()[0].active_assignments_count,3);
    component.closeAssignmentModal(); ticks.next(); assert.equal(requests,3);
    session.canAssign = () => false; session.profileChanges.next();
    assert.deepEqual(component.technicians(),[]); assert.equal(requests,3);
    component.ngOnDestroy(); ticks.next(); assert.equal(requests,3);
    assert.equal(ticks.observers.length,0); assert.equal(session.profileChanges.observers.length,0);
  } finally {component?.ngOnDestroy(); imports.rxjs.interval=oldInterval;}
});

test('un error en la carga no se presenta como lista vacía de técnicos disponibles', () => {
  injections = [auth(true), {}, {getTechnicians: () => rx.throwError(() => ({error:{error:'Servicio no disponible'}}))}, {}];
  const component = new AlertListComponent(); component.loadTechnicians();
  assert.equal(component.technicianError(),'Servicio no disponible');
  assert.equal(component.loadingTechnicians(),false);
  assert.deepEqual(component.technicians(),[]);
  component.ngOnDestroy();
});

test('anulación distingue ruta antigua no disponible de una denegación real de permisos', () => {
  const errors = new rx.Subject();
  injections = [auth(true), {}, {cancelAlert: () => errors}, {}];
  const component = new AlertDetailComponent();
  component.alert.set({id:1,state:{name:'Abierto'}}); component.cancellationReason='Caso duplicado documentado';
  component.cancelAlert(); errors.error({status:404,error:{error:'Not Found'}});
  assert.match(component.errorMsg(), /backend.*ruta de anulación/);
  assert.equal(component.cancelling(),false); assert.equal(component.alert().state.name,'Abierto');
  const denied = new rx.Subject();
  injections = [auth(true), {}, {cancelAlert: () => denied}, {}];
  const another = new AlertDetailComponent();
  another.alert.set({id:2,state:{name:'Abierto'}}); another.cancellationReason='Caso duplicado documentado';
  another.cancelAlert(); denied.error({status:403,error:{error:'Solo Administrador y Supervisor pueden anular alertas'}});
  assert.equal(another.errorMsg(),'Solo Administrador y Supervisor pueden anular alertas');
});

test('el servicio de anulación usa POST con motivo, no elimina el registro', () => {
  const requests = [];
  const service = new AlertService({ post: (url, data) => { requests.push({ url, data }); return rx.EMPTY; } });
  service.cancelAlert(12, 'Alerta duplicada').subscribe();
  assert.match(requests[0].url, /\/api\/alerts\/12\/cancel$/);
  assert.deepEqual(requests[0].data, { reason: 'Alerta duplicada' });
});

test('ni las notas de asignaciones anteriores son editables cuando se anula su alerta', () => {
  injections = [auth(true), {}];
  const component = new AssignmentListComponent();
  assert.equal(component.canEdit({ user_id: 1, status: 'Anulada', alert_state: 'Anulado' }), false);
  assert.equal(component.canEdit({ user_id: 1, status: 'Reasignada', alert_state: 'Anulado' }), false);
});

test('anular exige permiso, motivo válido y evita solicitudes duplicadas en el detalle', () => {
  const requests = [];
  const response = new rx.Subject();
  const session = auth(true);
  injections = [session, {}, { cancelAlert: (id, reason) => { requests.push({ id, reason }); return response; } }, {}];
  const component = new AlertDetailComponent();
  component.alert.set({ id: 12, title: 'Alerta manual', state: { name: 'Abierto' } });
  for (const reason of ['', '   ', 'A', '...', '12345', 'x'.repeat(1001)]) {
    component.cancellationReason = reason; component.cancelAlert();
  }
  assert.equal(requests.length, 0);
  session.canCancelAlert = () => false;
  component.cancellationReason = 'Se trata de un duplicado'; component.cancelAlert();
  assert.equal(requests.length, 0);
  session.canCancelAlert = () => true;
  component.cancelAlert(); component.cancelAlert();
  assert.equal(requests.length, 1);
  const history = [{ action: 'cancelled', detail: 'Se trata de un duplicado', user_id: 1 }];
  response.next({ message: 'Alerta anulada', alert: { id: 12, state: { name: 'Anulado' }, history } });
  assert.equal(component.canCancel, false);
  assert.equal(component.canAttend, false);
  assert.deepEqual(component.transitions, []);
  assert.deepEqual(component.history(), history);
  assert.equal(component.getActionLabel('cancelled').trim(), 'Anulada');
  assert.equal(component.cancelling(), false);
  component.cancelAlert(); assert.equal(requests.length, 1);
  component.alert.set({ id: 12, state: { name: 'Cerrado' } });
  component.cancelAlert(); assert.equal(requests.length, 1);
});

test('cambiar perfil ignora una respuesta tardía de anulación y recarga el alcance', () => {
  const response = new rx.Subject();
  const session = auth(true);
  const initial = { id: 12, state: { name: 'Abierto' }, history: [] };
  injections = [session, { snapshot: { paramMap: { get: () => '12' } } }, {
    getAlertById: () => rx.of({ alert: initial }), cancelAlert: () => response,
  }, {}];
  const component = new AlertDetailComponent(); component.ngOnInit();
  component.cancellationReason = 'Alerta duplicada'; component.cancelAlert();
  session.canCancelAlert = () => false;
  session.profileChanges.next();
  response.next({ message: 'No restaurar datos anteriores', alert: { id: 12, state: { name: 'Anulado' } } });
  assert.equal(component.canCancel, false);
  assert.equal(component.alert(), initial);
  assert.equal(component.successMsg(), '');
  assert.equal(component.cancelling(), false);
  component.ngOnDestroy();
});

test('desaparecer un caso de combustible no recarga ni recrea la misma alerta automáticamente', () => {
  const fuel = { alert_id: 99, code: 'LOW_FUEL', can_coordinate: true, fuel_status: 'coordinated', fuel_workflow: {} };
  const previous = { id: 1, plate: 'AAA-111', client: { id: 1 }, open_events: [fuel] };
  const current = { ...previous, open_events: [] };
  const stationResponse = new rx.Subject();
  const requests = [];
  injections = [auth(true), {
    getMapVehicles: () => rx.of({ vehicles: [current] }), getFuelStations: () => stationResponse,
    createMapEvent: data => { requests.push(data); return rx.EMPTY; },
  }, {}, { snapshot: { queryParamMap: { get: () => null } } }];
  const component = new VehicleMapComponent();
  component.vehicles.set([previous]); component.selectedVehicle.set(previous);
  const position = { segment: 0, progress: 0, lat: -12, lng: -77, fuel: 8, speed: 30, bearing: 0, updatedAt: new Date() };
  component.positions.set(1, position);
  for (let index = 0; index < 3; index++) component.roadRoutes.set(index, [{ lat: -12, lng: -77 }, { lat: -12.01, lng: -77.01 }]);
  component.consultFuelStations();
  component.loadVehicles();
  stationResponse.next({ stations: [{ id: 'old', name: 'Estación anterior', latitude: -12, longitude: -77 }] });
  assert.deepEqual(component.stations(), []);
  assert.equal(component.selectedVehicle().open_events.length, 0);
  assert.equal(position.fuel, 8);
  component.advance(); assert.equal(requests.length, 0);
  component.simulateLowFuel(); assert.equal(requests.length, 1);
  assert.equal(requests[0].event_code, 'LOW_FUEL');
});

test('la anulación interrumpe el recorrido local sin saltar la posición ni registrar recarga', () => {
  const previous = { id: 1, plate: 'AAA-111', client: { id: 1 }, open_events: [{ alert_id: 99, code: 'LOW_FUEL' }] };
  injections = [auth(true), { getMapVehicles: () => rx.of({ vehicles: [{ ...previous, open_events: [] }] }) }, {}, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  component.vehicles.set([previous]); component.selectedVehicle.set(previous);
  const position = { segment: 0, progress: 0, lat: -12, lng: -77, fuel: 8, speed: 30, bearing: 0, updatedAt: new Date() };
  component.positions.set(1, position);
  component.stationTrips.set(1, { mode: 'station', arrived: false, points: [], segment: 0, progress: 0 });
  component.loadVehicles(); component.advance();
  assert.equal(component.needsRouteRecovery(previous), true);
  assert.equal(position.lat, -12); assert.equal(position.lng, -77);
  assert.equal(position.fuel, 8); assert.equal(position.speed, 0);
});

test('la lista de alertas ignora respuestas antiguas y filtros dependientes atrasados', () => {
  const alertRequests = [];
  const vehicleRequests = [];
  const alertService = { getAlerts: () => {
    const subject = new rx.Subject(); alertRequests.push(subject); return subject;
  } };
  const master = {
    vehicles: () => { const subject = new rx.Subject(); vehicleRequests.push(subject); return subject; },
  };
  injections = [auth(), alertService, {}, master];
  const component = new AlertListComponent();
  component.loadAlerts();
  component.loadAlerts();
  alertRequests[1].next({ alerts: [{ id: 2 }], pages: 2 });
  alertRequests[0].next({ alerts: [{ id: 1 }], pages: 1 });
  assert.equal(component.alerts()[0].id, 2);
  assert.equal(component.totalPages(), 2);

  component.newForm.client_id = 10;
  component.onClientChange();
  component.newForm.client_id = 20;
  component.onClientChange();
  vehicleRequests[1].next({ vehicles: [{ id: 20 }] });
  vehicleRequests[0].next({ vehicles: [{ id: 10 }] });
  assert.deepEqual(component.formVehicles().map(item => item.id), [20]);
});

test('historial y pestañas de datos maestros conservan solo la solicitud vigente', () => {
  const historyRequests = [];
  injections = [{ getGlobalHistory: () => {
    const subject = new rx.Subject(); historyRequests.push(subject); return subject;
  } }];
  const history = new HistoryListComponent();
  history.loadHistory();
  history.loadHistory();
  historyRequests[1].next({ history: [{ id: 2 }], total: 1, pages: 1 });
  historyRequests[0].next({ history: [{ id: 1 }], total: 1, pages: 1 });
  assert.equal(history.history()[0].id, 2);

  const listRequests = [];
  let profileCalls = 0;
  const service = { list: () => {
    const subject = new rx.Subject(); listRequests.push(subject); return subject;
  } };
  injections = [service, { getProfiles: () => { profileCalls++; return rx.of({ states: [] }); } }, auth(false)];
  const masters = new MasterDataComponent();
  masters.ngOnInit();
  masters.select('vehicles');
  masters.select('event-types');
  listRequests[2].next({ event_types: [{ id: 30 }] });
  listRequests[1].next({ vehicles: [{ id: 20 }] });
  listRequests[0].next({ clients: [{ id: 10 }] });
  assert.deepEqual(masters.records().map(item => item.id), [30]);
  assert.equal(profileCalls, 0);
});

test('una confirmación tardía actualiza el auto original sin cambiar la selección nueva', () => {
  const response = new rx.Subject();
  let routeCalls = 0;
  const firstEvent = {
    alert_id: 101, code: 'LOW_FUEL', name: 'Combustible bajo', priority: 'high',
    can_coordinate: true, fuel_status: 'coordinated',
    fuel_workflow: { coordination: { timestamp: '2026-01-01', mode: 'manual' }, confirmation: null },
  };
  const first = { id: 1, plate: 'AAA-111', client: { id: 1, business_name: 'Uno' }, open_events: [firstEvent] };
  const second = { id: 2, plate: 'BBB-222', client: { id: 2, business_name: 'Dos' }, open_events: [] };
  const alerts = {
    recordFuelAction: () => response,
    getMapVehicles: () => rx.of({ vehicles: [first, second] }),
    getStreetRoute: () => { routeCalls++; return rx.of({ coordinates: [], distance_meters: 0 }); },
  };
  injections = [auth(true), alerts, { navigate() {} }, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  component.vehicles.set([first, second]);
  component.positions.set(1, {
    segment: 0, progress: 0, lat: -12, lng: -77, speed: 20,
    fuel: 8, bearing: 0, updatedAt: new Date(),
  });
  component.selectedVehicle.set(first);
  component.fuelObservation = 'Recarga documentada';
  component.recordFuel('confirm');
  component.selectVehicle(second);
  component.fuelObservation = 'Texto del segundo vehículo';
  response.next({ message: 'Confirmado', fuel_status: 'confirmed',
    fuel_workflow: { coordination: firstEvent.fuel_workflow.coordination,
      confirmation: { timestamp: '2026-01-02', mode: 'manual' } } });
  response.complete();
  assert.equal(component.selectedVehicle().id, second.id);
  assert.equal(component.fuelObservation, 'Texto del segundo vehículo');
  assert.equal(component.positions.get(first.id).fuel, 70);
  assert.equal(component.needsRouteRecovery(first), true);
  assert.equal(routeCalls, 0);
});

test('las rutas habituales son circuitos continuos y el retorno fallido queda recuperable', () => {
  const failedReturn = new rx.Subject();
  let calls = 0;
  const alerts = { getStreetRoute: () => {
    calls++;
    if (calls <= 3) return rx.of({ coordinates: [[-12, -77], [-12.01, -77.01]], distance_meters: 1000 });
    return failedReturn;
  } };
  injections = [auth(true), alerts, { navigate() {} }, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  component.loadRoadRoutes();
  const route = component.roadRoutes.get(0);
  assert.deepEqual(route[0], route.at(-1));
  const vehicle = { id: 3, plate: 'CCC-333', client: { id: 1, business_name: 'Uno' }, open_events: [] };
  component.selectedVehicle.set(vehicle);
  component.positions.set(vehicle.id, {
    segment: 0, progress: 0, lat: -12, lng: -77, speed: 30,
    fuel: 70, bearing: 0, updatedAt: new Date(),
  });
  component.recoverUsualRoute(vehicle);
  failedReturn.error(new Error('servicio no disponible'));
  assert.equal(component.needsRouteRecovery(vehicle), true);
  assert.equal(component.positions.get(vehicle.id).speed, 0);
  assert.match(component.error(), /reintentar/i);
});

test('una confirmación persistida nueva corrige combustible local desactualizado', () => {
  const vehicle = {
    id: 5, plate: 'DDD-555', client: { id: 1, business_name: 'Uno' }, open_events: [],
    fuel_confirmation: { alert_id: 50, timestamp: '2026-10-01T12:00:00Z' },
  };
  const alerts = { getMapVehicles: () => rx.of({ vehicles: [vehicle] }) };
  injections = [auth(true), alerts, { navigate() {} }, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  component.positions.set(vehicle.id, {
    segment: 0, progress: 0, lat: -12, lng: -77, speed: 0, fuel: 8,
    bearing: 0, updatedAt: new Date(), fuelConfirmationAt: '2026-09-01T12:00:00Z',
  });
  component.loadVehicles();
  assert.equal(component.positions.get(vehicle.id).fuel, 70);
  assert.equal(component.positions.get(vehicle.id).fuelConfirmationAt,
               vehicle.fuel_confirmation.timestamp);
});

test('el formulario exige cliente y vehículo coherentes solo para LOW_FUEL', () => {
  const payloads = [];
  const alertService = {
    createAlert: payload => { payloads.push({ ...payload }); return rx.of({ message: 'Creada' }); },
    getAlerts: () => rx.of({ alerts: [], pages: 1 }),
  };
  injections = [auth(true), alertService, {}, {}];
  const component = new AlertListComponent();
  component.eventTypes.set([
    { id: 1, code: 'LOW_FUEL', default_priority: 'high' },
    { id: 2, code: 'POWER_CUT', default_priority: 'high' },
  ]);
  component.newForm = { title: 'Combustible', description: 'Nivel bajo que requiere abastecimiento', event_type_id: 1,
    client_id: null, vehicle_id: null };
  component.createAlert();
  assert.equal(payloads.length, 0);
  assert.match(component.errorMsg(), /cliente y un vehículo válido/i);

  component.newForm.client_id = 10;
  component.newForm.vehicle_id = 20;
  component.formVehicles.set([{ id: 20, client_id: 11 }]);
  component.createAlert();
  assert.equal(payloads.length, 0);

  component.formVehicles.set([{ id: 20, client_id: 10 }]);
  component.createAlert();
  assert.equal(payloads.length, 1);

  component.newForm = { title: 'Corte general', description: 'Se detectó un corte de alimentación', event_type_id: 2,
    client_id: null, vehicle_id: null };
  component.createAlert();
  assert.equal(payloads.length, 2);
});

test('Datos Maestros conserva el mensaje del backend al bloquear una desactivación', () => {
  const message = 'Completa primero el abastecimiento de la alerta #25 antes de desactivar el vehículo';
  const service = { update: () => rx.throwError(() => ({ error: { error: message } })) };
  injections = [service, {}, auth(true)];
  const component = new MasterDataComponent();
  component.kind = 'vehicles';
  component.editing.set({ id: 5 });
  component.form = { state_id: 2, client_id: 1, plate: 'ABC-123' };
  component.showModal.set(true);
  component.save();
  assert.equal(component.error(), message);
  assert.equal(component.showModal(), true);
});

test('los tipos nuevos generan alertas sin ofrecer una casilla en el formulario', () => {
  const payloads = [];
  injections = [{ create: (kind, data) => { payloads.push({ kind, data }); return rx.EMPTY; } }, {}, auth(true)];
  const component = new MasterDataComponent();
  component.kind = 'event-types';
  component.states.set([{ id: 1, name: 'Activo' }]);
  component.open();
  Object.assign(component.form, { code: 'ENGINE_START', name: 'Encendido del motor' });
  component.save();
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].kind, 'event-types');
  assert.equal(payloads[0].data.generates_alert, true);
  const html = fs.readFileSync(path.join(root, 'src/app/features/admin/master-data/master-data.component.html'), 'utf8');
  assert.doesNotMatch(html, /form\.generates_alert|Genera alerta/);
});

test('editar un tipo de evento conserva la configuración anterior y exige administrador', () => {
  const payloads = [];
  const session = auth(true);
  injections = [{ update: (kind, id, data) => { payloads.push(data); return rx.EMPTY; } }, {}, session];
  const component = new MasterDataComponent();
  component.kind = 'event-types';
  const record = { id: 7, code: 'ENGINE_START', name: 'Encendido del motor',
    default_priority: 'medium', generates_alert: false, state_id: 1 };
  component.open(record);
  component.form.name = 'Encendido de motor';
  component.save();
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].generates_alert, false);
  assert.equal(record.name, 'Encendido del motor');
  assert.equal(record.generates_alert, false);
  component.saving.set(false);
  session.isAdmin = () => false;
  component.save();
  assert.equal(payloads.length, 1);
});

test('una alerta manual marca el vehículo y Gestionar navega a su detalle', () => {
  const navigations = [];
  injections = [auth(true), {}, { navigate: value => navigations.push(value) }, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  const vehicle = { id: 8, plate: 'MAN-008', client: { id: 1, business_name: 'Uno' },
    open_events: [{ alert_id: 88, code: null, name: 'Revisión manual', priority: 'medium',
      can_coordinate: false, fuel_status: 'pending', fuel_workflow: {} }] };
  assert.equal(component.vehicleStatus(vehicle), 'Con alerta');
  component.manageAlert(88);
  assert.deepEqual(navigations, [['/alerts', 88]]);
  assert.equal(component.vehicleStatus({ ...vehicle, open_events: [] }), 'Operativo');
});

test('el formulario de clientes bloquea los datos inválidos sin hacer peticiones', () => {
  let requests = 0;
  injections = [{ create: () => { requests++; return rx.EMPTY; } }, {}, auth(true)];
  const component = new MasterDataComponent();
  component.form = { document_type: 'RUC', document_number: '3000000028254561', business_name: 'A',
    contact_name: 'A', phone: '987654321h', email: 'hola@gmail.com', address: 'A', state_id: 1 };
  component.save();
  assert.equal(requests, 0);
  assert.equal(component.saving(), false);
  for (const field of ['document_number', 'business_name', 'contact_name', 'phone', 'address'])
    assert.ok(component.fieldErrors()[field]);
});

test('editar un cliente también valida y no envía una letra como razón social', () => {
  let requests = 0;
  injections = [{ update: () => { requests++; return rx.EMPTY; } }, {}, auth(true)];
  const component = new MasterDataComponent();
  component.editing.set({ id: 1 });
  component.form = { document_type: 'RUC', document_number: '20123456789', business_name: 'A', state_id: 1 };
  component.save();
  assert.equal(requests, 0);
  assert.match(component.error(), /Razón social/);
});

test('el mapa rechaza observaciones aisladas sin registrar abastecimiento', () => {
  let requests = 0;
  injections = [auth(true), { recordFuelAction: () => { requests++; return rx.EMPTY; } }, {}, {
    snapshot: { queryParamMap: { get: () => null } },
  }];
  const component = new VehicleMapComponent();
  component.selectedVehicle.set({ id: 1, open_events: [{ code: 'LOW_FUEL', alert_id: 1 }] });
  component.fuelObservation = 'A';
  component.recordFuel('confirm');
  assert.equal(requests, 0);
  assert.match(component.error(), /Observación/);
});

test('cliente RUC se guarda manualmente sin consulta, token ni motivo adicional', () => {
  const payloads = [];
  injections = [{create: (kind, data) => {payloads.push(data); return rx.EMPTY;}}, {}, auth(true)];
  const component = new MasterDataComponent();
  component.open();
  component.form = {document_type:'RUC', document_number:'20123456786', business_name:'Empresa Prueba', state_id:1};
  component.save();
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].business_name, 'Empresa prueba');
  assert.equal('ruc_verification' in payloads[0], false);
});

test('guardar cliente aplica formato de nombres y envía país y número por separado', () => {
  const payloads = [];
  injections = [{create: (kind, data) => {payloads.push(data); return rx.EMPTY;}}, {}, auth(true)];
  const component = new MasterDataComponent(); component.open();
  assert.equal(component.form.phone_country, 'PE');
  Object.assign(component.form, {state_id:1, document_number:'20123456786', business_name:'  tRANSPORTES  ÑANDÚ S.A.C.  ',
    contact_name:'aNA PÉREZ', phone:'987654321', address:'$@? thruno mz 9666'});
  component.save(); assert.equal(payloads.length, 0); assert.ok(component.fieldErrors().address);
  component.form.address='Av. Perú 123, Dpto. 301'; component.save();
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0].business_name, 'Transportes ñandú s.a.c.');
  assert.equal(payloads[0].contact_name, 'Ana pérez');
  assert.equal(payloads[0].phone_country, 'PE'); assert.equal(payloads[0].phone, '987654321');
});

test('editar teléfono internacional no duplica prefijo ni modifica el registro antes de guardar', () => {
  const payloads = [];
  injections = [{update: (kind, id, data) => {payloads.push(data); return rx.EMPTY;}}, {}, auth(true)];
  const component = new MasterDataComponent();
  const record = {id:5, document_type:'RUC', document_number:'20123456786', business_name:'Empresa actual',
    state_id:1, phone:'+34612345678', phone_country:'ES'};
  component.open(record);
  assert.equal(component.form.phone_country, 'ES'); assert.equal(component.form.phone, '612345678');
  assert.equal(record.phone, '+34612345678');
  component.form.phone_country='PE'; component.save();
  assert.equal(payloads.length,0); assert.ok(component.fieldErrors().phone);
  component.form.phone_country='ES'; component.save();
  assert.equal(payloads.length,1); assert.equal(payloads[0].phone,'612345678');
  assert.equal(payloads[0].phone_country,'ES');
  assert.equal(record.phone,'+34612345678');
  const html = fs.readFileSync(path.join(root, 'src/app/features/admin/master-data/master-data.component.html'), 'utf8');
  assert.match(html, /id="client-phone-country"/); assert.match(html, /form\.phone_country/);
});

test('editar razón social no exige API y no envía historial como datos editables', () => {
  const payloads = [];
  injections = [{update: (kind, id, data) => {payloads.push(data); return rx.EMPTY;}}, {}, auth(true)];
  const component = new MasterDataComponent();
  component.open({id:1, document_type:'RUC', document_number:'20123456786', business_name:'Empresa anterior', state_id:1,
    verification:{status:'pending',audit:[]}});
  component.form.business_name = 'Empresa actualizada';
  component.save();
  assert.equal(payloads.length,1);
  assert.equal(payloads[0].business_name, 'Empresa actualizada');
  assert.equal('verification' in payloads[0], false);
});

test('cambiar perfil cierra el formulario y no habilita CRUD para el operador', () => {
  const session = auth(true); let admin = true;
  session.isAdmin = () => admin;
  injections = [{list: () => rx.of({clients:[]}), clients: () => rx.of({clients:[]}), vehicles: () => rx.of({vehicles:[]})},
    {getProfiles: () => rx.of({states:[]})}, session];
  const component = new MasterDataComponent(); component.ngOnInit();
  component.open(); component.form.document_number='20123456786';
  admin=false; session.profileChanges.next();
  assert.equal(component.showModal(), false);
  component.open(); assert.equal(component.showModal(), false);
  component.ngOnDestroy();
});

test('Registrar GPS preselecciona el vehículo y distingue sin equipo de IMEI registrado', () => {
  injections = [{list: () => rx.of({gps_devices:[]})}, {}, auth(true)];
  const component = new MasterDataComponent();
  const vehicle = {id:8, plate:'GPS-008', gps_devices:[]};
  assert.equal(component.gpsLabel(vehicle), 'Sin GPS registrado');
  component.registerGps(vehicle);
  assert.equal(component.kind, 'gps-devices'); assert.equal(component.showModal(), true);
  assert.equal(component.form.vehicle_id, 8);
  assert.match(component.gpsLabel({...vehicle, gps_devices:[{imei:'860000000000001', state:{name:'Activo'}}]}), /860000000000001.*Activo/);
  assert.equal(component.title({serial_number:'GPS-ABC-123',imei:'000000000000018'}), 'GPS-ABC-123');
  assert.match(component.detail({model:'GPS J2F',imei:'000000000000018'}), /GPS J2F.*IMEI 000000000000018/);
  assert.match(component.gpsLabel({...vehicle,gps_devices:[{serial_number:'GPS-ABC-123',imei:'000000000000018',state:{name:'Activo'}}]}), /GPS-ABC-123.*Activo/);
});

test('Datos Maestros conserva la relación GPS-vehículo sin mensajes explicativos adicionales', () => {
  const html = fs.readFileSync(path.join(root, 'src/app/features/admin/master-data/master-data.component.html'), 'utf8');
  assert.match(html, /record\.vehicle\?\.plate/);
  assert.match(html, /<p>No hay registros<\/p>/);
  assert.doesNotMatch(html, /No hay equipos GPS registrados|El mapa utiliza posiciones simuladas|no conecta automáticamente|\bdemo\b|\bprueba\b/i);
});
