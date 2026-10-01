import {
  AfterViewInit, Component, EventEmitter, OnDestroy, OnInit, Output,
  ViewEncapsulation, computed, inject, signal,
} from '@angular/core';
import { DecimalPipe, NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import * as L from 'leaflet';
import { AlertService } from '../../core/services/alert.service';
import { AuthService } from '../../core/services/auth.service';
import { MapVehicle } from '../../shared/models/alert.model';

type EventCode = 'SPEEDING' | 'GPS_SIGNAL_LOSS' | 'SOS';
type Point = { lat: number; lng: number; label: string };
type Position = { segment: number; progress: number; lat: number; lng: number; speed: number };

@Component({
  selector: 'app-vehicle-map',
  standalone: true,
  imports: [NgFor, NgIf, DecimalPipe, FormsModule],
  templateUrl: './vehicle-map.component.html',
  styleUrl: './vehicle-map.component.scss',
  encapsulation: ViewEncapsulation.None,
})
export class VehicleMapComponent implements OnInit, AfterViewInit, OnDestroy {
  @Output() eventCreated = new EventEmitter<void>();

  readonly auth = inject(AuthService);
  private readonly alerts = inject(AlertService);
  private map?: L.Map;
  private markers = L.layerGroup();
  private routesLayer = L.layerGroup();
  private timer?: ReturnType<typeof setInterval>;
  private tick = 0;
  private readonly positions = new Map<number, Position>();

  vehicles = signal<MapVehicle[]>([]);
  loading = signal(true);
  running = signal(true);
  selectedVehicle = signal<MapVehicle | null>(null);
  selectedClientId: number | null = null;
  message = signal('');
  error = signal('');
  generatingCode = signal<EventCode | null>(null);

  readonly clients = computed(() => {
    const values = new Map<number, { id: number; business_name: string }>();
    for (const vehicle of this.vehicles()) {
      if (vehicle.client) values.set(vehicle.client.id, vehicle.client);
    }
    return [...values.values()].sort((a, b) => a.business_name.localeCompare(b.business_name));
  });

  private readonly routes: Point[][] = [
    [
      { lat: -12.0478, lng: -77.0622, label: 'Avenida Argentina, Lima' },
      { lat: -12.0561, lng: -77.0448, label: 'Plaza Bolognesi, Lima' },
      { lat: -12.0715, lng: -77.0362, label: 'Avenida Arequipa, Lima' },
      { lat: -12.0891, lng: -77.0378, label: 'Lince, Lima' },
      { lat: -12.1047, lng: -77.0306, label: 'San Isidro, Lima' },
    ],
    [
      { lat: -12.0526, lng: -77.1171, label: 'Callao' },
      { lat: -12.0610, lng: -77.0914, label: 'Carmen de la Legua' },
      { lat: -12.0732, lng: -77.0717, label: 'Avenida Colonial, Lima' },
      { lat: -12.0835, lng: -77.0574, label: 'Cercado de Lima' },
      { lat: -12.0964, lng: -77.0473, label: 'Jesús María, Lima' },
    ],
    [
      { lat: -12.1177, lng: -77.0357, label: 'Miraflores, Lima' },
      { lat: -12.1295, lng: -77.0204, label: 'Surquillo, Lima' },
      { lat: -12.1430, lng: -77.0168, label: 'Surco, Lima' },
      { lat: -12.1587, lng: -76.9917, label: 'Santiago de Surco, Lima' },
      { lat: -12.1738, lng: -76.9870, label: 'San Juan de Miraflores, Lima' },
    ],
  ];

  ngOnInit(): void {
    this.loadVehicles();
    this.timer = setInterval(() => this.advance(), 2000);
  }

  ngAfterViewInit(): void {
    this.map = L.map('fleet-map', { zoomControl: true, attributionControl: true })
      .setView([-12.083, -77.052], 11);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(this.map);
    this.routesLayer.addTo(this.map);
    this.markers.addTo(this.map);
    this.renderMap();
    setTimeout(() => this.map?.invalidateSize(), 0);
  }

  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
    this.map?.remove();
  }

  loadVehicles(): void {
    this.loading.set(true);
    this.alerts.getMapVehicles().subscribe({
      next: ({ vehicles }) => {
        this.vehicles.set(vehicles);
        for (const vehicle of vehicles) this.ensurePosition(vehicle);
        if (this.selectedVehicle()) {
          this.selectedVehicle.set(vehicles.find(v => v.id === this.selectedVehicle()!.id) ?? null);
        }
        this.loading.set(false);
        this.renderMap(true);
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.error || 'No se pudieron cargar los vehículos autorizados');
      },
    });
  }

  filteredVehicles(): MapVehicle[] {
    return this.selectedClientId
      ? this.vehicles().filter(v => v.client?.id === this.selectedClientId)
      : this.vehicles();
  }

  applyClientFilter(): void {
    if (this.selectedVehicle() && this.selectedClientId &&
        this.selectedVehicle()!.client.id !== this.selectedClientId) {
      this.selectedVehicle.set(null);
    }
    this.renderMap(true);
  }

  toggleSimulation(): void {
    this.running.update(value => !value);
  }

  selectVehicle(vehicle: MapVehicle): void {
    this.selectedVehicle.set(vehicle);
    const position = this.positions.get(vehicle.id);
    if (position) this.map?.panTo([position.lat, position.lng]);
  }

  positionFor(vehicle: MapVehicle): Position | undefined {
    return this.positions.get(vehicle.id);
  }

  locationFor(vehicle: MapVehicle): string {
    const position = this.positions.get(vehicle.id);
    if (!position) return 'Sin posición';
    const route = this.routeFor(vehicle);
    return route[position.segment]?.label || 'Lima';
  }

  hasOpenEvent(code: EventCode): boolean {
    return !!this.selectedVehicle()?.open_events.some(event => event.code === code);
  }

  generateEvent(code: EventCode): void {
    const vehicle = this.selectedVehicle();
    const position = vehicle ? this.positions.get(vehicle.id) : undefined;
    if (!vehicle || !position || this.generatingCode()) return;
    if (code === 'SPEEDING') position.speed = Math.max(position.speed, 96);
    if (code === 'GPS_SIGNAL_LOSS') position.speed = 0;
    this.generatingCode.set(code);
    this.error.set('');
    this.alerts.createMapEvent({
      vehicle_id: vehicle.id,
      event_code: code,
      latitude: position.lat,
      longitude: position.lng,
      speed: position.speed,
    }).subscribe({
      next: response => {
        const name = response.alert.event_type?.name || code;
        const event = { alert_id: response.alert.id, code, name,
          priority: response.alert.priority };
        vehicle.open_events = [event, ...vehicle.open_events.filter(item => item.code !== code)];
        this.vehicles.update(items => [...items]);
        this.selectedVehicle.set({ ...vehicle });
        this.message.set(response.message);
        this.generatingCode.set(null);
        this.renderMap();
        this.eventCreated.emit();
        setTimeout(() => this.message.set(''), 4500);
      },
      error: err => {
        this.error.set(err?.error?.error || 'No se pudo registrar el evento');
        this.generatingCode.set(null);
      },
    });
  }

  private ensurePosition(vehicle: MapVehicle): Position {
    const existing = this.positions.get(vehicle.id);
    if (existing) return existing;
    const route = this.routeFor(vehicle);
    const segment = vehicle.id % (route.length - 1);
    const progress = ((vehicle.id * 17) % 70) / 100;
    const point = this.interpolate(route, segment, progress);
    const position = { segment, progress, ...point, speed: 38 + (vehicle.id * 7) % 42 };
    this.positions.set(vehicle.id, position);
    return position;
  }

  private advance(): void {
    if (!this.running()) return;
    this.tick++;
    for (const vehicle of this.vehicles()) {
      const position = this.ensurePosition(vehicle);
      const route = this.routeFor(vehicle);
      position.progress += 0.08 + (vehicle.id % 3) * 0.012;
      if (position.progress >= 1) {
        position.progress -= 1;
        position.segment = (position.segment + 1) % (route.length - 1);
      }
      Object.assign(position, this.interpolate(route, position.segment, position.progress));
      if (!vehicle.open_events.some(event => event.code === 'GPS_SIGNAL_LOSS')) {
        position.speed = 38 + ((vehicle.id * 11 + this.tick * 3) % 43);
      }
    }
    this.renderMap();
  }

  private routeFor(vehicle: MapVehicle): Point[] {
    return this.routes[vehicle.id % this.routes.length];
  }

  private interpolate(route: Point[], segment: number, progress: number): { lat: number; lng: number } {
    const start = route[segment];
    const end = route[segment + 1];
    return {
      lat: start.lat + (end.lat - start.lat) * progress,
      lng: start.lng + (end.lng - start.lng) * progress,
    };
  }

  private renderMap(fit = false): void {
    if (!this.map) return;
    this.markers.clearLayers();
    this.routesLayer.clearLayers();
    const bounds: L.LatLngTuple[] = [];
    const visibleRoutes = new Set<number>();
    for (const vehicle of this.filteredVehicles()) {
      const routeIndex = vehicle.id % this.routes.length;
      if (!visibleRoutes.has(routeIndex)) {
        visibleRoutes.add(routeIndex);
        L.polyline(this.routes[routeIndex].map(point => [point.lat, point.lng]), {
          color: '#52788f', weight: 3, opacity: 0.42, dashArray: '7 8',
        }).addTo(this.routesLayer);
      }
      const position = this.ensurePosition(vehicle);
      const affected = vehicle.open_events.length > 0;
      const node = document.createElement('span');
      node.className = `fleet-marker ${affected ? 'fleet-marker-alert' : ''}`;
      node.textContent = vehicle.plate;
      const icon = L.divIcon({ className: 'fleet-marker-container', html: node,
        iconSize: [64, 28], iconAnchor: [32, 14] });
      const marker = L.marker([position.lat, position.lng], {
        icon, title: vehicle.plate, keyboard: true,
      }).on('click', () => this.selectVehicle(vehicle));
      marker.addTo(this.markers);
      bounds.push([position.lat, position.lng]);
    }
    if (fit && bounds.length) this.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 12 });
  }
}
