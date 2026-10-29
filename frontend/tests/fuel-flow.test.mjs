import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(path.join(root, 'src/app/features/dashboard/vehicle-map.component.ts'), 'utf8');
const template = fs.readFileSync(path.join(root, 'src/app/features/dashboard/vehicle-map.component.html'), 'utf8');
const service = fs.readFileSync(path.join(root, 'src/app/core/services/alert.service.ts'), 'utf8');
const simulationSource = fs.readFileSync(path.join(root, 'src/app/features/dashboard/fleet-simulation.ts'), 'utf8');
const simulation = {};
vm.runInThisContext('(function(exports){' + ts.transpileModule(simulationSource, {
  compilerOptions: {module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
}).outputText + '\n})')(simulation);

test('la confirmación exige observación pero no espera a la animación', () => {
  assert.match(component, /const observation = this\.fuelObservation\.trim\(\)/);
  assert.doesNotMatch(component, /action === 'confirm' && !this\.arrivedAtStation/);
  assert.match(template, /La confirmación documentada no depende del recorrido visual/);
});

test('el nivel local simulado solo cambia tras confirmar explícitamente', () => {
  assert.doesNotMatch(component, /position\.fuel = 75/);
  assert.match(component, /if \(action === 'confirm'\)[\s\S]*position\.fuel = SIMULATION_SETTINGS\.confirmedFuelPercent/);
  assert.equal(simulation.SIMULATION_SETTINGS.confirmedFuelPercent,70);
  assert.equal(simulation.LOW_FUEL_THRESHOLD,10);
  assert.match(template, /Telemetría simulada local en este navegador/);
});

test('consultas de abastecimiento tienen alcance de alerta y cancelación', () => {
  assert.match(service, /getFuelStations\(alertId: number/);
  assert.match(service, /set\('alert_id', alertId\)/);
  assert.match(component, /takeUntil\(this\.stationQueryCancel\)/);
  assert.match(component, /isCurrentFuelSelection\(vehicleId, alertId\)/);
  assert.match(component, /this\.auth\.profileChanges/);
});

test('el recorrido a estación conserva separados los índices de la ruta habitual', () => {
  const startTrip = component.slice(component.indexOf('private startTripToStation'),
    component.indexOf('private returnToUsualRoute'));
  assert.match(component, /moveAlongRoute\(trip \|\| position/);
  assert.doesNotMatch(startTrip, /position\.segment\s*=/);
  assert.match(component, /mode: 'return', resumeSegment/);
});

test('los parámetros mantienen las reglas de HU-11 y las posiciones son solo simulación', () => {
  const config=simulation.SIMULATION_SETTINGS;
  assert.equal(config.eventsIntervalMs,10000); assert.equal(config.confirmedFuelPercent,70);
  const route=[{lat:-12,lng:-77},{lat:-12.01,lng:-77.01}];
  const normal=simulation.initialPosition(1,route,false);
  const low=simulation.initialPosition(1,route,true);
  assert.ok(normal.fuel>simulation.LOW_FUEL_THRESHOLD); assert.ok(low.fuel<=simulation.LOW_FUEL_THRESHOLD);
  const confirmation='2026-10-28T18:00:00Z';
  assert.equal(simulation.initialPosition(1,route,false,confirmation).fuel,70);
  assert.ok(simulation.initialPosition(1,route,true,confirmation).fuel<=simulation.LOW_FUEL_THRESHOLD);
  assert.ok(normal.speed>=config.minSpeedKmh);
});

test('la geometría respeta distancia, orientación y llegada sin reiniciar el recorrido habitual', () => {
  const start={lat:-12,lng:-77}; const end={lat:-12.01,lng:-77};
  assert.ok(simulation.distanceMeters(start,end)>1000);
  assert.ok(Math.abs(simulation.bearingDegrees(start,end)-180)<0.001);
  assert.ok(Math.abs(simulation.bearingDegrees(start,{lat:-12,lng:-76.99})-90)<0.01);
  const state={segment:0,progress:0};
  const first=simulation.moveAlongRoute(state,[start,end],100,false);
  assert.ok(first.lat<start.lat && first.lat>end.lat); assert.ok(state.progress>0 && state.progress<1);
  const arrived=simulation.moveAlongRoute(state,[start,end],2000,true);
  assert.equal(arrived.lat,end.lat); assert.equal(arrived.lng,end.lng);
  assert.equal(state.segment,1); assert.equal(state.progress,0);
});

test('la coordinación manual sigue disponible si fallan servicios externos', () => {
  assert.match(template, /Registrar coordinación manual/);
  assert.match(component, /Puedes registrar una coordinación manual documentada/);
});

