// Solo fixtures de pruebas: adapta los ejemplos antiguos al contrato nuevo de la BD.
import fs from 'node:fs';
export const catalogs = JSON.parse(fs.readFileSync(new URL('./catalog-fixture.json', import.meta.url), 'utf8'));
const permissionExamples = {
  Administrador: ['admin', 'assign', 'reports', 'cancel', 'view_all', 'attend'],
  Supervisor: ['supervise', 'assign', 'reports', 'cancel', 'view_all'],
  Operador: ['assign', 'view_all'], Técnico: ['attend'],
};
export function contractFixture(value) {
  if (!value || typeof value !== 'object') return value;
  for (const item of Object.values(value)) contractFixture(item);
  if (value.name === 'Activo' || value.name === 'Inactivo') value.is_active = value.name === 'Activo';
  if (value.state && permissionExamples[value.name] && !value.permissions) value.permissions = permissionExamples[value.name];
  const state = catalogs.states.find(item => item.name === value.name);
  if (state && !value.state) Object.assign(value, {is_active: state.is_active, is_terminal: state.is_terminal, is_resolution: state.is_resolution, code: state.code});
  return value;
}
export function mockPermissions(value) {
  if (value?.isAdmin && !value.hasPermission) value.hasPermission = function(permission) {
    if (permission === 'reports') return !!(this.isAdmin?.() || this.isSupervisor?.());
    if (permission === 'admin') return !!this.isAdmin?.();
    if (permission === 'assign') return !!this.canAssign?.();
    return false;
  };
  return value;
}
export function hydrateCatalog(exports) {
  Object.assign(exports.runtimeCatalog, structuredClone(catalogs));
  Object.assign(exports.simulationSettings, catalogs.parameters.simulation);
  exports.lowFuelThreshold = catalogs.parameters.low_fuel_threshold;
}
