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
  rxjs: rx,
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
const { HistoryListComponent } = load('src/app/features/history/history-list/history-list.component.ts');
const { MasterDataComponent } = load('src/app/features/admin/master-data/master-data.component.ts');
const { VehicleMapComponent } = load('src/app/features/dashboard/vehicle-map.component.ts');

const auth = (admin = false) => ({
  isAdmin: () => admin, isTechnician: () => false, canAssign: () => true,
  currentUser: () => ({ id: 1 }), profileChanges: new rx.Subject(),
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
  component.newForm = { title: 'Combustible', event_type_id: 1,
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

  component.newForm = { title: 'Corte general', event_type_id: 2,
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
  component.form = { state_id: 2 };
  component.showModal.set(true);
  component.save();
  assert.equal(component.error(), message);
  assert.equal(component.showModal(), true);
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
