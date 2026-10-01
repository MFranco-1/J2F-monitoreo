import { AfterViewInit, Component, EventEmitter, OnDestroy, OnInit, Output, ViewEncapsulation, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, catchError, forkJoin, map, of, takeUntil } from 'rxjs';
import * as L from 'leaflet';
import { AlertService } from '../../core/services/alert.service';
import { AuthService } from '../../core/services/auth.service';
import { AlertPriority, FuelStation, MapOpenEvent, MapVehicle, StreetRoute } from '../../shared/models/alert.model';

type EventCode = 'SPEEDING' | 'GPS_SIGNAL_LOSS' | 'SOS' | 'LOW_FUEL';
type Point = { lat: number; lng: number };
type Position = {
  segment: number; progress: number; lat: number; lng: number;
  speed: number; fuel: number; bearing: number; updatedAt: Date;
  fuelConfirmationAt?: string;
};
type StationOption = FuelStation & { roadDistance?: number; route?: StreetRoute };
type StationTrip = {
  points: Point[]; segment: number; progress: number; arrived: boolean;
  mode: 'station' | 'return'; resumeSegment?: number;
};

@Component({
  selector: 'app-vehicle-map', standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, DatePipe, FormsModule],
  templateUrl: './vehicle-map.component.html', styleUrl: './vehicle-map.component.scss',
  encapsulation: ViewEncapsulation.None,
})
export class VehicleMapComponent implements OnInit, AfterViewInit, OnDestroy {
  @Output() eventCreated = new EventEmitter<void>();
  readonly auth = inject(AuthService);
  private readonly alerts = inject(AlertService);
  private readonly router = inject(Router);
  private readonly activatedRoute = inject(ActivatedRoute);
  private map?: L.Map;
  private markers = L.layerGroup();
  private simulatedRoutes = L.layerGroup();
  private stationLayer = L.layerGroup();
  private streetRouteLayer = L.layerGroup();
  private movementTimer?: ReturnType<typeof setInterval>;
  private eventsTimer?: ReturnType<typeof setInterval>;
  private tick = 0;
  private readonly positions = new Map<number, Position>();
  private readonly roadRoutes = new Map<number, Point[]>();
  private readonly stationTrips = new Map<number, StationTrip>();
  private readonly routeRecovery = new Set<number>();
  private readonly fuelRequests = new Set<number>();
  private readonly stationQueryCancel = new Subject<void>();
  private readonly destroy$ = new Subject<void>();
  private vehicleRequestId = 0;
  private pendingTrip?: { vehicleId: number; mode: 'station' | 'return' };
  private requestedFuelAlertId?: number;
  private destroyed = false;

  vehicles = signal<MapVehicle[]>([]);
  loading = signal(true);
  loadingRoutes = signal(true);
  running = signal(true);
  selectedVehicle = signal<MapVehicle | null>(null);
  stations = signal<StationOption[]>([]);
  selectedStation = signal<StationOption | null>(null);
  loadingStations = signal(false);
  selectedClientId: number | null = null;
  message = signal('');
  error = signal('');
  generatingCode = signal<EventCode | null>(null);
  fuelAction = signal<'coordinate' | 'confirm' | null>(null);
  fuelObservation = '';

  readonly clients = computed(() => {
    const values = new Map<number, { id: number; business_name: string }>();
    for (const vehicle of this.vehicles()) {
      if (vehicle.client) values.set(vehicle.client.id, vehicle.client);
    }
    return [...values.values()].sort((a, b) => a.business_name.localeCompare(b.business_name));
  });

  // Los extremos se convierten en geometrías viales reales con el servicio de rutas.
  private readonly routeEndpoints: [Point, Point][] = [
    [{ lat: -12.0478, lng: -77.0622 }, { lat: -12.1047, lng: -77.0306 }],
    [{ lat: -12.0526, lng: -77.1171 }, { lat: -12.0964, lng: -77.0473 }],
    [{ lat: -12.1177, lng: -77.0357 }, { lat: -12.1738, lng: -76.9870 }],
  ];

