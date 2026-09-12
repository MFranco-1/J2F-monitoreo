import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { MasterKind, Client, Vehicle, GpsDevice, EventType } from '../../shared/models/master-data.model';

@Injectable({ providedIn: 'root' })
export class MasterDataService {
  private readonly base = `${environment.apiUrl}/master-data`;
  constructor(private http: HttpClient) {}
  list<T>(kind: MasterKind, filters: Record<string,string|number|boolean|undefined> = {}) {
    let params = new HttpParams();
    Object.entries(filters).forEach(([key,value]) => { if (value !== undefined) params = params.set(key, String(value)); });
    return this.http.get<Record<string,T[]>>(`${this.base}/${kind}/`, { params });
  }
  clients(active=true) { return this.list<Client>('clients', { active }); }
  vehicles(clientId?:number, active=true) { return this.list<Vehicle>('vehicles', { client_id:clientId, active }); }
  devices(vehicleId?:number, active=true) { return this.list<GpsDevice>('gps-devices', { vehicle_id:vehicleId, active }); }
  eventTypes(active=true) { return this.list<EventType>('event-types', { active }); }
  create(kind:MasterKind, data:any) { return this.http.post<{message:string;record:any}>(`${this.base}/${kind}/`, data); }
  update(kind:MasterKind, id:number, data:any) { return this.http.put<{message:string;record:any}>(`${this.base}/${kind}/${id}`, data); }
  delete(kind:MasterKind, id:number) { return this.http.delete<{message:string}>(`${this.base}/${kind}/${id}`); }
}
