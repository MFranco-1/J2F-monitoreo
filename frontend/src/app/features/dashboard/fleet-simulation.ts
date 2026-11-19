/** Parámetros y geometría de la simulación local; nunca representan telemetría GPS real. */
export type Point = { lat: number; lng: number };
export interface SimulationPosition extends Point {
  segment: number;
  progress: number;
  speed: number;
  fuel: number;
  bearing: number;
  updatedAt: Date;
  fuelConfirmationAt?: string;
}

// Valores obtenidos de app_parameters en PostgreSQL; no hay telemetría real.
export { simulationSettings as SIMULATION_SETTINGS, lowFuelThreshold as LOW_FUEL_THRESHOLD } from '../../core/runtime-catalog';
import { simulationSettings as SIMULATION_SETTINGS } from '../../core/runtime-catalog';

export function distanceMeters(a: Point, b: Point): number {
  const lat = ((b.lat - a.lat) * Math.PI) / 180;
  const lng = ((b.lng - a.lng) * Math.PI) / 180;
  const center = ((a.lat + b.lat) * Math.PI) / 360;
  return 6_371_000 * Math.hypot(lat, lng * Math.cos(center));
}

export function bearingDegrees(a: Point, b: Point): number {
  const fromLat = (a.lat * Math.PI) / 180,
    toLat = (b.lat * Math.PI) / 180;
  const deltaLng = ((b.lng - a.lng) * Math.PI) / 180;
  return (
    ((Math.atan2(
      Math.sin(deltaLng) * Math.cos(toLat),
      Math.cos(fromLat) * Math.sin(toLat) -
        Math.sin(fromLat) * Math.cos(toLat) * Math.cos(deltaLng),
    ) *
      180) /
      Math.PI +
      360) %
    360
  );
}

export function initialPosition(
  vehicleId: number,
  route: Point[],
  lowFuel: boolean,
  confirmationAt?: string,
): SimulationPosition {
  if (route.length < 2) throw new Error('El recorrido requiere al menos dos puntos');
  const config = SIMULATION_SETTINGS;
  const segment = (vehicleId * config.initialPositionSpacing) % (route.length - 1);
  const point = route[segment];
  return {
    segment,
    progress: 0,
    ...point,
    speed: config.minSpeedKmh + ((vehicleId * config.vehicleVariation) % config.initialSpeedSpread),
    fuel: lowFuel
      ? config.lowFuelInitialPercent
      : confirmationAt
        ? config.confirmedFuelPercent
        : config.initialFuelMinPercent +
          ((vehicleId * config.vehicleVariation) % config.initialFuelSpread),
    bearing: bearingDegrees(point, route[segment + 1]),
    updatedAt: new Date(),
    fuelConfirmationAt: confirmationAt,
  };
}

export function simulatedSpeed(vehicleId: number, tick: number): number {
  const config = SIMULATION_SETTINGS;
  return (
    config.minSpeedKmh +
    ((vehicleId * config.speedVehicleVariation + tick * config.speedVariationPerTick) %
      config.speedSpread)
  );
}

export function moveAlongRoute(
  state: { segment: number; progress: number },
  points: Point[],
  meters: number,
  stopAtEnd: boolean,
): Point & { bearing: number } {
  if (points.length < 2) throw new Error('El recorrido requiere al menos dos puntos');
  let remaining = Math.max(0, meters);
  while (remaining > 0) {
    if (state.segment >= points.length - 1) {
      if (stopAtEnd) break;
      state.segment = 0;
      state.progress = 0;
    }
    const from = points[state.segment],
      to = points[state.segment + 1];
    const distance = Math.max(1, distanceMeters(from, to));
    const available = distance * (1 - state.progress);
    if (remaining < available) {
      state.progress += remaining / distance;
      remaining = 0;
    } else {
      remaining -= available;
      state.segment++;
      state.progress = 0;
    }
  }
  const from = points[Math.min(state.segment, points.length - 1)];
  const to = points[Math.min(state.segment + 1, points.length - 1)];
  return {
    lat: from.lat + (to.lat - from.lat) * state.progress,
    lng: from.lng + (to.lng - from.lng) * state.progress,
    bearing: from !== to ? bearingDegrees(from, to) : 0,
  };
}
