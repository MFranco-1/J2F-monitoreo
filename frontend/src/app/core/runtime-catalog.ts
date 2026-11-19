import { environment } from '../../environments/environment';
export interface CatalogItem { code: string; label: string; rank?: number; }
export interface CatalogState { id: number; name: string; type: string; code: string; is_active: boolean; is_terminal: boolean; is_resolution: boolean; }
export interface SimulationSettings {
  movementIntervalMs: number; eventsIntervalMs: number; confirmedFuelPercent: number;
  lowFuelInitialPercent: number; triggeredLowFuelPercent: number; initialFuelMinPercent: number;
  initialFuelSpread: number; minSpeedKmh: number; initialSpeedSpread: number; speedSpread: number;
  speedVariationPerTick: number; fuelConsumedPerTick: number; speedingEventKmh: number;
  initialPositionSpacing: number; vehicleVariation: number; speedVehicleVariation: number;
  stationCandidates: number; center: [number, number]; initialZoom: number; maxZoom: number;
  tileUrl: string; routes: [{lat: number; lng: number}, {lat: number; lng: number}][];
}
export const runtimeCatalog = {
  priorities: [] as CatalogItem[], document_types: [] as CatalogItem[],
  report_types: [] as {value: string; label: string}[], permissions: [] as {code: string; description: string}[],
  states: [] as CatalogState[], transitions: {} as Record<string, string[]>,
  parameters: {} as Record<string, any>, simulated_events: [] as string[],
};
// Se mantiene la identidad del objeto para los consumidores importados antes del bootstrap.
export const simulationSettings = {} as SimulationSettings;
export let lowFuelThreshold: number;
export async function loadCatalogs(): Promise<void> {
  const response = await fetch(`${environment.apiUrl}/catalogs`);
  if (!response.ok) throw new Error('No se pudieron cargar los catálogos de PostgreSQL');
  const data = await response.json();
  if (!Array.isArray(data.priorities) || !Array.isArray(data.states) || !data.parameters?.simulation)
    throw new Error('Catálogos incompletos: aplica los scripts SQL');
  Object.assign(runtimeCatalog, data);
  Object.assign(simulationSettings, data.parameters.simulation);
  lowFuelThreshold = data.parameters.low_fuel_threshold;
}
export function priorityLabel(code: string): string {
  return runtimeCatalog.priorities.find(item => item.code === code)?.label || code;
}
export function stateName(code: string): string {
  return runtimeCatalog.states.find(item => item.code === code)?.name || code;
}
