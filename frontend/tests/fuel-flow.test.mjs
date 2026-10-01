import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(path.join(root, 'src/app/features/dashboard/vehicle-map.component.ts'), 'utf8');
const template = fs.readFileSync(path.join(root, 'src/app/features/dashboard/vehicle-map.component.html'), 'utf8');
const service = fs.readFileSync(path.join(root, 'src/app/core/services/alert.service.ts'), 'utf8');

test('la confirmación exige observación pero no espera a la animación', () => {
  assert.match(component, /const observation = this\.fuelObservation\.trim\(\)/);
  assert.doesNotMatch(component, /action === 'confirm' && !this\.arrivedAtStation/);
  assert.match(template, /La confirmación documentada no depende del recorrido visual/);
});

test('el nivel local simulado solo cambia tras confirmar explícitamente', () => {
  assert.doesNotMatch(component, /position\.fuel = 75/);
  assert.match(component, /if \(action === 'confirm'\)[\s\S]*position\.fuel = 70/);
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
  assert.match(component, /this\.move\(trip \|\| position/);
  assert.doesNotMatch(startTrip, /position\.segment\s*=/);
  assert.match(component, /mode: 'return', resumeSegment/);
});

test('la coordinación manual sigue disponible si fallan servicios externos', () => {
  assert.match(template, /Registrar coordinación manual/);
  assert.match(component, /Puedes registrar una coordinación manual documentada/);
});

