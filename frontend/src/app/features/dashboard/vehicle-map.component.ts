import { AfterViewInit, Component, EventEmitter, OnDestroy, OnInit, Output, ViewEncapsulation, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { catchError, forkJoin, map, of } from 'rxjs';
import * as L from 'leaflet';
import { AlertService } from '../../core/services/alert.service';
import { AuthService } from '../../core/services/auth.service';
import { AlertPriority, FuelStation, MapOpenEvent, MapVehicle, StreetRoute } from '../../shared/models/alert.model';

type EventCode = 'SPEEDING' | 'GPS_SIGNAL_LOSS' | 'SOS' | 'LOW_FUEL';
type Point = { lat: number; lng: number };
type Position = {
  segment: number; progress: number; lat: number; lng: number;
  speed: number; fuel: number; bearing: number; updatedAt: Date;
};
type StationOption = FuelStation & { roadDistance: number; route: StreetRoute };
type StationTrip = { points: Point[]; segment: number; progress: number; arrived: boolean };

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
  private readonly fuelRequests = new Set<number>();

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
    this.loadRoadRoutes();
    this.loadVehicles(true);
    this.movementTimer = setInterval(() => this.advance(), 2000);
    this.eventsTimer = setInterval(() => this.loadVehicles(), 10000);
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
    if (this.movementTimer) clearInterval(this.movementTimer);
    if (this.eventsTimer) clearInterval(this.eventsTimer);
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
          const points = route.coordinates.map(([lat, lng]) => ({ lat, lng }));
          if (points.length >= 2) this.roadRoutes.set(index, points);
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
    this.alerts.getMapVehicles().subscribe({
      next: ({ vehicles }) => {
        const previous = new Map(this.vehicles().map(vehicle => [vehicle.id, vehicle]));
        const selectedId = this.selectedVehicle()?.id;
        this.vehicles.set(vehicles);
        for (const vehicle of vehicles) {
          const position = this.ensurePosition(vehicle);
          const hadFuelAlert = previous.get(vehicle.id)?.open_events.some(event => event.code === 'LOW_FUEL');
          if (position && hadFuelAlert && !this.lowFuelEvent(vehicle)) position.fuel = 75;
        }
        if (selectedId) this.selectedVehicle.set(vehicles.find(vehicle => vehicle.id === selectedId) ?? null);
        this.loading.set(false);
        this.renderMap(initial);
      },
      error: err => {
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
    if (this.selectedVehicle() && this.selectedClientId &&
        this.selectedVehicle()!.client.id !== this.selectedClientId) this.selectedVehicle.set(null);
    this.clearStationRoute();
    this.renderMap(true);
  }

  toggleSimulation(): void { this.running.update(value => !value); }
  selectVehicle(vehicle: MapVehicle): void {
    this.selectedVehicle.set(vehicle);
    this.clearStationRoute();
    const position = this.positions.get(vehicle.id);
    if (position) this.map?.panTo([position.lat, position.lng]);
    this.renderMap();
  }
  positionFor(vehicle: MapVehicle): Position | undefined { return this.positions.get(vehicle.id); }
  locationFor(vehicle: MapVehicle): string {
    const position = this.positions.get(vehicle.id);
    if (!position) return 'Esperando ruta vial';
    if (this.stationTrips.get(vehicle.id)?.arrived) return 'Estación seleccionada';
    if (this.stationTrips.has(vehicle.id)) return 'En ruta a estación';
    return `Posición simulada: ${position.lat.toFixed(5)}, ${position.lng.toFixed(5)}`;
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
  arrivedAtStation(vehicle: MapVehicle): boolean { return !!this.stationTrips.get(vehicle.id)?.arrived; }
  tripInProgress(vehicle: MapVehicle): boolean {
    const trip = this.stationTrips.get(vehicle.id);
    return !!trip && !trip.arrived;
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
          priority: response.alert.priority, can_coordinate: false, fuel_status: 'pending',
        };
        vehicle.open_events = [event, ...vehicle.open_events.filter(item => item.code !== code)];
        this.vehicles.update(items => [...items]);
        if (this.selectedVehicle()?.id === vehicle.id) this.selectedVehicle.set({ ...vehicle });
        this.message.set(response.message);
        this.generatingCode.set(null);
        this.fuelRequests.delete(vehicle.id);
        this.renderMap();
        this.eventCreated.emit();
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
    const position = vehicle ? this.positions.get(vehicle.id) : undefined;
    if (!position) return;
    this.loadingStations.set(true);
    this.error.set('');
    this.clearStationRoute();
    this.alerts.getFuelStations(position.lat, position.lng).subscribe({
      next: ({ stations }) => {
        if (!stations.length) {
          this.loadingStations.set(false);
          this.message.set('No se encontraron estaciones registradas cerca del vehículo');
          return;
        }
        const candidates = stations
          .sort((a, b) => this.distance(position, { lat: a.latitude, lng: a.longitude }) - this.distance(position, { lat: b.latitude, lng: b.longitude }))
          .slice(0, 8);
        forkJoin(candidates.map(station =>
          this.alerts.getStreetRoute(position.lat, position.lng, station.latitude, station.longitude).pipe(
            map(route => ({ ...station, roadDistance: route.distance_meters, route })),
            catchError(() => of(null))
          )
        )).subscribe({
          next: options => {
            const valid = options.filter((item): item is StationOption => item !== null)
              .sort((a, b) => a.roadDistance - b.roadDistance);
            this.stations.set(valid);
            this.loadingStations.set(false);
            if (valid.length) {
              this.renderStations();
              this.chooseStation(valid[0]);
            }
            else this.error.set('No se pudo calcular una ruta vial a las estaciones cercanas');
          },
          error: () => {
            this.loadingStations.set(false);
            this.error.set('No se pudieron calcular las rutas a las estaciones');
          },
        });
      },
      error: err => {
        this.loadingStations.set(false);
        this.error.set(err?.error?.error || 'El servicio de estaciones no está disponible');
      },
    });
  }

  chooseStation(station: StationOption): void {
    const vehicle = this.selectedVehicle();
    if (!vehicle) return;
    this.selectedStation.set(station);
    this.streetRouteLayer.clearLayers();
    const line = L.polyline(station.route.coordinates, { color: '#267d83', weight: 4, opacity: .85 })
      .addTo(this.streetRouteLayer);
    this.map?.fitBounds(line.getBounds(), { padding: [32, 32] });
    this.message.set(`Ruta vial a ${station.name}: ${(station.roadDistance / 1000).toFixed(1)} km`);
  }

  resumeStationTrip(): void {
    const vehicle = this.selectedVehicle();
    const station = this.selectedStation();
    if (vehicle && station && this.lowFuelEvent(vehicle)?.fuel_status === 'coordinated') {
      this.startStationTrip(vehicle, station.route);
    }
  }

  recordFuel(action: 'coordinate' | 'confirm'): void {
    const vehicle = this.selectedVehicle();
    const event = vehicle ? this.lowFuelEvent(vehicle) : undefined;
    if (!vehicle || !event) return;
    const station = this.selectedStation();
    if (action === 'coordinate' && !station) {
      this.error.set('Consulta y selecciona una estación con ruta vial');
      return;
    }
    if (action === 'confirm' && !this.arrivedAtStation(vehicle)) {
      this.error.set('Espera a que el vehículo llegue a la estación');
      return;
    }
    const detail = action === 'coordinate'
      ? `Ruta vial a ${station!.name}, ${(station!.roadDistance / 1000).toFixed(1)} km`
      : `Abastecimiento confirmado para ${vehicle.plate}`;
    this.fuelAction.set(action);
    this.alerts.recordFuelAction(event.alert_id, action, detail).subscribe({
      next: response => {
        if (action === 'coordinate') this.startStationTrip(vehicle, station!.route);
        else {
          const position = this.positions.get(vehicle.id);
          if (position) position.fuel = 75;
          this.stationTrips.delete(vehicle.id);
          vehicle.open_events = vehicle.open_events.filter(item => item.alert_id !== event.alert_id);
          this.eventCreated.emit();
        }
        this.selectedVehicle.set({ ...vehicle });
        this.fuelAction.set(null);
        this.message.set(response.message);
        this.loadVehicles();
      },
      error: err => {
        this.fuelAction.set(null);
        this.error.set(err?.error?.error || 'No se pudo registrar el abastecimiento');
      },
    });
  }

  private startStationTrip(vehicle: MapVehicle, route: StreetRoute): void {
    const points = route.coordinates.map(([lat, lng]) => ({ lat, lng }));
    if (points.length < 2) return;
    this.stationTrips.set(vehicle.id, { points, segment: 0, progress: 0, arrived: false });
    const position = this.positions.get(vehicle.id);
    if (position) {
      position.lat = points[0].lat;
      position.lng = points[0].lng;
      position.segment = 0;
      position.progress = 0;
    }
    if (!this.running()) this.running.set(true);
    this.renderMap();
  }

  private ensurePosition(vehicle: MapVehicle): Position | undefined {
    const existing = this.positions.get(vehicle.id);
    if (existing) return existing;
    const route = this.routeFor(vehicle);
    const segment = route?.length ? (vehicle.id * 37) % (route.length - 1) : 0;
    const point = route?.[segment] || this.routeEndpoints[vehicle.id % this.routeEndpoints.length][0];
    const lowFuel = this.lowFuelEvent(vehicle);
    const position: Position = {
      segment, progress: 0, lat: point.lat, lng: point.lng,
      speed: 38 + (vehicle.id * 7) % 42,
      fuel: lowFuel && lowFuel.fuel_status !== 'confirmed' ? 8 : 58 + (vehicle.id * 7) % 30,
      bearing: route?.[segment + 1] ? this.bearing(point, route[segment + 1]) : 0, updatedAt: new Date(),
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
      this.move(position, points, speed * 2 / 3.6, !!trip);
      if (trip) {
        trip.segment = position.segment;
        trip.progress = position.progress;
        if (position.segment >= points.length - 1) {
          trip.arrived = true;
          position.speed = 0;
          this.message.set(`${vehicle.plate} llegó a la estación seleccionada`);
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

  private move(position: Position, points: Point[], meters: number, stopAtEnd: boolean): void {
    let remaining = meters;
    while (remaining > 0) {
      if (position.segment >= points.length - 1) {
        if (stopAtEnd) break;
        position.segment = 0;
        position.progress = 0;
      }
      const from = points[position.segment], to = points[position.segment + 1];
      const distance = Math.max(1, this.distance(from, to));
      const available = distance * (1 - position.progress);
      if (remaining < available) {
        position.progress += remaining / distance;
        remaining = 0;
      } else {
        remaining -= available;
        position.segment++;
        position.progress = 0;
      }
    }
    const from = points[Math.min(position.segment, points.length - 1)];
    const to = points[Math.min(position.segment + 1, points.length - 1)];
    position.lat = from.lat + (to.lat - from.lat) * position.progress;
    position.lng = from.lng + (to.lng - from.lng) * position.progress;
    if (from !== to) position.bearing = this.bearing(from, to);
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