  ngOnInit(): void {
    const requestedAlert = Number(this.activatedRoute.snapshot.queryParamMap.get('fuel_alert'));
    this.requestedFuelAlertId = Number.isInteger(requestedAlert) && requestedAlert > 0 ? requestedAlert : undefined;
    this.loadRoadRoutes();
    this.loadVehicles(true);
    this.movementTimer = setInterval(() => this.advance(), 2000);
    this.eventsTimer = setInterval(() => this.loadVehicles(), 10000);
    this.auth.profileChanges.pipe(takeUntil(this.destroy$)).subscribe(() => {
      this.cancelStationRequests();
      this.selectedVehicle.set(null);
      this.clearStationRoute();
      this.loadVehicles(true);
    });
  }

  ngAfterViewInit(): void {
    this.map = L.map('fleet-map', { zoomControl: true, attributionControl: true })
      .setView([-12.083, -77.052], 11);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '&copy; OpenStreetMap contributors',
    }).addTo(this.map);
    this.simulatedRoutes.addTo(this.map);
    this.markers.addTo(this.map);
    this.stationLayer.addTo(this.map);
    this.streetRouteLayer.addTo(this.map);
    this.map.on('zoomend', () => this.updateLabelVisibility());
    this.updateLabelVisibility();
    this.renderMap();
    setTimeout(() => this.map?.invalidateSize(), 0);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    if (this.movementTimer) clearInterval(this.movementTimer);
    if (this.eventsTimer) clearInterval(this.eventsTimer);
    this.cancelStationRequests();
    this.destroy$.next();
    this.destroy$.complete();
    this.stationQueryCancel.complete();
    this.map?.remove();
  }

  private loadRoadRoutes(): void {
    this.loadingRoutes.set(true);
    forkJoin(this.routeEndpoints.map(([start, end]) =>
      this.alerts.getStreetRoute(start.lat, start.lng, end.lat, end.lng).pipe(catchError(() => of(null)))
    )).subscribe({
      next: routes => {
        routes.forEach((route, index) => {
          if (!route) return;
          const forward = route.coordinates.map(([lat, lng]) => ({ lat, lng }));
          // Ida y vuelta por la misma geometría vial: el reinicio coincide con
          // el último punto y evita teletransportes al cerrar el recorrido.
          if (forward.length >= 2) {
            this.roadRoutes.set(index, [...forward, ...forward.slice(0, -1).reverse()]);
          }
        });
        this.loadingRoutes.set(false);
        if (routes.some(route => !route)) this.error.set('Algunas rutas por calles no están disponibles. Esos vehículos permanecerán sin movimiento hasta recargar.');
        for (const vehicle of this.vehicles()) this.ensurePosition(vehicle);
        this.renderMap(true);
      },
      error: err => {
        this.loadingRoutes.set(false);
        this.error.set(err?.error?.error || 'No se pudieron cargar las rutas por calles. Reintenta al actualizar.');
      },
    });
  }

  loadVehicles(initial = false): void {
    if (initial) this.loading.set(true);
    const requestId = ++this.vehicleRequestId;
    this.alerts.getMapVehicles().subscribe({
      next: ({ vehicles }) => {
        if (requestId !== this.vehicleRequestId) return;
        const selectedId = this.selectedVehicle()?.id;
        this.vehicles.set(vehicles);
        for (const vehicle of vehicles) {
          const position = this.ensurePosition(vehicle);
          const confirmationAt = vehicle.fuel_confirmation?.timestamp;
          const hasLowFuel = !!this.lowFuelEvent(vehicle);
          if (position && confirmationAt && position.fuelConfirmationAt !== confirmationAt) {
            if (!hasLowFuel) position.fuel = 70;
            position.fuelConfirmationAt = confirmationAt;
            position.updatedAt = new Date();
          }
        }
        if (selectedId) this.selectedVehicle.set(vehicles.find(vehicle => vehicle.id === selectedId) ?? null);
        if (this.requestedFuelAlertId) {
          const requested = vehicles.find(vehicle =>
            vehicle.open_events.some(event => event.alert_id === this.requestedFuelAlertId));
          if (requested) {
            this.selectedVehicle.set(requested);
            this.requestedFuelAlertId = undefined;
          }
        }
        this.loading.set(false);
        this.renderMap(initial);
      },
      error: err => {
        if (requestId !== this.vehicleRequestId) return;
        this.loading.set(false);
        this.error.set(err?.error?.error || 'No se pudieron actualizar los vehículos autorizados');
      },
    });
  }

  filteredVehicles(): MapVehicle[] {
    return this.selectedClientId
      ? this.vehicles().filter(vehicle => vehicle.client?.id === this.selectedClientId)
      : this.vehicles();
  }

  applyClientFilter(): void {
    this.cancelStationRequests();
    if (this.selectedVehicle() && this.selectedClientId &&
        this.selectedVehicle()!.client.id !== this.selectedClientId) this.selectedVehicle.set(null);
    this.clearStationRoute();
    this.renderMap(true);
  }

  toggleSimulation(): void { this.running.update(value => !value); }
  selectVehicle(vehicle: MapVehicle): void {
    this.cancelStationRequests();
    this.selectedVehicle.set(vehicle);
    this.fuelObservation = '';
    this.clearStationRoute();
    const position = this.positions.get(vehicle.id);
    if (position) this.map?.panTo([position.lat, position.lng]);
    this.renderMap();
  }
  positionFor(vehicle: MapVehicle): Position | undefined { return this.positions.get(vehicle.id); }
  locationFor(vehicle: MapVehicle): string {
    const position = this.positions.get(vehicle.id);
    if (!position) return 'Esperando ruta vial';
    const trip = this.stationTrips.get(vehicle.id);
    if (trip?.mode === 'return') return trip.arrived ? 'Retorno pendiente' : 'Retorno visual a recorrido habitual';
    if (trip?.arrived) return 'Estación seleccionada (posición local simulada)';
    if (trip) return 'Recorrido visual a estación';
    return `Posición local simulada: ${position.lat.toFixed(5)}, ${position.lng.toFixed(5)}`;
  }
  priorityLabel(priority: AlertPriority): string {
    return { critical: 'Crítica', high: 'Alta', medium: 'Media', low: 'Baja' }[priority];
  }
  hasOpenEvent(code: EventCode): boolean {
    return !!this.selectedVehicle()?.open_events.some(event => event.code === code);
  }
  lowFuelEvent(vehicle: MapVehicle): MapOpenEvent | undefined {
    return vehicle.open_events.find(event => event.code === 'LOW_FUEL');
  }
  vehicleStatus(vehicle: MapVehicle): 'Con alerta' | 'Operativo' {
    return vehicle.open_events.length ? 'Con alerta' : 'Operativo';
  }
  arrivedAtStation(vehicle: MapVehicle): boolean { return !!this.stationTrips.get(vehicle.id)?.arrived; }
  needsRouteRecovery(vehicle: MapVehicle): boolean { return this.routeRecovery.has(vehicle.id); }
  recoverUsualRoute(vehicle: MapVehicle): void {
    this.error.set('');
    this.returnToUsualRoute(vehicle);
  }
  tripInProgress(vehicle: MapVehicle): boolean {
    const trip = this.stationTrips.get(vehicle.id);
    return !!trip && !trip.arrived;
  }
  fuelGuidance(event: MapOpenEvent): string {
    if (event.can_coordinate) return this.auth.isAdmin()
      ? 'Como administrador puedes coordinar y confirmar de forma excepcional.'
      : 'Como técnico asignado puedes coordinar y confirmar el abastecimiento.';
    return 'Operador y Supervisor revisan y asignan el caso; la atención corresponde al técnico asignado.';
  }
  manageAlert(id: number): void { this.router.navigate(['/alerts', id]); }
  simulateLowFuel(): void {
    const vehicle = this.selectedVehicle();
    if (!vehicle || this.lowFuelEvent(vehicle)) return;
    const position = this.positions.get(vehicle.id);
    if (!position) return;
    position.fuel = 9;
    this.generateEvent('LOW_FUEL', vehicle);
  }

  generateEvent(code: EventCode, vehicle = this.selectedVehicle()): void {
    const position = vehicle ? this.positions.get(vehicle.id) : undefined;
    if (!vehicle || !position || this.generatingCode() ||
        vehicle.open_events.some(event => event.code === code)) return;
    if (code === 'LOW_FUEL' && position.fuel > 10) return;
    if (code === 'SPEEDING') position.speed = Math.max(position.speed, 96);
    if (code === 'GPS_SIGNAL_LOSS') position.speed = 0;
    this.generatingCode.set(code);
    this.error.set('');
    this.alerts.createMapEvent({
      vehicle_id: vehicle.id, event_code: code, latitude: position.lat,
      longitude: position.lng, speed: position.speed, fuel_percent: code === 'LOW_FUEL' ? position.fuel : undefined,
    }).subscribe({
      next: response => {
        const event: MapOpenEvent = {
          alert_id: response.alert.id, code, name: response.alert.event_type?.name || code,
          priority: response.alert.priority, can_coordinate: this.auth.isAdmin(), fuel_status: 'pending',
          fuel_workflow: { coordination: null, confirmation: null },
        };
        const originalVehicle = this.vehicles().find(item => item.id === vehicle.id) || vehicle;
        originalVehicle.open_events = [event, ...originalVehicle.open_events.filter(item => item.code !== code)];
        this.vehicles.update(items => [...items]);
        if (this.selectedVehicle()?.id === vehicle.id) {
          this.selectedVehicle.set({ ...originalVehicle });
          this.message.set(response.message);
        }
        this.generatingCode.set(null);
        this.fuelRequests.delete(vehicle.id);
        this.renderMap();
        this.eventCreated.emit();
        this.loadVehicles();
        setTimeout(() => this.message.set(''), 4500);
      },
      error: err => {
        this.error.set(err?.error?.error || 'No se pudo registrar el evento');
        this.generatingCode.set(null);
        this.fuelRequests.delete(vehicle.id);
      },
    });
  }

  consultFuelStations(): void {
    const vehicle = this.selectedVehicle();
    const event = vehicle ? this.lowFuelEvent(vehicle) : undefined;
    const position = vehicle ? this.positions.get(vehicle.id) : undefined;
    if (!vehicle || !event || !event.can_coordinate || !position) return;
    this.cancelStationRequests();
    const vehicleId = vehicle.id;
    const alertId = event.alert_id;
    this.loadingStations.set(true);
    this.error.set('');
    this.clearStationRoute();
    this.alerts.getFuelStations(alertId, position.lat, position.lng)
      .pipe(takeUntil(this.stationQueryCancel)).subscribe({
      next: ({ stations }) => {
        if (!this.isCurrentFuelSelection(vehicleId, alertId)) return;
        if (!stations.length) {
          this.loadingStations.set(false);
          this.error.set('No se encontraron estaciones registradas. Puedes documentar una coordinación manual.');
          return;
        }
        const candidates = stations
          .sort((a, b) => this.distance(position, { lat: a.latitude, lng: a.longitude }) - this.distance(position, { lat: b.latitude, lng: b.longitude }))
          .slice(0, 8);
        forkJoin(candidates.map(station =>
          this.alerts.getStreetRoute(position.lat, position.lng, station.latitude, station.longitude, alertId).pipe(
            map(route => ({ ...station, roadDistance: route.distance_meters, route })),
            catchError(() => of({ ...station } as StationOption))
          )
        )).pipe(takeUntil(this.stationQueryCancel)).subscribe({
          next: options => {
            if (!this.isCurrentFuelSelection(vehicleId, alertId)) return;
            const sorted = options.sort((a, b) =>
              (a.roadDistance ?? Number.MAX_VALUE) - (b.roadDistance ?? Number.MAX_VALUE));
            this.stations.set(sorted);
            this.loadingStations.set(false);
            this.renderStations();
            const routed = sorted.find(item => item.route);
            if (routed) this.chooseStation(routed);
            else this.error.set('Se encontraron estaciones, pero el servicio de rutas falló. Puedes seleccionar una y registrar la coordinación documentada.');
          },
          error: () => {
            if (!this.isCurrentFuelSelection(vehicleId, alertId)) return;
            this.loadingStations.set(false);
            this.error.set('No se pudieron calcular las rutas. Puedes registrar una coordinación manual documentada.');
          },
        });
      },
      error: err => {
        if (!this.isCurrentFuelSelection(vehicleId, alertId)) return;
        this.loadingStations.set(false);
        this.error.set((err?.error?.error || 'El servicio de estaciones no está disponible') +
          '. Puedes registrar una coordinación manual documentada.');
      },
    });
  }

  chooseStation(station: StationOption): void {
    const vehicle = this.selectedVehicle();
    if (!vehicle) return;
    this.selectedStation.set(station);
    this.streetRouteLayer.clearLayers();
    if (station.route) {
      const line = L.polyline(station.route.coordinates, { color: '#267d83', weight: 4, opacity: .85 })
        .addTo(this.streetRouteLayer);
      this.map?.fitBounds(line.getBounds(), { padding: [32, 32] });
      this.message.set(`Ruta sugerida a ${station.name}: ${((station.roadDistance || 0) / 1000).toFixed(1)} km`);
    } else {
      this.map?.panTo([station.latitude, station.longitude]);
      this.message.set(`${station.name} seleccionada; no hay una ruta vial disponible.`);
    }
  }

  startPersistedStationTrip(event: MapOpenEvent): void {
    const vehicle = this.selectedVehicle();
    const station = event.fuel_workflow.coordination?.station;
    if (vehicle && station) this.startTripToStation(vehicle, event, station);
  }

  recordFuel(action: 'coordinate' | 'confirm'): void {
    const vehicle = this.selectedVehicle();
    const event = vehicle ? this.lowFuelEvent(vehicle) : undefined;
    if (!vehicle || !event) return;
    const station = this.selectedStation();
    const observation = this.fuelObservation.trim();
    const vehicleId = vehicle.id;
    const alertId = event.alert_id;
    if (!observation) {
      this.error.set(`La observación es obligatoria para ${action === 'confirm' ? 'confirmar' : 'coordinar'} el abastecimiento.`);
      return;
    }
    this.fuelAction.set(action);
    this.alerts.recordFuelAction(event.alert_id, action, observation,
      action === 'coordinate' ? station || undefined : undefined).subscribe({
      next: response => {
        if (this.destroyed) return;
        const originalVehicle = this.vehicles().find(item => item.id === vehicleId) || vehicle;
        const originalEvent = originalVehicle.open_events.find(item => item.alert_id === alertId) || event;
        originalEvent.fuel_status = response.fuel_status;
        originalEvent.fuel_workflow = response.fuel_workflow;
        const stillSelected = this.isCurrentFuelSelection(vehicleId, alertId);
        if (stillSelected && this.fuelObservation.trim() === observation) this.fuelObservation = '';
        if (action === 'coordinate' && station && stillSelected) {
          this.startTripToStation(originalVehicle, originalEvent, station);
        }
        else {
          const position = this.positions.get(vehicleId);
          if (action === 'confirm') {
            if (position) position.fuel = 70;
            if (stillSelected) this.returnToUsualRoute(originalVehicle);
            else if (position) {
              this.stationTrips.set(vehicleId, {
                points: [{ lat: position.lat, lng: position.lng }, { lat: position.lat, lng: position.lng }],
                segment: 1, progress: 0, arrived: true, mode: 'return',
              });
              this.routeRecovery.add(vehicleId);
              position.speed = 0;
            }
            originalVehicle.open_events = originalVehicle.open_events.filter(item => item.alert_id !== alertId);
            this.eventCreated.emit();
          }
        }
        this.vehicles.update(items => [...items]);
        if (stillSelected) this.selectedVehicle.set({ ...originalVehicle });
        this.fuelAction.set(null);
        if (stillSelected) this.message.set(response.message);
        this.loadVehicles();
      },
      error: err => {
        if (this.destroyed) return;
        this.fuelAction.set(null);
        if (this.isCurrentFuelSelection(vehicleId, alertId)) {
          this.error.set(err?.error?.error || 'No se pudo registrar el abastecimiento');
        }
      },
    });
  }

  private startTripToStation(vehicle: MapVehicle, event: MapOpenEvent,
                             station: Pick<FuelStation, 'latitude' | 'longitude' | 'name'>): void {
    const position = this.positions.get(vehicle.id);
    if (!position) return;
    this.cancelStationRequests();
    const vehicleId = vehicle.id;
    const origin = { lat: position.lat, lng: position.lng };
    this.stationTrips.set(vehicleId, {
      points: [origin, origin], segment: 1, progress: 0, arrived: true, mode: 'station',
    });
    this.pendingTrip = { vehicleId, mode: 'station' };
    this.alerts.getStreetRoute(origin.lat, origin.lng, station.latitude, station.longitude,
      event.alert_id).pipe(takeUntil(this.stationQueryCancel)).subscribe({
      next: route => {
        if (!this.isCurrentFuelSelection(vehicleId, event.alert_id)) return;
        this.pendingTrip = undefined;
        const points = [origin,
          ...route.coordinates.map(([lat, lng]) => ({ lat, lng }))];
        this.stationTrips.set(vehicle.id, { points, segment: 0, progress: 0, arrived: false, mode: 'station' });
        if (!this.running()) this.running.set(true);
        this.message.set(`Recorrido visual iniciado hacia ${station.name}. La confirmación no depende de esta animación.`);
        this.renderMap();
      },
      error: err => {
        if (!this.isCurrentFuelSelection(vehicleId, event.alert_id)) return;
        this.pendingTrip = undefined;
        this.stationTrips.delete(vehicleId);
        this.error.set((err?.error?.error || 'No se pudo calcular la ruta desde la posición actual') +
          '. La coordinación quedó registrada y puedes confirmar con una observación.');
      },
    });
  }

  private returnToUsualRoute(vehicle: MapVehicle): void {
    const position = this.positions.get(vehicle.id);
    const usualRoute = this.routeFor(vehicle);
    if (!position || !usualRoute?.length) {
      this.routeRecovery.add(vehicle.id);
      if (position) position.speed = 0;
      this.error.set('No hay una ruta habitual disponible. El vehículo queda detenido en su última posición simulada hasta reintentar.');
      return;
    }
    this.cancelStationRequests();
    const resumeSegment = (position.segment + 1) % usualRoute.length;
    const destination = usualRoute[resumeSegment];
    const current = { lat: position.lat, lng: position.lng };
    this.stationTrips.set(vehicle.id, {
      points: [current, current], segment: 1, progress: 0, arrived: true,
      mode: 'return', resumeSegment,
    });
    this.pendingTrip = { vehicleId: vehicle.id, mode: 'return' };
    this.alerts.getStreetRoute(current.lat, current.lng, destination.lat, destination.lng)
      .pipe(takeUntil(this.stationQueryCancel)).subscribe({
        next: route => {
          this.pendingTrip = undefined;
          const points = [current, ...route.coordinates.map(([lat, lng]) => ({ lat, lng }))];
          this.stationTrips.set(vehicle.id, {
            points, segment: 0, progress: 0, arrived: false, mode: 'return', resumeSegment,
          });
          this.routeRecovery.delete(vehicle.id);
          this.message.set('Abastecimiento confirmado. Nivel local simulado actualizado; retorno visual en curso.');
        },
        error: () => {
          this.pendingTrip = undefined;
          this.routeRecovery.add(vehicle.id);
          position.speed = 0;
          this.error.set('Abastecimiento confirmado. No se pudo calcular el retorno por calles; el vehículo queda detenido en su posición simulada y puedes reintentar.');
        },
      });
  }

  private isCurrentFuelSelection(vehicleId: number, alertId: number): boolean {
    const selected = this.selectedVehicle();
    return !!selected && selected.id === vehicleId &&
      this.lowFuelEvent(selected)?.alert_id === alertId;
  }

  private cancelStationRequests(): void {
    this.stationQueryCancel.next();
    if (this.pendingTrip?.mode === 'station') this.stationTrips.delete(this.pendingTrip.vehicleId);
    if (this.pendingTrip?.mode === 'return') this.routeRecovery.add(this.pendingTrip.vehicleId);
    this.pendingTrip = undefined;
    this.loadingStations.set(false);
  }

  private ensurePosition(vehicle: MapVehicle): Position | undefined {
    const existing = this.positions.get(vehicle.id);
    if (existing) return existing;
    const route = this.routeFor(vehicle);
    if (!route || route.length < 2) return undefined;
    const segment = (vehicle.id * 37) % (route.length - 1);
    const point = route[segment];
    const lowFuel = this.lowFuelEvent(vehicle);
    const position: Position = {
      segment, progress: 0, lat: point.lat, lng: point.lng,
      speed: 38 + (vehicle.id * 7) % 42,
      fuel: lowFuel && lowFuel.fuel_status !== 'confirmed' ? 8 : 58 + (vehicle.id * 7) % 30,
      bearing: this.bearing(point, route[segment + 1]), updatedAt: new Date(),
      fuelConfirmationAt: vehicle.fuel_confirmation?.timestamp,
    };
    this.positions.set(vehicle.id, position);
    return position;
  }

  private advance(): void {
    if (!this.running()) return;
    this.tick++;
    for (const vehicle of this.vehicles()) {
      const position = this.ensurePosition(vehicle);
      if (!position || vehicle.open_events.some(event => event.code === 'GPS_SIGNAL_LOSS')) continue;
      const trip = this.stationTrips.get(vehicle.id);
      if (trip?.arrived) continue;
      const points = trip?.points || this.routeFor(vehicle);
      if (!points?.length) continue;
      const speed = 38 + ((vehicle.id * 11 + this.tick * 3) % 43);
      const motion = this.move(trip || position, points, speed * 2 / 3.6, !!trip);
      position.lat = motion.lat;
      position.lng = motion.lng;
      position.bearing = motion.bearing;
      if (trip) {
        position.speed = speed;
        if (trip.segment >= points.length - 1) {
          trip.arrived = true;
          position.speed = 0;
          if (trip.mode === 'return') {
            position.segment = trip.resumeSegment || 0;
            position.progress = 0;
            this.stationTrips.delete(vehicle.id);
            this.routeRecovery.delete(vehicle.id);
            this.message.set(`${vehicle.plate} volvió visualmente a su recorrido habitual`);
          } else this.message.set(`${vehicle.plate} llegó visualmente a la estación seleccionada`);
        }
      } else {
        position.speed = speed;
      }
      position.fuel = Math.max(0, position.fuel - .015);
      position.updatedAt = new Date();
      if (this.auth.canAssign() && position.fuel <= 10 &&
          !vehicle.open_events.some(event => event.code === 'LOW_FUEL') &&
          !this.fuelRequests.has(vehicle.id) && !this.generatingCode()) {
        this.fuelRequests.add(vehicle.id);
        this.generateEvent('LOW_FUEL', vehicle);
      }
    }
    this.renderMap();
  }

  private move(state: { segment: number; progress: number }, points: Point[], meters: number,
               stopAtEnd: boolean): Point & { bearing: number } {
    let remaining = meters;
    while (remaining > 0) {
      if (state.segment >= points.length - 1) {
        if (stopAtEnd) break;
        state.segment = 0;
        state.progress = 0;
      }
      const from = points[state.segment], to = points[state.segment + 1];
      const distance = Math.max(1, this.distance(from, to));
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
      bearing: from !== to ? this.bearing(from, to) : 0,
    };
  }

  private routeFor(vehicle: MapVehicle): Point[] | undefined {
    return this.roadRoutes.get(vehicle.id % this.routeEndpoints.length);
  }
  private distance(a: Point, b: Point): number {
    const lat = (b.lat - a.lat) * Math.PI / 180;
    const lng = (b.lng - a.lng) * Math.PI / 180;
    const center = (a.lat + b.lat) * Math.PI / 360;
    return 6371000 * Math.hypot(lat, lng * Math.cos(center));
  }
  private bearing(a: Point, b: Point): number {
    return Math.atan2(b.lng - a.lng, b.lat - a.lat) * 180 / Math.PI;
  }

  private renderMap(fit = false): void {
    if (!this.map) return;
    this.markers.clearLayers();
    this.simulatedRoutes.clearLayers();
    const bounds: L.LatLngTuple[] = [];
    const seen = new Set<number>();
    for (const vehicle of this.filteredVehicles()) {
      const routeIndex = vehicle.id % this.routeEndpoints.length;
      const route = this.routeFor(vehicle);
      if (route && !seen.has(routeIndex)) {
        seen.add(routeIndex);
        L.polyline(route.map(point => [point.lat, point.lng]), {
          color: '#718897', weight: 2, opacity: .38, dashArray: '5 7',
        }).addTo(this.simulatedRoutes);
      }
      const position = this.ensurePosition(vehicle);
      if (!position) continue;
      const node = document.createElement('div');
      node.className = `j2f-vehicle-marker${vehicle.open_events.length ? ' has-alert' : ''}${this.selectedVehicle()?.id === vehicle.id ? ' is-selected' : ''}`;
      const car = document.createElement('span');
      car.className = 'j2f-car';
      car.style.transform = `rotate(${position.bearing}deg)`;
      car.innerHTML = '<svg viewBox="0 0 28 32" aria-hidden="true"><rect class="wheel" x="1.3" y="7" width="3.5" height="7" rx="1.1"/><rect class="wheel" x="23.2" y="7" width="3.5" height="7" rx="1.1"/><rect class="wheel" x="1.3" y="20" width="3.5" height="6" rx="1.1"/><rect class="wheel" x="23.2" y="20" width="3.5" height="6" rx="1.1"/><path class="body" d="M8 2.4Q14 .6 20 2.4L23 8V26Q22.5 30 19 30H9Q5.5 30 5 26V8Z"/><path class="windshield" d="M8.6 9.6Q14 7.7 19.4 9.6L20 13.4H8Z"/><path class="rear-window" d="M8.2 23.1H19.8L19.3 26.3H8.7Z"/><path class="roof" d="M9 15H19V21H9Z"/><path class="detail" d="M6.9 4.3H9M19 4.3H21.1"/></svg>';
      const label = document.createElement('span');
      label.className = 'j2f-plate';
      label.textContent = vehicle.plate;
      node.append(car, label);
      L.marker([position.lat, position.lng], {
        icon: L.divIcon({ className: 'j2f-marker-wrap', html: node, iconSize: [30, 32], iconAnchor: [15, 16] }),
        title: vehicle.plate, keyboard: true,
        zIndexOffset: this.selectedVehicle()?.id === vehicle.id ? 1000 : 0,
      }).on('click', () => this.selectVehicle(vehicle)).addTo(this.markers);
      bounds.push([position.lat, position.lng]);
    }
    if (fit && bounds.length) this.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 12 });
  }

  private updateLabelVisibility(): void {
    this.map?.getContainer().classList.toggle('fleet-map-far', this.map.getZoom() < 13);
  }
  private renderStations(): void {
    this.stationLayer.clearLayers();
    for (const station of this.stations()) {
      L.circleMarker([station.latitude, station.longitude], {
        radius: 8, color: '#fff', weight: 2, fillColor: '#267d83', fillOpacity: 1,
      }).bindTooltip(station.name).on('click', () => this.chooseStation(station)).addTo(this.stationLayer);
    }
  }
  private clearStationRoute(): void {
    this.stations.set([]);
    this.selectedStation.set(null);
    this.stationLayer.clearLayers();
    this.streetRouteLayer.clearLayers();
  }
}
